"""Промпты лежат файлами с версией: prompts/<id>.v<version>.md (раздел 6 ТЗ)."""

from dataclasses import dataclass
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


@dataclass(frozen=True)
class Prompt:
    id: str
    version: int
    system: str


def load_prompt(prompt_id: str, version: int, directory: Path = PROMPTS_DIR) -> Prompt:
    path = directory / f"{prompt_id}.v{version}.md"
    return Prompt(id=prompt_id, version=version, system=path.read_text(encoding="utf-8").strip())
