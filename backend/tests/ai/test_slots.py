import asyncio
import json
import threading
import time
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from app.agents.ml.gateway import (
    Gateway,
    MemorySink,
    OpenAICompatibleProvider,
    Prompt,
    ProviderConfig,
    slots,
)
from app.agents.ml.gateway import gateway as gateway_module

pytestmark = pytest.mark.anyio

PROMPT = Prompt(id="parse_request", version=1, system="Разбери запрос.")
VALID = json.dumps({"name": "Подшипник 6204-2RS"})


class Answer(BaseModel):
    name: str


class SlowServer:
    """Отвечает через delay секунд и считает, сколько запросов было в работе одновременно."""

    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.now = 0
        self.peak = 0
        self.calls = 0
        self._lock = threading.Lock()

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        with self._lock:
            self.now += 1
            self.calls += 1
            self.peak = max(self.peak, self.now)
        await asyncio.sleep(self.delay)
        with self._lock:
            self.now -= 1
        return httpx.Response(200, json={
            "choices": [{"message": {"content": VALID}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        })  # fmt: skip


def provider(name: str, server: SlowServer, **kw: Any) -> OpenAICompatibleProvider:
    cfg = ProviderConfig(name=name, base_url="http://x/v1", api_key="k", model=name, **kw)
    return OpenAICompatibleProvider(cfg, httpx.AsyncClient(transport=httpx.MockTransport(server)))


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def fresh_slots() -> None:
    slots._QUEUES.clear()


async def call(gw: Gateway) -> str:
    return (await gw.call(prompt=PROMPT, data="подшипник", schema=Answer)).provider


async def test_extra_requests_wait_for_a_slot() -> None:
    srv = SlowServer(0.05)
    gw = Gateway([provider("qwen-local", srv, local=True, max_concurrency=2)])
    names = await asyncio.gather(*(call(gw) for _ in range(6)))
    assert names == ["qwen-local"] * 6 and srv.peak == 2


def test_slots_are_shared_between_worker_threads() -> None:
    srv = SlowServer(0.05)

    async def step() -> None:
        # Как поток воркера: свой цикл asyncio и свой шлюз, провайдер тот же
        gw = Gateway([provider("qwen-local", srv, local=True, max_concurrency=3)])
        await asyncio.gather(*(call(gw) for _ in range(4)))

    def task() -> None:
        asyncio.run(step())

    threads = [threading.Thread(target=task) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert srv.calls == 16 and srv.peak == 3


async def test_busy_goes_to_reserve_without_pause() -> None:
    local, cloud = SlowServer(0.3), SlowServer(0.0)
    sink = MemorySink()
    cooldown: dict[str, float] = {}
    qwen = provider("qwen-local", local, local=True, max_concurrency=1)
    gw = Gateway([qwen, provider("yandexgpt", cloud)], sink, cooldown=cooldown, queue_wait_s=0.05)
    names = await asyncio.gather(call(gw), call(gw))
    assert sorted(names) == ["qwen-local", "yandexgpt"]
    assert cooldown == {}  # занят — не отказ: Qwen не уходит на паузу
    assert all(r.success for r in sink.records)  # «занят» — не вызов модели, в журнал не пишется


async def test_cancelled_wait_does_not_leak_a_slot() -> None:
    srv = SlowServer(0.2)
    gw = Gateway([provider("qwen-local", srv, local=True, max_concurrency=1)])
    first = asyncio.create_task(call(gw))
    await asyncio.sleep(0.01)
    waiting = asyncio.create_task(call(gw))
    await asyncio.sleep(0.05)
    waiting.cancel()
    await first
    assert await call(gw) == "qwen-local"  # слот свободен


async def test_without_reserve_waits_for_the_queue() -> None:
    srv = SlowServer(0.1)
    gw = Gateway([provider("qwen-local", srv, local=True, max_concurrency=1)], queue_wait_s=0.05)
    names = await asyncio.gather(*(call(gw) for _ in range(3)))
    assert names == ["qwen-local"] * 3  # ждать 0,05 с — для резерва; без него ждём очереди


async def test_queue_is_first_come_first_served() -> None:
    srv = SlowServer(0.05)
    gw = Gateway([provider("qwen-local", srv, local=True, max_concurrency=1)])
    order: list[int] = []

    async def numbered(n: int) -> None:
        await call(gw)
        order.append(n)

    tasks = []
    for n in range(5):
        tasks.append(asyncio.create_task(numbered(n)))
        await asyncio.sleep(0.005)  # встают в очередь по порядку
    await asyncio.gather(*tasks)
    assert order == [0, 1, 2, 3, 4]


async def test_primary_is_awaited_while_reserve_still_has_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gateway_module, "RESERVE_CALL_S", 4.0)
    local, cloud = SlowServer(2.0), SlowServer(0.0)
    qwen = provider("qwen-local", local, local=True, max_concurrency=1)
    gw = Gateway([qwen, provider("yandexgpt", cloud)]).bind(
        MemorySink(), deadline=time.monotonic() + 4.5
    )
    started = time.monotonic()
    first = asyncio.create_task(call(gw))
    await asyncio.sleep(0.01)
    assert await call(gw) == "yandexgpt"  # Qwen занят дольше, чем резерв может ждать
    assert 0.4 < time.monotonic() - started < 1.5
    assert await first == "qwen-local"


async def test_rate_limit_is_busy_not_down() -> None:
    def limited(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "sessions quota"}})

    cfg = ProviderConfig(name="yandexgpt", base_url="http://x/v1", api_key="k", model="y")
    ya = OpenAICompatibleProvider(cfg, httpx.AsyncClient(transport=httpx.MockTransport(limited)))
    cooldown: dict[str, float] = {}
    gw = Gateway([ya, provider("qwen-local", SlowServer(0.0), local=True)], cooldown=cooldown)
    assert await call(gw) == "qwen-local" and cooldown == {}
