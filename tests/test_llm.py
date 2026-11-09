import json

import httpx
import pytest

from cairnkit import (
    FailoverReason,
    FallbackModel,
    ModelAPIError,
    ScriptedModel,
    classify_error,
    openrouter,
)
from cairnkit.llm.fallback import AllModelsFailed
from tests.conftest import say


def transport(status: int, payload: dict, seen: list | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(json.loads(request.content))
        return httpx.Response(status, json=payload)

    return httpx.MockTransport(handler)


async def test_openrouter_parses_tool_calls_and_usage_and_denies_data_collection():
    seen: list = []
    payload = {
        "model": "deepseek/deepseek-v4-flash",
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "x1",
                            "type": "function",
                            "function": {"name": "f", "arguments": '{"a":1}'},
                        }
                    ],
                },
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 3,
            "cost": 0.0001,
            "prompt_tokens_details": {"cached_tokens": 4},
        },
    }
    model = openrouter(
        "deepseek/deepseek-v4-flash", api_key="k", transport=transport(200, payload, seen)
    )
    response = await model.complete(
        [{"role": "user", "content": "hi"}], tools=[{"type": "function"}]
    )
    assert response.tool_calls[0].name == "f" and response.tool_calls[0].arguments == '{"a":1}'
    assert (response.usage.prompt_tokens, response.usage.cached_tokens, response.usage.cost) == (
        10,
        4,
        0.0001,
    )
    assert seen[0]["provider"]["data_collection"] == "deny"
    assert seen[0]["tools"] == [{"type": "function"}]


async def test_http_errors_raise_model_api_error():
    model = openrouter(
        "m", api_key="k", transport=transport(401, {"error": {"message": "bad key"}})
    )
    with pytest.raises(ModelAPIError) as info:
        await model.complete([{"role": "user", "content": "hi"}])
    assert info.value.status_code == 401
    assert classify_error(info.value).reason is FailoverReason.auth


@pytest.mark.parametrize(
    ("status", "body", "reason", "fallback"),
    [
        (429, {"error": {"message": "Rate limit"}}, FailoverReason.rate_limit, True),
        (
            429,
            {"error": {"message": "x", "metadata": {"provider_name": "DeepInfra"}}},
            FailoverReason.upstream_rate_limit,
            True,
        ),
        (
            404,
            {"error": {"message": "No endpoints found matching your data policy"}},
            FailoverReason.provider_policy_blocked,
            True,
        ),
        (404, {"error": {"message": "model not found"}}, FailoverReason.model_not_found, True),
        (
            400,
            {"error": {"message": "maximum context length is 64000"}},
            FailoverReason.context_overflow,
            False,
        ),
        (402, {"error": {"message": "Insufficient credits"}}, FailoverReason.billing, True),
        (503, {"error": {"message": "overloaded"}}, FailoverReason.overloaded, True),
    ],
)
def test_classification(status, body, reason, fallback):
    verdict = classify_error(ModelAPIError(status, body["error"]["message"], body))
    assert verdict.reason is reason
    assert verdict.should_fallback is fallback


class Failing:
    def __init__(self, name, error):
        self.name, self.error, self.calls = name, error, 0

    async def complete(self, messages, **kwargs):
        self.calls += 1
        raise self.error


async def _no_sleep(_):
    return None


async def test_fallback_moves_on_and_retries_transient():
    flaky = Failing("a", ModelAPIError(503, "overloaded"))
    good = ScriptedModel([say("ok")], name="b")
    chain = FallbackModel([flaky, good], retries=2, sleep=_no_sleep)
    assert (await chain.complete([])).content == "ok"
    assert flaky.calls == 3  # first try + 2 retries, then fall back


async def test_fallback_does_not_mask_auth_errors():
    chain = FallbackModel(
        [Failing("a", ModelAPIError(401, "bad key")), ScriptedModel([say("x")])], sleep=_no_sleep
    )
    with pytest.raises(ModelAPIError):
        await chain.complete([])


async def test_rate_limited_model_cools_down():
    limited = Failing("a", ModelAPIError(429, "Rate limit"))
    good = ScriptedModel([say("1"), say("2")], name="b")
    now = [0.0]
    chain = FallbackModel(
        [limited, good], sleep=_no_sleep, clock=lambda: now[0], cooldown_seconds=60
    )
    await chain.complete([])
    await chain.complete([])
    assert limited.calls == 1  # skipped on the second call while cooling down


async def test_all_failed():
    chain = FallbackModel([Failing("a", ModelAPIError(404, "nope"))], sleep=_no_sleep)
    with pytest.raises(AllModelsFailed):
        await chain.complete([])


# --- Hermes v0.23.0 ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "request body too large, must be less than 20MB",  # Novita
        "Request size exceeds the limit of 33554432",  # Z.AI
        "Payload too large",
        "Content-Length of the request exceeds 33554432 bytes",
    ],
)
def test_byte_size_400s_mean_compress(message):
    body = {"error": {"message": message, "type": "invalid_request_error"}}
    verdict = classify_error(ModelAPIError(400, message, body))
    assert verdict.reason is FailoverReason.payload_too_large and verdict.should_compress


@pytest.mark.parametrize(
    "message",
    [
        "Request body too large for gpt-4.1 model. Max size: 8000 tokens.",  # a token cap
        "tools[0].description content length exceeds maximum allowed",  # a field
        "request size parameter page_size exceeds the maximum of 100",  # a parameter
        "response size too large",
    ],
)
def test_other_size_complaints_stay_format_errors(message):
    body = {"error": {"message": message, "type": "invalid_request_error"}}
    assert classify_error(ModelAPIError(400, message, body)).reason is FailoverReason.format_error


def test_timeouts_say_which_phase_failed():
    connect = classify_error(httpx.ConnectTimeout("timed out"))
    assert connect.reason is FailoverReason.timeout and connect.retryable
    assert connect.context == {"timeout_phase": "connect"}
    assert "before it was established" in connect.message and "base_url" in connect.message
    read = classify_error(httpx.ReadTimeout("timed out"))
    assert read.context == {"timeout_phase": "read"}
    assert "waiting for the provider to respond" in read.message and "timeout=" in read.message
    pool = classify_error(httpx.PoolTimeout("no free connection"))
    assert pool.reason is FailoverReason.timeout and pool.context == {}
    assert pool.message == "no free connection"


async def test_all_failed_names_the_timeout_phase():
    chain = FallbackModel(
        [Failing("a", httpx.ConnectTimeout("timed out"))], retries=0, sleep=_no_sleep
    )
    with pytest.raises(AllModelsFailed, match="a: timeout .Connection to the provider timed out"):
        await chain.complete([])


def sse(chunks: list[dict]) -> httpx.MockTransport:
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    return httpx.MockTransport(
        lambda request: httpx.Response(
            200, text=body, headers={"content-type": "text/event-stream"}
        )
    )


def tool_delta(index=0, id=None, name=None, arguments=None) -> dict:
    function = {k: v for k, v in (("name", name), ("arguments", arguments)) if v is not None}
    delta = {"index": index, "function": function, **({"id": id} if id else {})}
    return {"choices": [{"delta": {"tool_calls": [delta]}}]}


async def streamed_calls(*chunks: dict) -> list[tuple[str, str, str]]:
    model = openrouter("m", api_key="k", transport=sse(list(chunks)))
    response = await model.complete([{"role": "user", "content": "hi"}], on_delta=lambda _: None)
    return [(c.id, c.name, c.arguments) for c in response.tool_calls]


async def test_parallel_calls_sharing_index_zero_are_split():
    # Ollama reuses index 0 for every call of a parallel batch, told apart only by id.
    assert await streamed_calls(
        tool_delta(id="a", name="search", arguments='{"q": "x"}'),
        tool_delta(id="b", name="lookup", arguments='{"id": 1}'),
    ) == [("a", "search", '{"q": "x"}'), ("b", "lookup", '{"id": 1}')]


async def test_two_parallel_calls_of_one_tool_are_split_once_arguments_close():
    assert await streamed_calls(
        tool_delta(id="a", name="search", arguments='{"q": "x"}'),
        tool_delta(id="b", name="search", arguments='{"q": "y"}'),
    ) == [("a", "search", '{"q": "x"}'), ("b", "search", '{"q": "y"}')]


async def test_fresh_id_on_every_fragment_does_not_split_a_call():
    # LM Studio and Kimi: a new id on each argument fragment, no name.
    assert await streamed_calls(
        tool_delta(id="a", name="search", arguments='{"q": '),
        tool_delta(id="b", arguments='"x", "n": '),
        tool_delta(id="c", arguments="2}"),
    ) == [("c", "search", '{"q": "x", "n": 2}')]


async def test_name_resent_on_every_fragment_does_not_split_a_call():
    # Some MiniMax routes resend the same name (and a fresh id) with each fragment.
    assert await streamed_calls(
        tool_delta(id="a", name="search", arguments='{"q": "a}b'),
        tool_delta(id="b", name="search", arguments='", "n": [1, '),
        tool_delta(id="c", name="search", arguments="2]}"),
    ) == [("c", "search", '{"q": "a}b", "n": [1, 2]}')]
