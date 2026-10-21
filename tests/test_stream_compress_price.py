import json

import httpx
import pytest

from cairnkit import (
    SUMMARY_PREFIX,
    Agent,
    AgentSpec,
    ContextCompressor,
    FallbackModel,
    ModelAPIError,
    Price,
    ScriptedModel,
    ToolContext,
    Usage,
    cost_of,
    estimate_tokens,
    openrouter,
)
from tests.conftest import say


def sse(chunks: list[dict]) -> httpx.MockTransport:
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"

    def handler(request):
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(
            200,
            text=": OPENROUTER PROCESSING\n\n" + body,
            headers={"content-type": "text/event-stream"},
        )

    return httpx.MockTransport(handler)


async def test_openrouter_streams_text_and_assembles_tool_calls():
    chunks = [
        {"model": "m", "choices": [{"delta": {"content": "Hel"}}]},
        {"choices": [{"delta": {"content": "lo"}}]},
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "t1",
                                "function": {"name": "f", "arguments": '{"a":'},
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {"tool_calls": [{"index": 0, "function": {"arguments": "1}"}}]},
                    "finish_reason": "tool_calls",
                }
            ]
        },
        {"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 2, "cost": 0.001}},
    ]
    seen = []
    model = openrouter("m", api_key="k", transport=sse(chunks))
    response = await model.complete([{"role": "user", "content": "hi"}], on_delta=seen.append)
    assert seen == ["Hel", "lo"] and response.content == "Hello"
    assert response.tool_calls[0].arguments == '{"a":1}'
    assert response.usage.cost == 0.001


async def test_agent_stream_emits_text_deltas():
    events = []
    spec = AgentSpec(name="a", description="", persona="p")
    await Agent(spec, model=ScriptedModel([say("Good morning Avery")])).run(
        "hi",
        ToolContext(),
        stream=True,
        on_event=lambda e: events.append(e.data["text"]) if e.kind == "text_delta" else None,
    )
    assert "".join(events) == "Good morning Avery"


class StreamsThenFails:
    name = "a"

    async def complete(self, messages, on_delta=None, **kwargs):
        await on_delta("partial ")
        raise ModelAPIError(503, "overloaded")


async def test_fallback_never_restarts_after_text_was_streamed():
    chain = FallbackModel([StreamsThenFails(), ScriptedModel([say("other")])], retries=0)
    with pytest.raises(ModelAPIError):
        await chain.complete([], on_delta=lambda t: None)


def _conversation(turns: int) -> list[dict]:
    messages = [{"role": "system", "content": "SYS"}]
    for i in range(turns):
        messages += [
            {"role": "user", "content": f"question {i} " + "x" * 100},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"t{i}",
                        "type": "function",
                        "function": {"name": "f", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": f"t{i}", "content": f"result {i} " + "y" * 2000},
            {"role": "assistant", "content": f"answer {i} " + "a" * 1200},
        ]
    return messages


async def test_compression_prunes_then_summarises_and_keeps_structure():
    messages = _conversation(8)
    summary_model = ScriptedModel(
        [say("## Goal\nHelp with members.\n\n## Key Facts\n- question 0")]
    )
    compressor = ContextCompressor(
        context_window=2000, threshold=0.5, protect_last_turns=2, summary_model=summary_model
    )
    result = await compressor.compress(messages)
    out = result.messages
    assert out[0] == {"role": "system", "content": "SYS"}  # system prompt untouched
    assert result.pruned_tool_results > 0 and result.summary.startswith("## Goal")
    assert out[1]["role"] == "user" and out[1]["content"].startswith(SUMMARY_PREFIX)
    assert "question 6" in out[1]["content"]  # first protected turn keeps its own text
    roles = [m["role"] for m in out]
    assert all(not (a == b == "user") for a, b in zip(roles, roles[1:], strict=False))
    ids = {m.get("tool_call_id") for m in out if m["role"] == "tool"}
    calls = {c["id"] for m in out for c in m.get("tool_calls") or []}
    assert ids == calls  # no tool result without its call
    assert estimate_tokens(out) < estimate_tokens(messages)


async def test_compression_falls_back_without_a_summary_model():
    compressor = ContextCompressor(context_window=2000, threshold=0.5)
    result = await compressor.compress(_conversation(8))
    assert result.used_fallback and "summary model was unavailable" in result.summary


async def test_agent_compresses_before_calling_the_model():
    model = ScriptedModel([say("ok")])
    spec = AgentSpec(name="a", description="", persona="p")
    agent = Agent(spec, model=model, compressor=ContextCompressor(context_window=2000))
    result = await agent.run("new question", ToolContext(), history=_conversation(8)[1:])
    assert result.compressed
    assert estimate_tokens(model.requests[0]["messages"]) < estimate_tokens(_conversation(8))


def test_pricing():
    usage = Usage(prompt_tokens=1_000_000, completion_tokens=500_000, cached_tokens=500_000)
    prices = {"m": Price(0.14, 0.28, cached_input_per_million=0.014)}
    assert cost_of(usage, prices, "m") == pytest.approx(0.07 + 0.007 + 0.14)
    assert cost_of(Usage(cost=0.5), prices, "m") == 0.5
    assert cost_of(usage, prices, "unknown") is None
