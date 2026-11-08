"""Настройки провайдеров моделей. Секреты — только из переменных окружения."""

import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

DEFAULT_LOCAL_URL = "http://localhost:8080/v1"
YANDEX_URL = "https://llm.api.cloud.yandex.net/v1"
GIGACHAT_URL = "https://gigachat.devices.sberbank.ru/api/v1"
# Сертификат GigaChat подписан корневым сертификатом НУЦ Минцифры («Russian Trusted Root CA»,
# до 27.02.2032), которого нет в certifi: без него — CERTIFICATE_VERIFY_FAILED. Лежит рядом
# со шлюзом; GIGACHAT_CA_BUNDLE в .env нужен, только если сертификат другой
GIGACHAT_CA = Path(__file__).with_name("certs") / "russian_trusted_root_ca.pem"

# ₽ за 1000 токенов с НДС, синхронный режим: (вход, выход). Прайсы Yandex AI Studio
# и GigaChat API для юрлиц на 16.10.2026. Цена из .env важнее таблицы.
PRICES_RUB_PER_1K: dict[str, tuple[float, float]] = {
    "yandexgpt-5.1": (0.8, 0.8),  # YandexGPT Pro 5.1
    "yandexgpt-5-pro": (1.2, 1.2),
    "yandexgpt-5-lite": (0.2, 0.2),  # объявлена устаревшей, отключат 15.11.2026
    "aliceai-llm": (0.5, 1.2),
    "GigaChat-2": (0.065, 0.065),  # GigaChat 2 Lite
    "GigaChat-2-Pro": (0.5, 0.5),
    "GigaChat-2-Max": (0.65, 0.65),
}


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    base_url: str
    api_key: str | None
    model: str
    timeout_s: float = 90.0
    # Рубли за 1000 токенов; у локальной модели 0.
    rub_per_1k_input: float = 0.0
    rub_per_1k_output: float = 0.0
    # llama.cpp с Qwen3: выключаем режим рассуждений через chat_template_kwargs.
    local: bool = False
    # Дополнительные заголовки запроса: у Yandex — OpenAI-Project с каталогом.
    headers: tuple[tuple[str, str], ...] = ()
    # Задан — провайдер получает токен по OAuth (GigaChat), api_key — ключ авторизации.
    oauth_scope: str | None = None
    # Корневой сертификат, которого нет в certifi (НУЦ Минцифры у GigaChat).
    ca_bundle: str | None = None
    # Сколько запросов держит провайдер одновременно (слоты llama.cpp); None — без очереди.
    max_concurrency: int | None = None


def public_model(model: str) -> str:
    """gpt://<каталог>/yandexgpt-5.1 → yandexgpt-5.1: каталог в журнале и на экране не нужен."""
    return re.sub(r"^gpt://[^/]+/", "", model)


def load_env(path: str | Path | None = None) -> None:
    """Подхватывает .env, не перетирая уже заданные переменные. Нужен только скриптам и eval:
    в воркере окружение приходит из env_file compose, python-dotenv в образ не ставим."""
    from dotenv import load_dotenv

    load_dotenv(path, override=False)


def _prices(prefix: str, model: str) -> tuple[float, float]:
    """Без цены облачный вызов попал бы в стоимость сделки как бесплатный — лучше упасть."""
    rin = os.environ.get(f"{prefix}_RUB_PER_1K_IN")
    rout = os.environ.get(f"{prefix}_RUB_PER_1K_OUT")
    if rin is not None and rout is not None:
        return float(rin), float(rout)
    if model not in PRICES_RUB_PER_1K:
        raise ValueError(
            f"нет цены для модели {model}: задай {prefix}_RUB_PER_1K_IN и {prefix}_RUB_PER_1K_OUT"
        )
    tin, tout = PRICES_RUB_PER_1K[model]
    return float(rin) if rin is not None else tin, float(rout) if rout is not None else tout


def _env(*names: str, default: str | None = None) -> str | None:
    """Первая непустая переменная: у ядра свои имена (docs/AGENTS.md), у шлюза — прежние."""
    return next((v for n in names if (v := os.environ.get(n))), default)


def local_qwen_from_env() -> ProviderConfig:
    return ProviderConfig(
        name="qwen-local",
        base_url=_env("LLM_BASE_URL", "LOCAL_LLM_BASE_URL", default=DEFAULT_LOCAL_URL) or "",
        api_key=os.environ.get("LLM_KEY"),
        model=_env("LLM_MODEL", "LOCAL_LLM_MODEL", default="qwen3-14b") or "",
        timeout_s=float(os.environ.get("LLM_TIMEOUT_S", "90")),
        local=True,
        # По числу слотов llama-server (--parallel): у Qwen на ПК их 3
        max_concurrency=_concurrency("LLM_MAX_CONCURRENCY", 3),
    )


def reserve_from_env() -> ProviderConfig | None:
    """Облачный резерв с OpenAI-совместимым API. Не задан — резерва нет."""
    base_url = os.environ.get("RESERVE_BASE_URL")
    if not base_url:
        return None
    return ProviderConfig(
        name=os.environ.get("RESERVE_NAME", "reserve"),
        base_url=base_url,
        api_key=os.environ.get("RESERVE_KEY"),
        model=os.environ["RESERVE_MODEL"],
        timeout_s=float(os.environ.get("RESERVE_TIMEOUT_S", "60")),
        rub_per_1k_input=float(os.environ.get("RESERVE_RUB_PER_1K_IN", "0")),
        rub_per_1k_output=float(os.environ.get("RESERVE_RUB_PER_1K_OUT", "0")),
    )


def yandexgpt_from_env() -> ProviderConfig | None:
    """YandexGPT через OpenAI-совместимый API AI Studio. Нет ключа — провайдера нет."""
    key = os.environ.get("YANDEX_API_KEY")
    if not key:
        return None
    folder = os.environ["YANDEX_FOLDER_ID"]
    model = os.environ.get("YANDEX_MODEL", "yandexgpt-5.1")
    rin, rout = _prices("YANDEX", model)
    return ProviderConfig(
        name="yandexgpt",
        base_url=os.environ.get("YANDEX_BASE_URL", YANDEX_URL),
        api_key=key,
        model=f"gpt://{folder}/{model}",
        timeout_s=float(os.environ.get("YANDEX_TIMEOUT_S", "60")),
        rub_per_1k_input=rin,
        rub_per_1k_output=rout,
        headers=(("OpenAI-Project", folder),),
        # Квота одновременных сессий у ключа: на 4 eval шёл без 429, больше — 429
        max_concurrency=_concurrency("YANDEX_MAX_CONCURRENCY", 4),
    )


def gigachat_from_env() -> ProviderConfig | None:
    """GigaChat API. GIGACHAT_API_KEY (прежнее имя GIGACHAT_AUTH_KEY) — «ключ авторизации»
    из личного кабинета."""
    key = _env("GIGACHAT_API_KEY", "GIGACHAT_AUTH_KEY")
    if not key:
        return None
    model = os.environ.get("GIGACHAT_MODEL", "GigaChat-2-Max")
    rin, rout = _prices("GIGACHAT", model)
    scope = os.environ.get("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")
    # Ключ физлица (GIGACHAT_API_PERS) держит один поток: параллельные части разбора
    # получали HTTP 429, и резерв не срабатывал (US-23, 25.10). Части ждут очереди;
    # у B2B и CORP — без ограничения
    default_concurrency = 1 if scope == "GIGACHAT_API_PERS" else None
    return ProviderConfig(
        name="gigachat",
        base_url=os.environ.get("GIGACHAT_BASE_URL", GIGACHAT_URL),
        api_key=key,
        model=model,
        timeout_s=float(os.environ.get("GIGACHAT_TIMEOUT_S", "60")),
        rub_per_1k_input=rin,
        rub_per_1k_output=rout,
        oauth_scope=scope,
        ca_bundle=os.environ.get("GIGACHAT_CA_BUNDLE") or str(GIGACHAT_CA),
        max_concurrency=_concurrency("GIGACHAT_MAX_CONCURRENCY", default_concurrency),
    )


PROVIDERS_FROM_ENV: dict[str, Callable[[], ProviderConfig | None]] = {
    "qwen-local": local_qwen_from_env,
    "local": local_qwen_from_env,  # имя из .env.example ядра
    "reserve": reserve_from_env,
    "yandexgpt": yandexgpt_from_env,
    "gigachat": gigachat_from_env,
}


def providers_from_env() -> list[ProviderConfig]:
    """Порядок провайдеров — LLM_PROVIDERS, например «yandexgpt,gigachat»: переход на облако —
    одна строка в .env. Не задан — Qwen на ПК, затем облака, для которых есть ключи."""
    order = os.environ.get("LLM_PROVIDERS")
    default = ",".join(n for n in PROVIDERS_FROM_ENV if n != "local")
    names = [n.strip() for n in (order or default).split(",") if n.strip()]
    configs: list[ProviderConfig] = []
    for name in names:
        if name not in PROVIDERS_FROM_ENV:
            known = ", ".join(PROVIDERS_FROM_ENV)
            raise ValueError(f"неизвестный провайдер {name!r} в LLM_PROVIDERS; есть: {known}")
        cfg = PROVIDERS_FROM_ENV[name]()
        if cfg is None:
            if order:
                raise ValueError(f"провайдер {name} указан в LLM_PROVIDERS, но его ключ не задан")
            continue
        configs.append(cfg)
    return configs


def queue_wait_from_env() -> float | None:
    """Потолок ожидания слота, прежде чем идти к резерву (Ш-15); не задан — по сроку задачи."""
    raw = os.environ.get("LLM_QUEUE_WAIT_S")
    return float(raw) if raw else None


def _concurrency(var: str, default: int | None) -> int | None:
    raw = os.environ.get(var)
    return (int(raw) or None) if raw else default
