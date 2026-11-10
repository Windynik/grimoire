import json

import httpx
import pytest

from backend.core.ollama_client import CallStats, ModelError, OllamaClient

SCHEMA = {"type": "object", "properties": {"a": {"type": "integer"}}}


def _reply(content, **stats):
    body = {"message": {"content": content}, "done": True}
    body.update(stats)
    return httpx.Response(200, json=body)


def _client(handler):
    return OllamaClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_chat_structured_sends_schema_and_returns_stats():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return _reply('<think>hmm</think>{"a": 1}', prompt_eval_count=100,
                      prompt_eval_duration=2_000_000_000, eval_count=50,
                      eval_duration=1_000_000_000)

    data, stats = await _client(handler).chat_structured(
        "hi", SCHEMA, system="sys", model="gpt-oss:20b", think="medium")
    assert data == {"a": 1}
    assert stats == CallStats(100, 2.0, 50, 1.0)
    body = seen[0]
    assert body["format"] == SCHEMA and body["stream"] is False
    assert body["think"] == "medium"
    assert body["messages"][0] == {"role": "system", "content": "sys"}
    assert body["options"]["num_ctx"] == 16384


@pytest.mark.asyncio
async def test_chat_structured_missing_stats_are_zero():
    data, stats = await _client(lambda r: _reply('{"a": 2}')).chat_structured(
        "hi", SCHEMA, model="m")
    assert stats == CallStats(0, 0.0, 0, 0.0)


@pytest.mark.asyncio
async def test_chat_structured_retries_once_then_raises():
    calls = []

    def handler(request):
        calls.append(1)
        return _reply("not json")

    with pytest.raises(ModelError):
        await _client(handler).chat_structured("hi", SCHEMA, model="m")
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_chat_structured_retry_recovers_from_http_error():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(500)
        return _reply('{"a": 3}')

    data, _ = await _client(handler).chat_structured("hi", SCHEMA, model="m")
    assert data == {"a": 3} and len(calls) == 2


@pytest.mark.asyncio
async def test_think_value_by_model():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content)["think"])
        return _reply('{"a": 1}')

    client = _client(handler)
    await client.chat_structured("p", SCHEMA, model="gpt-oss:20b", think="medium")
    await client.chat_structured("p", SCHEMA, model="qwen3.8", think="medium")
    await client.chat_structured("p", SCHEMA, model="qwen3.8", think="high")
    await client.chat_structured("p", SCHEMA, model="qwen3.8", think="low")
    # On/off models have no thinking budget, so only "high" turns thinking on
    assert seen == ["medium", False, True, False]


@pytest.mark.asyncio
async def test_stream_text_reports_stats():
    lines = [
        {"message": {"content": "Hel"}, "done": False},
        {"message": {"content": "lo"}, "done": False},
        {"message": {"content": ""}, "done": True, "prompt_eval_count": 7,
         "prompt_eval_duration": 1_000_000_000, "eval_count": 9,
         "eval_duration": 3_000_000_000},
    ]

    def handler(request):
        return httpx.Response(200, text="\n".join(json.dumps(x) for x in lines))

    got = []
    chunks = [c async for c in _client(handler).stream_text("p", model="m", on_stats=got.append)]
    assert "".join(chunks) == "Hello"
    assert got == [CallStats(7, 1.0, 9, 3.0)]


def test_pick_model_prefers_gpt_oss():
    pick = OllamaClient.pick_model
    assert pick(["llama3:8b", "gpt-oss:20b", "qwen3:8b"]) == "gpt-oss:20b"
    assert pick(["llama3:8b", "qwen3.8:30b"]) == "qwen3.8:30b"
    assert pick([]) is None


@pytest.mark.asyncio
async def test_chat_structured_rejects_non_object():
    calls = []

    def handler(request):
        calls.append(1)
        return _reply("[1, 2]")

    with pytest.raises(ModelError) as caught:
        await _client(handler).chat_structured("hi", SCHEMA, model="m")
    assert len(calls) == 2
    assert "reply starts '[1, 2]'" in str(caught.value)


LIST_SCHEMA = {"type": "object", "required": ["swaps"],
               "properties": {"swaps": {"type": "array", "maxItems": 8, "items": {}}}}


@pytest.mark.asyncio
async def test_chat_structured_wraps_bare_list_for_single_list_schema():
    # Small models sometimes send only the list that the schema puts in an object
    data, _ = await _client(lambda r: _reply('[{"out": "a"}]')).chat_structured(
        "hi", LIST_SCHEMA, model="m")
    assert data == {"swaps": [{"out": "a"}]}


@pytest.mark.asyncio
async def test_chat_structured_error_shows_short_reply_start():
    with pytest.raises(ModelError) as caught:
        await _client(lambda r: _reply("x" * 500)).chat_structured("hi", SCHEMA, model="m")
    assert "reply starts '%s'" % ("x" * 160) in str(caught.value)
    assert "x" * 161 not in str(caught.value)


@pytest.mark.asyncio
async def test_chat_structured_connect_error_and_missing_message():
    def refuse(request):
        raise httpx.ConnectError("down")

    with pytest.raises(ModelError):
        await _client(refuse).chat_structured("hi", SCHEMA, model="m")
    with pytest.raises(ModelError):
        await _client(lambda r: httpx.Response(200, json={"done": True})).chat_structured(
            "hi", SCHEMA, model="m")


@pytest.mark.asyncio
async def test_chat_structured_timeout_does_not_retry():
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ReadTimeout("slow")

    with pytest.raises(ModelError):
        await _client(handler).chat_structured("hi", SCHEMA, model="m")
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_chat_structured_num_predict_and_no_models():
    seen = []

    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": []})
        seen.append(json.loads(request.content))
        return _reply('{"a": 1}')

    client = _client(handler)
    with pytest.raises(ModelError):
        await client.chat_structured("hi", SCHEMA)
    await client.chat_structured("hi", SCHEMA, model="m", num_predict=8192)
    assert seen[0]["options"]["num_predict"] == 8192


@pytest.mark.asyncio
async def test_stream_text_options_and_errors():
    seen = []

    def ok(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, text=json.dumps({"message": {"content": "a"}, "done": True}))

    _ = [c async for c in _client(ok).stream_text("p", model="m", num_predict=16)]
    assert seen[0]["options"] == {"num_ctx": 16384, "num_predict": 16}

    with pytest.raises(ModelError):
        _ = [c async for c in _client(lambda r: httpx.Response(500)).stream_text("p", model="m")]
    err = httpx.Response(200, text=json.dumps({"error": "boom"}))
    with pytest.raises(ModelError):
        _ = [c async for c in _client(lambda r: err).stream_text("p", model="m")]


@pytest.mark.asyncio
async def test_status_tells_running_with_no_models_from_not_running():
    empty = _client(lambda request: httpx.Response(200, json={"models": []}))
    assert await empty.status() == {"available": False, "running": True, "models": [],
                                    "default_model": None}

    def down(request):
        raise httpx.ConnectError("refused")

    assert (await _client(down).status())["running"] is False
    one = _client(lambda request: httpx.Response(200, json={"models": [{"name": "qwen3.5:9b"}]}))
    assert await one.status() == {"available": True, "running": True, "models": ["qwen3.5:9b"],
                                  "default_model": "qwen3.5:9b"}
