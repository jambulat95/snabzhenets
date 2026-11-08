from .config import (
    ProviderConfig,
    gigachat_from_env,
    load_env,
    local_qwen_from_env,
    providers_from_env,
    queue_wait_from_env,
    reserve_from_env,
    yandexgpt_from_env,
)
from .gateway import AgentNotSure, CallResult, Gateway
from .prompts import Prompt, load_prompt
from .providers import GigaChatProvider, OpenAICompatibleProvider, Provider, ProviderError
from .records import CallRecord, CallSink, JsonlSink, MemorySink


def make_provider(cfg: ProviderConfig) -> Provider:
    return GigaChatProvider(cfg) if cfg.oauth_scope else OpenAICompatibleProvider(cfg)


def build_gateway_from_env() -> Gateway:
    """Провайдеры в порядке LLM_PROVIDERS; по умолчанию Qwen на ПК, облака — резерв."""
    return Gateway(
        [make_provider(cfg) for cfg in providers_from_env()], queue_wait_s=queue_wait_from_env()
    )


__all__ = [
    "AgentNotSure",
    "CallRecord",
    "CallResult",
    "CallSink",
    "Gateway",
    "GigaChatProvider",
    "JsonlSink",
    "MemorySink",
    "OpenAICompatibleProvider",
    "Provider",
    "Prompt",
    "ProviderConfig",
    "ProviderError",
    "build_gateway_from_env",
    "gigachat_from_env",
    "load_env",
    "load_prompt",
    "local_qwen_from_env",
    "make_provider",
    "providers_from_env",
    "reserve_from_env",
    "yandexgpt_from_env",
]
