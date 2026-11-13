"""Exercise the real HTTP/SSE client with offline byte streams, never a model service."""

import asyncio
import json

import httpx
import pytest

from cairnkit import (
    Agent,
    AgentSpec,
    FallbackModel,
    ModelAPIError,
    OpenAICompatModel,
    ScriptedModel,
    ToolContext,
    ToolRegistry,
)
from tests.conftest import say


def event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


TEXT = event({"choices": [{"index": 0, "delta": {"content": "你好"}}]})
STOP = event({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
DONE = "data: [DONE]\n\n"


class ByteStream(httpx.AsyncByteStream):
    def __init__(self, body: str, failure: Exception | None = None):
        self.body = body.encode()
        self.failure = failure
        self.closed = False

    async def __aiter__(self):
        # Split both UTF-8 characters and SSE fields across transport chunks.
        for start in range(0, len(self.body), 2):
            yield self.body[start : start + 2]
        if self.failure is not None:
            raise self.failure

    async def aclose(self):
        self.closed = True


def client(body: str, failure: Exception | None = None):
    stream = ByteStream(body, failure)
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)

    model = OpenAICompatModel(
        "test",
        base_url="https://model.invalid/v1",
        api_key="test",
        transport=httpx.MockTransport(handle),
    )
    return model, stream, requests


@pytest.mark.parametrize(
    "body",
    [
        "",
        event({"choices": [{"delta": {"role": "assistant"}}]}),
        TEXT,
        TEXT + DONE,
        TEXT + STOP,
        TEXT + STOP + "data: [DONE]",  # Unterminated SSE event, not a complete marker.
    ],
    ids=["empty", "role-only", "eof", "done-only", "finish-only", "partial-done-frame"],
)
async def test_incomplete_stream_raises_instead_of_returning_a_response(body):
    model, stream, requests = client(body)
    with pytest.raises(ModelAPIError) as error:
        await model.complete([], on_delta=lambda _: None)
    assert error.value.status_code == 502
    assert stream.closed and len(requests) == 1


@pytest.mark.parametrize(
    "payload",
    [
        "{broken json",
        "null",
        "[]",
        '{"choices": {}}',
        '{"choices": [null]}',
        '{"choices": [{"delta": "not an object"}]}',
        '{"choices": [{"delta": {"content": 42}}]}',
        '{"choices": [{"finish_reason": true}]}',
        '{"choices": [{"finish_reason": ""}]}',
        '{"choices": [{"finish_reason": "  "}]}',
        '{"choices": [{"finish_reason": "error"}]}',
    ],
)
async def test_malformed_event_is_not_silently_skipped_before_valid_ending(payload):
    model, stream, _ = client(TEXT + f"data: {payload}\n\n" + STOP + DONE)
    seen = []
    with pytest.raises(ModelAPIError) as error:
        await model.complete([], on_delta=seen.append)
    assert error.value.status_code == 502
    assert seen == ["你好"] and stream.closed


@pytest.mark.parametrize("finish_reason", ["stop", "length", "tool_calls", "content_filter"])
@pytest.mark.parametrize("repeated_finish", [False, True])
async def test_valid_endings_keep_final_usage_and_provider_finish_reason(
    finish_reason, repeated_finish
):
    terminal = event({"choices": [{"delta": {}, "finish_reason": finish_reason}]})
    usage = {
        "prompt_tokens": 12,
        "completion_tokens": 2,
        "prompt_tokens_details": {"cached_tokens": 5},
    }
    # OpenAI uses empty choices; OpenRouter repeats the terminal reason with no new output.
    choices = (
        [{"delta": {"content": "", "role": "assistant"}, "finish_reason": finish_reason}]
        if repeated_finish
        else []
    )
    model, stream, requests = client(
        TEXT + terminal + event({"choices": choices, "usage": usage}) + DONE
    )
    seen = []
    result = await model.complete([], on_delta=seen.append)
    assert result.content == "你好" and seen == ["你好"]
    assert result.finish_reason == finish_reason
    assert (
        result.usage.prompt_tokens,
        result.usage.completion_tokens,
        result.usage.cached_tokens,
    ) == (12, 2, 5)
    assert stream.closed and len(requests) == 1


async def test_multiline_data_comments_and_final_content_share_a_valid_terminal_event():
    body = (
        ": keep alive\r\nid: 7\r\nevent: message\r\n"
        'data: {"choices": [\r\n'
        'data: {"delta": {"content": "你好"}, "finish_reason": "stop"}]}\r\n\r\n' + DONE
    )
    model, stream, _ = client(body)
    seen = []
    result = await model.complete([], on_delta=seen.append)
    assert result.content == "你好" and seen == ["你好"] and stream.closed


@pytest.mark.parametrize(
    "tail",
    [TEXT, event({"choices": [{"delta": {}, "finish_reason": "length"}]})],
    ids=["output-after-finish", "conflicting-finish"],
)
async def test_terminal_event_cannot_be_followed_by_more_output_or_a_different_reason(tail):
    model, stream, _ = client(TEXT + STOP + tail + DONE)
    seen = []
    with pytest.raises(ModelAPIError):
        await model.complete([], on_delta=seen.append)
    assert seen == ["你好"] and stream.closed


@pytest.mark.parametrize("error", [{"code": 503, "message": "overloaded"}, "overloaded"])
async def test_provider_error_after_content_is_not_overridden_by_finish(error):
    model, stream, _ = client(TEXT + event({"error": error}) + STOP + DONE)
    with pytest.raises(ModelAPIError, match="overloaded"):
        await model.complete([], on_delta=lambda _: None)
    assert stream.closed


async def test_another_choice_finishing_cannot_hide_the_selected_choices_truncation():
    other = event(
        {"choices": [{"index": 1, "delta": {"content": "other"}, "finish_reason": "stop"}]}
    )
    model, stream, _ = client(TEXT + other + DONE)
    seen = []
    with pytest.raises(ModelAPIError):
        await model.complete([], on_delta=seen.append)
    assert seen == ["你好"] and stream.closed


async def test_truncation_after_output_never_retries_or_uses_fallback():
    model, stream, requests = client(TEXT)
    backup = ScriptedModel([say("replacement")], name="backup")
    chain = FallbackModel([model, backup], retries=2, backoff_seconds=0)
    seen = []
    with pytest.raises(ModelAPIError):
        await chain.complete([], on_delta=seen.append)
    assert seen == ["你好"] and len(requests) == 1 and backup.requests == []
    assert stream.closed


async def test_agent_never_executes_a_tool_from_an_unfinished_stream():
    tools = ToolRegistry()
    executed = []

    @tools.tool(name="save", description="Record a value.")
    def save(args, ctx):
        executed.append(args)
        return {"ok": True}

    call = {"index": 0, "id": "c1", "function": {"name": "save", "arguments": "{}"}}
    model, stream, requests = client(event({"choices": [{"delta": {"tool_calls": [call]}}]}) + DONE)
    agent = Agent(
        AgentSpec(name="test", description="", persona="", tools=["save"]), model=model, tools=tools
    )
    with pytest.raises(ModelAPIError):
        await agent.run("save", ToolContext(), stream=True)
    assert executed == [] and len(requests) == 1 and stream.closed


async def test_transport_failure_is_preserved_and_response_is_closed():
    failure = httpx.ReadError("connection lost")
    model, stream, _ = client(TEXT, failure)
    with pytest.raises(httpx.ReadError) as error:
        await model.complete([], on_delta=lambda _: None)
    assert error.value is failure and stream.closed


async def test_callback_cancellation_is_preserved_and_response_is_closed():
    model, stream, _ = client(TEXT + STOP + DONE)

    async def cancel(_):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await model.complete([], on_delta=cancel)
    assert stream.closed
