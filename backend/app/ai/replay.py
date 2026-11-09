"""Запись и воспроизведение ответов моделей — чтобы демо работало без интернета (docs/ARCHITECTURE.md, 7).

LLM_REPLAY в .env:
  off            — только живые модели (по умолчанию);
  record         — живые модели, каждый успешный ответ сохраняется в data/replay/llm;
  replay         — только записанные ответы (офлайн; нет записи — шаг уходит человеку, как при сбое модели);
  replay_or_live — сначала запись, нет её — живая модель с записью (режим для защиты).

Ключ записи — хеш системного промпта, текста запроса и схемы ответа. Номер заявки «СН-000123» в ключе
заменяется на «СН-XXXXXX»: письма поставщиков в каждом прогоне демо отличаются только номером.
В файл пишется только ответ модели и его метрики — не входной текст.
"""

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from ..config import settings
from .gateway import Gateway, build_gateway_from_env
from .gateway.config import ProviderConfig, queue_wait_from_env
from .gateway.providers import Completion, Provider, ProviderUnavailable

_NUMBER = re.compile(r"СН-\d{6}")
REPLAY_CFG = ProviderConfig(name="replay", base_url="local://replay", api_key=None, model="запись-ответа")


def directory() -> Path:
    return Path(settings.replay_dir) / "llm"


def key(messages: list[dict[str, str]], json_schema: dict[str, Any]) -> str:
    norm = [{"role": m["role"], "content": _NUMBER.sub("СН-XXXXXX", m["content"])} for m in messages]
    raw = json.dumps([norm, json_schema], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ReplayProvider:
    cfg = REPLAY_CFG

    async def complete(self, messages: list[dict[str, str]], json_schema: dict[str, Any], *, temperature: float,
                       max_tokens: int, seed: int | None, timeout_s: float | None = None) -> Completion:
        path = directory() / f"{key(messages, json_schema)}.json"
        if not path.exists():
            raise ProviderUnavailable("нет записанного ответа для этого запроса")
        data = json.loads(path.read_text("utf-8"))
        return Completion(text=data["text"], prompt_tokens=data["prompt_tokens"],
                          completion_tokens=data["completion_tokens"], latency_ms=1, finish_reason="replay")

    async def aclose(self) -> None:
        return None


class RecordingProvider:
    """Живой провайдер, успешные ответы которого сохраняются для офлайн-демо."""

    def __init__(self, inner: Provider) -> None:
        self.inner = inner
        self.cfg = inner.cfg

    async def complete(self, messages: list[dict[str, str]], json_schema: dict[str, Any], *, temperature: float,
                       max_tokens: int, seed: int | None, timeout_s: float | None = None) -> Completion:
        out = await self.inner.complete(messages, json_schema, temperature=temperature, max_tokens=max_tokens,
                                        seed=seed, timeout_s=timeout_s)
        directory().mkdir(parents=True, exist_ok=True)
        (directory() / f"{key(messages, json_schema)}.json").write_text(json.dumps({
            "text": out.text, "prompt_tokens": out.prompt_tokens, "completion_tokens": out.completion_tokens,
            "provider": self.cfg.name, "model": self.cfg.model.rsplit("/", 1)[-1],
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }, ensure_ascii=False, indent=1), "utf-8")
        return out

    async def aclose(self) -> None:
        await self.inner.aclose()


def gateway() -> Gateway:
    """Шлюз моделей с учётом LLM_REPLAY. Все шаги «Снабженца» берут шлюз отсюда."""
    mode = os.environ.get("LLM_REPLAY", "off").strip().lower()
    if mode == "off":
        return build_gateway_from_env()
    if mode == "replay":
        return Gateway([ReplayProvider()])
    live = build_gateway_from_env().providers
    recording: list[Provider] = [RecordingProvider(p) for p in live]
    if mode == "record":
        return Gateway(recording, queue_wait_s=queue_wait_from_env())
    if mode == "replay_or_live":
        return Gateway([ReplayProvider(), *recording], queue_wait_s=queue_wait_from_env())
    raise ValueError(f"LLM_REPLAY={mode!r}: ожидается off, record, replay или replay_or_live")
