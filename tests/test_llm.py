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
