"""Провайдеры моделей за одним интерфейсом."""

import asyncio
import dataclasses
import json
import os
import ssl
import time
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

import certifi
import httpx

from .config import ProviderConfig

GIGACHAT_OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
# Токен GigaChat живёт 30 минут; обновляем заранее, чтобы он не истёк посреди запроса.
TOKEN_MARGIN_S = 60
# Недоступный хост (ПК с Qwen выключен) должен отказать за секунды, а не за таймаут чтения.
CONNECT_TIMEOUT_S = 3.0
# Облако — резерв, когда основной недоступен (US-23): соединение с ним на медленной сети бывает
# дольше 3 с. Упавшее облако после первого отказа всё равно уходит на паузу (COOLDOWN_S)
CLOUD_CONNECT_TIMEOUT_S = 8.0


class ProviderError(Exception):
    """Провайдер не ответил: сеть, таймаут, HTTP-ошибка, неожиданный формат."""


class TransientProviderError(ProviderError):
    """Соединение оборвалось до ответа: запрос можно сразу повторить."""


class ProviderUnavailable(ProviderError):
    """Нет соединения или HTTP 5xx: провайдер лежит, его стоит пропустить на время."""


class ProviderTimeout(ProviderError):
    """Не ответил за отведённое время."""


class ProviderRateLimited(ProviderError):
    """HTTP 429: квота запросов или одновременных сессий (у Yandex — сессий). Провайдер жив."""


@dataclass(frozen=True)
class Completion:
    text: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    finish_reason: str | None
    # Скорость генерации из timings llama.cpp; у облака обычно нет.
    tokens_per_s: float | None = None


class Provider(Protocol):
    cfg: ProviderConfig

    async def complete(
        self,
        messages: list[dict[str, str]],
        json_schema: dict[str, Any],
        *,
        temperature: float,
        max_tokens: int,
        seed: int | None,
        timeout_s: float | None = None,
    ) -> Completion: ...

    async def aclose(self) -> None: ...


def _make_client(cfg: ProviderConfig) -> httpx.AsyncClient:
    if not cfg.ca_bundle:
        return httpx.AsyncClient()
    # GigaChat подписан корневым сертификатом НУЦ Минцифры, которого нет в certifi.
    ctx = ssl.create_default_context(cafile=certifi.where())
    ctx.load_verify_locations(cafile=cfg.ca_bundle)
    return httpx.AsyncClient(verify=ctx)


def _timeout(cfg: ProviderConfig, timeout_s: float | None) -> httpx.Timeout:
    total = cfg.timeout_s if timeout_s is None else min(cfg.timeout_s, timeout_s)
    connect = CONNECT_TIMEOUT_S if cfg.local else CLOUD_CONNECT_TIMEOUT_S
    return httpx.Timeout(total, connect=min(connect, total))


async def _post(
    client: httpx.AsyncClient, url: str, timeout: httpx.Timeout, **kw: Any
) -> httpx.Response:
    try:
        return await client.post(url, timeout=timeout, **kw)
    except (httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError) as e:
        raise TransientProviderError(f"{type(e).__name__}: {e}") from e
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.InvalidURL) as e:
        # InvalidURL — не HTTPError: адрес провайдера в .env не задан или с опечаткой
        raise ProviderUnavailable(f"{type(e).__name__}: {e}") from e
    except httpx.TimeoutException as e:
        raise ProviderTimeout(f"{type(e).__name__}: {e}") from e
    except httpx.HTTPError as e:
        raise ProviderError(f"{type(e).__name__}: {e}") from e


def _parse_completion(resp: httpx.Response, latency_ms: int) -> Completion:
    """Ответ в формате /chat/completions: так отвечают llama.cpp, Yandex и GigaChat v1."""
    if resp.status_code == 429:
        raise ProviderRateLimited(f"HTTP 429: {resp.text[:200]}")
    if resp.status_code >= 500:
        raise ProviderUnavailable(f"HTTP {resp.status_code}: {resp.text[:200]}")
    if resp.status_code != 200:
        raise ProviderError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    try:
        data = resp.json()
        choice = data["choices"][0]
        usage = data.get("usage") or {}
        timings = data.get("timings") or {}
        return Completion(
            text=choice["message"].get("content") or "",
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            latency_ms=latency_ms,
            finish_reason=choice.get("finish_reason"),
            tokens_per_s=timings.get("predicted_per_second"),
        )
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise ProviderError(f"неожиданный ответ: {resp.text[:200]}") from e


class OpenAICompatibleProvider:
    """llama.cpp server, YandexGPT и любой провайдер с /v1/chat/completions."""

    def __init__(self, cfg: ProviderConfig, client: httpx.AsyncClient | None = None) -> None:
        self.cfg = cfg
        self._client = client or _make_client(cfg)

    async def complete(
        self,
        messages: list[dict[str, str]],
        json_schema: dict[str, Any],
        *,
        temperature: float,
        max_tokens: int,
        seed: int | None,
        timeout_s: float | None = None,
    ) -> Completion:
        body: dict[str, Any] = {
            "model": self.cfg.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "answer", "schema": json_schema, "strict": True},
            },
        }
        if seed is not None:
            body["seed"] = seed
        if self.cfg.local:
            body["chat_template_kwargs"] = {"enable_thinking": False}

        headers = dict(self.cfg.headers)
        if self.cfg.api_key:
            headers["Authorization"] = f"Bearer {self.cfg.api_key}"
        url = self.cfg.base_url.rstrip("/") + "/chat/completions"
        started = time.monotonic()
        resp = await _post(
            self._client, url, _timeout(self.cfg, timeout_s), json=body, headers=headers
        )
        return _parse_completion(resp, int((time.monotonic() - started) * 1000))

    async def aclose(self) -> None:
        await self._client.aclose()


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Подставляет $defs на место $ref. В документации GigaChat схемы без ссылок, а Pydantic
    выносит вложенные модели в $defs. Рекурсивных схем у нас нет."""
    defs: dict[str, Any] = schema.get("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, list):
            return [walk(v) for v in node]
        if not isinstance(node, dict):
            return node
        out = {k: walk(v) for k, v in node.items() if k not in ("$ref", "$defs")}
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            return walk(defs[ref.removeprefix("#/$defs/")]) | out
        return out

    result: dict[str, Any] = walk(schema)
    return result


def gigachat_parameters(schema: dict[str, Any]) -> dict[str, Any]:
    """Схема ответа как параметры функции GigaChat: без $ref, title и default. «X или null» —
    просто X и необязательное: null в параметрах функций GigaChat не описан, а пропущенное
    поле дополнит fill_nullable. Иначе модель выдумывает «» вместо отсутствующего артикула."""

    def nullable(node: Any) -> bool:
        variants = node.get("anyOf") if isinstance(node, dict) else None
        return isinstance(variants, list) and any(
            isinstance(v, dict) and v.get("type") == "null" for v in variants
        )

    def walk(node: Any) -> Any:
        if isinstance(node, list):
            return [walk(v) for v in node]
        if not isinstance(node, dict):
            return node
        props = node.get("properties")
        if isinstance(props, dict) and isinstance(node.get("required"), list):
            node = {**node, "required": [k for k in node["required"] if not nullable(props.get(k))]}
        variants = node.get("anyOf")
        if isinstance(variants, list):
            real = [v for v in variants if not (isinstance(v, dict) and v.get("type") == "null")]
            if len(real) == 1 and len(real) < len(variants):
                rest = {k: v for k, v in node.items() if k not in ("anyOf", "default")}
                return walk({**real[0], **rest})
        return {k: walk(v) for k, v in node.items() if k not in ("title", "default")}

    result: dict[str, Any] = walk(inline_refs(schema))
    return result


def fill_nullable(value: Any, schema: dict[str, Any]) -> Any:
    """Обязательные поля, которые могут быть null, а модель их пропустила, — null.
    Схема — после inline_refs; остальное проверит Pydantic."""
    if isinstance(value, list):
        items = schema.get("items")
        return [fill_nullable(v, items) for v in value] if isinstance(items, dict) else value
    if not isinstance(value, dict):
        return value
    props: dict[str, Any] = schema.get("properties") or {}
    out = {k: fill_nullable(v, props[k]) if isinstance(props.get(k), dict) else v
           for k, v in value.items()}  # fmt: skip
    for key in schema.get("required") or []:
        variants = (props.get(key) or {}).get("anyOf") or []
        is_nullable = any(isinstance(v, dict) and v.get("type") == "null" for v in variants)
        if key not in out and is_nullable:
            out[key] = None
    return out


class GigaChatProvider:
    """GigaChat API v1: OAuth-токен по ключу авторизации.

    Ответ по схеме — через вызов функции (GIGACHAT_STRUCTURED=function, по умолчанию): схема
    уходит параметрами функции «answer», модель обязана её вызвать, аргументы и есть ответ.
    response_format с JSON-схемой GigaChat не соблюдает: на проверке US-23 25.10 четыре ответа
    из шести не прошли схему (массив вместо объекта, нет обязательных полей).
    GIGACHAT_STRUCTURED=response_format — прежний способ.
    """

    def __init__(
        self,
        cfg: ProviderConfig,
        client: httpx.AsyncClient | None = None,
        oauth_url: str = GIGACHAT_OAUTH_URL,
    ) -> None:
        if not cfg.api_key or not cfg.oauth_scope:
            raise ValueError("GigaChat: нужны ключ авторизации и scope")
        self.cfg = cfg
        self.oauth_url = oauth_url
        self.structured = os.environ.get("GIGACHAT_STRUCTURED", "function")
        self._client = client or _make_client(cfg)
        self._token: str | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def _access_token(self, stale: str | None = None) -> str:
        async with self._lock:
            fresh = self._token is not None and time.time() < self._expires_at - TOKEN_MARGIN_S
            if fresh and self._token != stale:
                assert self._token is not None
                return self._token
            resp = await _post(
                self._client, self.oauth_url, _timeout(self.cfg, None),
                data={"scope": self.cfg.oauth_scope},
                headers={
                    "Authorization": f"Basic {self.cfg.api_key}",
                    "RqUID": str(uuid.uuid4()),
                    "Accept": "application/json",
                },
            )  # fmt: skip
            if resp.status_code != 200:
                raise ProviderError(f"OAuth HTTP {resp.status_code}: {resp.text[:200]}")
            try:
                data = resp.json()
                token = str(data["access_token"])
                self._expires_at = int(data["expires_at"]) / 1000  # миллисекунды
            except (ValueError, KeyError, TypeError) as e:
                raise ProviderError(f"OAuth: неожиданный ответ: {resp.text[:200]}") from e
            self._token = token
            return token

    async def complete(
        self,
        messages: list[dict[str, str]],
        json_schema: dict[str, Any],
        *,
        temperature: float,
        max_tokens: int,
        seed: int | None,  # у GigaChat нет seed; повторяемость держим низкой температурой
        timeout_s: float | None = None,
    ) -> Completion:
        body: dict[str, Any] = {
            "model": self.cfg.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self.structured == "function":
            body["functions"] = [{
                "name": "answer",
                "description": "Верни ответ: заполни параметры строго по схеме.",
                "parameters": gigachat_parameters(json_schema),
            }]  # fmt: skip
            body["function_call"] = {"name": "answer"}
        else:
            body["response_format"] = {
                "type": "json_schema",
                "schema": inline_refs(json_schema),
                "strict": True,
            }
        url = self.cfg.base_url.rstrip("/") + "/chat/completions"
        token = await self._access_token()
        started = time.monotonic()
        resp = await _post(
            self._client, url, _timeout(self.cfg, timeout_s), json=body,
            headers={"Authorization": f"Bearer {token}"},
        )  # fmt: skip
        if resp.status_code == 401:  # токен отозван раньше срока — один раз берём новый
            token = await self._access_token(stale=token)
            started = time.monotonic()
            resp = await _post(
                self._client, url, _timeout(self.cfg, timeout_s), json=body,
                headers={"Authorization": f"Bearer {token}"},
            )  # fmt: skip
        comp = _parse_completion(resp, int((time.monotonic() - started) * 1000))
        call = resp.json()["choices"][0]["message"].get("function_call")
        if not isinstance(call, dict):
            return comp  # функцию не вызвала — ответ текстом, его проверит схема
        args = call.get("arguments")
        try:
            value = json.loads(args) if isinstance(args, str) else args
        except ValueError:
            return dataclasses.replace(comp, text=str(args))
        value = fill_nullable(value, inline_refs(json_schema))
        return dataclasses.replace(comp, text=json.dumps(value, ensure_ascii=False))

    async def aclose(self) -> None:
        await self._client.aclose()
