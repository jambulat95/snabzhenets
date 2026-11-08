from types import SimpleNamespace
from typing import Any

import httpx
from pydantic import BaseModel

from app.ai import runtime
from app.ai.gateway import Gateway, OpenAICompatibleProvider, Prompt, ProviderConfig, switch

PROMPT = Prompt(id="smoke", version=1, system="Ответь.")


class Answer(BaseModel):
    ok: bool


class FakeRedis:
    def __init__(self, fail: bool = False) -> None:
        self.sets: dict[str, set[str]] = {}
        self.fail = fail

    def smembers(self, key: str) -> set[str]:
        if self.fail:
            raise ConnectionError("redis недоступен")
        return set(self.sets.get(key, set()))

    def sadd(self, key: str, value: str) -> None:
        self.sets.setdefault(key, set()).add(value)

    def srem(self, key: str, value: str) -> None:
        self.sets.get(key, set()).discard(value)

    def delete(self, key: str) -> None:
        if self.fail:
            raise ConnectionError("redis недоступен")
        self.sets.pop(key, None)


def test_switch_is_per_sandbox_and_survives_redis_failure() -> None:
    r = FakeRedis()
    assert switch.set_disabled(1, "qwen-local", True, r) == {"qwen-local"}
    assert switch.disabled(1, r) == {"qwen-local"} and switch.disabled(2, r) == set()
    assert switch.set_disabled(1, "qwen-local", False, r) == set()
    switch.set_disabled(1, "qwen-local", True, r)
    switch.clear(1, r)
    assert switch.disabled(1, r) == set()
    # Redis не ответил — работают все провайдеры, сброс не падает; без песочницы Redis не нужен
    assert switch.disabled(1, FakeRedis(fail=True)) == set()
    switch.clear(1, FakeRedis(fail=True))
    assert switch.disabled(None) == set()


class FakeCtx:
    def __init__(self, sandbox_id: int) -> None:
        self.task = SimpleNamespace(sandbox_id=sandbox_id)
        self.calls: list[dict[str, Any]] = []

    def time_left(self) -> float:
        return 120.0

    def tokens_left(self) -> int:
        return 8000

    def record_model_call(self, **kw: Any) -> None:
        self.calls.append(kw)


def provider(name: str, hits: list[str]) -> OpenAICompatibleProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        hits.append(name)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2},
            },
        )

    cfg = ProviderConfig(name=name, base_url="http://x/v1", api_key=None, model=f"{name}-model")
    return OpenAICompatibleProvider(cfg, httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def test_next_task_after_switch_goes_to_reserve(monkeypatch: Any) -> None:
    off = {7: {"qwen-local"}}
    monkeypatch.setattr(switch, "disabled", lambda sandbox_id: off.get(sandbox_id, set()))

    async def pipeline(gw: Gateway) -> bool:
        return (await gw.call(prompt=PROMPT, data="x", schema=Answer)).value.ok

    for sandbox, expected in ((7, "yandexgpt"), (8, "qwen-local")):
        hits: list[str] = []
        ctx = FakeCtx(sandbox)
        provs = [provider("qwen-local", hits), provider("yandexgpt", hits)]
        assert runtime.run_step(ctx, pipeline, providers=provs, cooldown={}) is True
        # Модель видна в журнале: вызов записан с резервной моделью
        assert hits == [expected] and ctx.calls[0]["model"] == f"{expected}-model"
