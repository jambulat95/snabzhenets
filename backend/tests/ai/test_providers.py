import json
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from app.agents.ml.gateway import (
    GigaChatProvider,
    OpenAICompatibleProvider,
    ProviderConfig,
    ProviderError,
    make_provider,
    providers_from_env,
)
from app.agents.ml.gateway.providers import GIGACHAT_OAUTH_URL, inline_refs

pytestmark = pytest.mark.anyio

CHAT_URL = "https://giga/api/v1/chat/completions"


class Line(BaseModel):
    name: str
    quantity: float


class Parsed(BaseModel):
    lines: list[Line]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def chat_reply() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": '{"lines": []}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 5, "total_tokens": 55},
        },
    )


class Giga:
    """Подставной GigaChat: OAuth и чат на одном транспорте."""

    def __init__(self, *chat: httpx.Response) -> None:
        self.chat = list(chat)
        self.oauth: list[httpx.Request] = []
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if str(request.url) == GIGACHAT_OAUTH_URL:
            self.oauth.append(request)
            n = len(self.oauth)
            return httpx.Response(200, json={"access_token": f"tok{n}", "expires_at": 4e12})
        self.calls.append(request)
        return self.chat.pop(0)


def giga(server: Giga) -> GigaChatProvider:
    cfg = ProviderConfig(
        name="gigachat", base_url="https://giga/api/v1", api_key="QXV0aEtleQ==",
        model="GigaChat-2-Max", oauth_scope="GIGACHAT_API_PERS",
    )  # fmt: skip
    return GigaChatProvider(cfg, httpx.AsyncClient(transport=httpx.MockTransport(server)))


async def complete(p: GigaChatProvider) -> None:
    await p.complete(
        [{"role": "user", "content": "x"}], Parsed.model_json_schema(),
        temperature=0.2, max_tokens=100, seed=0,
    )  # fmt: skip


async def test_gigachat_gets_token_once_and_sends_schema_as_function() -> None:
    srv = Giga(chat_reply(), chat_reply())
    p = giga(srv)

    await complete(p)
    await complete(p)

    [oauth] = srv.oauth  # токен на 30 минут переиспользуется
    assert oauth.headers["Authorization"] == "Basic QXV0aEtleQ=="
    assert oauth.headers["RqUID"] and oauth.content == b"scope=GIGACHAT_API_PERS"
    assert srv.calls[0].headers["Authorization"] == "Bearer tok1"
    body = json.loads(srv.calls[0].content)
    # response_format с JSON-схемой GigaChat не соблюдает — схема уходит параметрами функции
    assert "response_format" not in body and body["function_call"] == {"name": "answer"}
    [fn] = body["functions"]
    params = fn["parameters"]
    assert "$ref" not in json.dumps(params) and "title" not in json.dumps(params)
    assert params["properties"]["lines"]["items"]["required"] == ["name", "quantity"]
    assert "seed" not in body


class Item(BaseModel):
    name: str
    article: str | None


class Items(BaseModel):
    items: list[Item]


async def test_gigachat_function_arguments_are_the_answer() -> None:
    # Аргументы вызова функции — ответ; пропущенное поле «или null» — null, а не ошибка схемы
    reply = httpx.Response(200, json={
        "choices": [{"message": {"content": "", "function_call": {
            "name": "answer", "arguments": {"items": [{"name": "Подшипник 6205"}]}}},
            "finish_reason": "function_call"}],
        "usage": {"prompt_tokens": 40, "completion_tokens": 9},
    })  # fmt: skip
    p = giga(Giga(reply))
    comp = await p.complete(
        [{"role": "user", "content": "x"}], Items.model_json_schema(),
        temperature=0.2, max_tokens=100, seed=None,
    )  # fmt: skip
    assert Items.model_validate_json(comp.text).items[0].article is None
    assert (comp.prompt_tokens, comp.completion_tokens) == (40, 9)


async def test_gigachat_nullable_field_is_plain_type_in_function(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    srv = Giga(chat_reply())
    p = giga(srv)
    await p.complete(
        [{"role": "user", "content": "x"}], Items.model_json_schema(),
        temperature=0.2, max_tokens=100, seed=None,
    )  # fmt: skip
    params = json.loads(srv.calls[0].content)["functions"][0]["parameters"]
    assert params["properties"]["items"]["items"]["properties"]["article"] == {"type": "string"}
    # Прежний способ — настройкой
    monkeypatch.setenv("GIGACHAT_STRUCTURED", "response_format")
    srv2 = Giga(chat_reply())
    await complete(giga(srv2))
    assert json.loads(srv2.calls[0].content)["response_format"]["type"] == "json_schema"


async def test_gigachat_refreshes_revoked_token_once() -> None:
    srv = Giga(httpx.Response(401, text="token expired"), chat_reply())
    p = giga(srv)

    await complete(p)

    assert len(srv.oauth) == 2
    assert srv.calls[1].headers["Authorization"] == "Bearer tok2"


async def test_gigachat_oauth_failure_is_provider_error() -> None:
    def deny(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="bad key")

    cfg = ProviderConfig(
        name="gigachat", base_url="https://giga/api/v1", api_key="k", model="GigaChat-2",
        oauth_scope="GIGACHAT_API_PERS",
    )  # fmt: skip
    p = GigaChatProvider(cfg, httpx.AsyncClient(transport=httpx.MockTransport(deny)))
    with pytest.raises(ProviderError, match="OAuth HTTP 401"):
        await complete(p)


def test_inline_refs_keeps_field_description() -> None:
    schema: dict[str, Any] = {
        "$defs": {"Line": {"type": "object", "properties": {"name": {"type": "string"}}}},
        "type": "object",
        "properties": {"line": {"$ref": "#/$defs/Line", "description": "строка"}},
    }
    line = inline_refs(schema)["properties"]["line"]
    assert line == {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "description": "строка",
    }


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for var in [
        "LLM_PROVIDERS", "RESERVE_BASE_URL", "YANDEX_API_KEY", "YANDEX_MODEL",
        "YANDEX_RUB_PER_1K_IN", "YANDEX_RUB_PER_1K_OUT", "GIGACHAT_AUTH_KEY", "GIGACHAT_API_KEY",
        "GIGACHAT_MODEL", "LLM_BASE_URL", "LOCAL_LLM_BASE_URL", "LLM_MODEL", "LOCAL_LLM_MODEL",
        "GIGACHAT_RUB_PER_1K_IN", "GIGACHAT_RUB_PER_1K_OUT", "GIGACHAT_CA_BUNDLE",
        "GIGACHAT_SCOPE", "GIGACHAT_MAX_CONCURRENCY",
    ]:  # fmt: skip
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def test_switch_to_cloud_is_one_env_line(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("YANDEX_API_KEY", "ya")
    clean_env.setenv("YANDEX_FOLDER_ID", "b1gfolder")
    clean_env.setenv("GIGACHAT_AUTH_KEY", "giga")
    clean_env.setenv("LLM_PROVIDERS", "yandexgpt, gigachat")

    ya, gc = providers_from_env()

    assert (ya.name, ya.model) == ("yandexgpt", "gpt://b1gfolder/yandexgpt-5.1")
    assert ya.headers == (("OpenAI-Project", "b1gfolder"),)
    assert (ya.rub_per_1k_input, ya.rub_per_1k_output) == (0.8, 0.8)
    assert (gc.model, gc.rub_per_1k_input, gc.oauth_scope) == (
        "GigaChat-2-Max", 0.65, "GIGACHAT_API_PERS"
    )  # fmt: skip
    assert isinstance(make_provider(ya), OpenAICompatibleProvider)
    assert isinstance(make_provider(gc), GigaChatProvider)


def test_gigachat_trusts_russian_root_ca(clean_env: pytest.MonkeyPatch) -> None:
    import ssl

    clean_env.setenv("GIGACHAT_AUTH_KEY", "giga")
    clean_env.setenv("LLM_PROVIDERS", "gigachat")
    [gc] = providers_from_env()
    # Сертификат НУЦ Минцифры — в образе: без него TLS к GigaChat — CERTIFICATE_VERIFY_FAILED
    assert gc.ca_bundle and gc.ca_bundle.endswith("russian_trusted_root_ca.pem")
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(cafile=gc.ca_bundle)
    names = [dict(x[0] for x in c["subject"]).get("commonName") for c in ctx.get_ca_certs()]
    assert "Russian Trusted Root CA" in names
    clean_env.setenv("GIGACHAT_CA_BUNDLE", "/certs/other.pem")
    assert providers_from_env()[0].ca_bundle == "/certs/other.pem"


def test_gigachat_personal_key_is_one_stream(clean_env: pytest.MonkeyPatch) -> None:
    # Ключ физлица держит один поток: параллельные части разбора иначе получают HTTP 429 (US-23)
    clean_env.setenv("GIGACHAT_AUTH_KEY", "giga")
    clean_env.setenv("LLM_PROVIDERS", "gigachat")
    assert providers_from_env()[0].max_concurrency == 1
    clean_env.setenv("GIGACHAT_SCOPE", "GIGACHAT_API_CORP")
    assert providers_from_env()[0].max_concurrency is None
    clean_env.setenv("GIGACHAT_MAX_CONCURRENCY", "3")
    assert providers_from_env()[0].max_concurrency == 3


def test_default_order_skips_clouds_without_keys(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("GIGACHAT_AUTH_KEY", "giga")
    assert [c.name for c in providers_from_env()] == ["qwen-local", "gigachat"]


def test_listed_provider_without_key_fails(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("LLM_PROVIDERS", "gigachat")
    with pytest.raises(ValueError, match="ключ не задан"):
        providers_from_env()


def test_cloud_model_without_price_fails(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("GIGACHAT_AUTH_KEY", "giga")
    clean_env.setenv("GIGACHAT_MODEL", "GigaChat-3-Ultra")
    with pytest.raises(ValueError, match="нет цены"):
        providers_from_env()
    clean_env.setenv("GIGACHAT_RUB_PER_1K_IN", "1.5")
    clean_env.setenv("GIGACHAT_RUB_PER_1K_OUT", "1.5")
    assert providers_from_env()[-1].rub_per_1k_output == 1.5


def test_core_env_names_work(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("GIGACHAT_API_KEY", "giga")
    clean_env.setenv("LOCAL_LLM_BASE_URL", "http://gpu:8080/v1")
    clean_env.setenv("LOCAL_LLM_MODEL", "qwen3-14b-q8")
    clean_env.setenv("LLM_PROVIDERS", "local,gigachat")
    local, gc = providers_from_env()
    assert (local.name, local.base_url, local.model) == (
        "qwen-local", "http://gpu:8080/v1", "qwen3-14b-q8"
    )  # fmt: skip
    assert gc.api_key == "giga"


def test_cloud_reserve_gets_longer_connect_timeout() -> None:
    from app.agents.ml.gateway.providers import (
        CLOUD_CONNECT_TIMEOUT_S,
        CONNECT_TIMEOUT_S,
        _timeout,
    )

    local = ProviderConfig(
        name="qwen-local", base_url="http://x/v1", api_key=None, model="q", local=True
    )
    cloud = ProviderConfig(name="yandexgpt", base_url="https://x/v1", api_key="k", model="y")
    assert _timeout(local, 60).connect == CONNECT_TIMEOUT_S
    assert _timeout(cloud, 60).connect == CLOUD_CONNECT_TIMEOUT_S
    assert _timeout(cloud, 2).connect == 2  # не дольше срока задачи
