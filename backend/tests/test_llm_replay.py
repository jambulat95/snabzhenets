import asyncio
from pathlib import Path
from typing import Any

import pytest

from app.ai import replay
from app.ai.gateway.config import ProviderConfig
from app.ai.gateway.providers import Completion, ProviderUnavailable
from app.config import settings

SCHEMA: dict[str, Any] = {"type": "object", "properties": {"x": {"type": "integer"}}}


class Fake:
    cfg = ProviderConfig(name="fake", base_url="x", api_key=None, model="gpt://folder/fake-1")

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, messages: list[dict[str, str]], json_schema: dict[str, Any], **kw: Any) -> Completion:
        self.calls += 1
        return Completion(text='{"x": 1}', prompt_tokens=10, completion_tokens=2, latency_ms=5, finish_reason="stop")

    async def aclose(self) -> None:
        return None


def msgs(number: str) -> list[dict[str, str]]:
    return [{"role": "system", "content": "s"}, {"role": "user", "content": f"По запросу {number}: 1. Бумага — 500"}]


def test_key_ignores_procurement_number() -> None:
    assert replay.key(msgs("СН-000004"), SCHEMA) == replay.key(msgs("СН-000123"), SCHEMA)
    assert replay.key(msgs("СН-000004"), SCHEMA) != replay.key(msgs("СН-000004"), {"type": "object"})


def test_record_then_replay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "replay_dir", str(tmp_path))
    fake = Fake()
    rec = replay.RecordingProvider(fake)  # type: ignore[arg-type]
    kw = {"temperature": 0.0, "max_tokens": 100, "seed": 0}
    out = asyncio.run(rec.complete(msgs("СН-000004"), SCHEMA, **kw))
    assert out.text == '{"x": 1}' and fake.calls == 1
    back = asyncio.run(replay.ReplayProvider().complete(msgs("СН-000777"), SCHEMA, **kw))
    assert back.text == '{"x": 1}' and back.finish_reason == "replay"
    saved = next((tmp_path / "llm").glob("*.json")).read_text("utf-8")
    assert "Бумага" not in saved and "fake-1" in saved  # входной текст не сохраняется
    with pytest.raises(ProviderUnavailable):
        asyncio.run(replay.ReplayProvider().complete(msgs("СН-000004"), {"type": "array"}, **kw))
