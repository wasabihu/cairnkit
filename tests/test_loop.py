import json

import pytest

from cairnkit import (
    Agent,
    AgentSpec,
    GuardrailConfig,
    ScriptedModel,
    ToolContext,
    ToolError,
    ToolRegistry,
)
from cairnkit.guardrails import GuardrailController
from tests.conftest import call, say


def spec(**overrides) -> AgentSpec:
    values = dict(name="t", description="", persona="You help.", tools=["echo"], max_iterations=4)
    values.update(overrides)
    return AgentSpec(**values)


def registry(events: list | None = None) -> ToolRegistry:
    tools = ToolRegistry()

    @tools.tool(
        name="echo",
        description="Echo text.",
        parameters={"type": "object", "properties": {"text": {"type": "string"}}},
    )
    def echo(args, ctx):
        if events is not None:
            events.append(("handler", args["text"]))
        if args["text"] == "boom":
            raise ToolError("cannot echo boom")
        return {"echo": args["text"], "user": ctx.principal.get("id")}

    @tools.tool(name="admin_only", description="Admin.", roles={"admin"})
    def admin_only(args, ctx):
        return {"ok": True}

    return tools


async def test_tool_round_then_answer():
    model = ScriptedModel([call("echo", {"text": "hi"}), say("done")])
    result = await Agent(spec(), model=model, tools=registry()).run(
        "go", ToolContext(principal={"id": "u1"})
    )
    assert result.text == "done"
    assert result.stop_reason == "completed"
    tool_message = result.messages[-2]
    assert tool_message["role"] == "tool"
    assert json.loads(tool_message["content"]) == {"success": True, "echo": "hi", "user": "u1"}
    assert result.usage.calls == 2


async def test_identity_comes_from_context_not_model():
    model = ScriptedModel([call("echo", {"text": "hi", "user": "attacker"}), say("ok")])
    result = await Agent(spec(), model=model, tools=registry()).run(
        "go", ToolContext(principal={"id": "real"})
    )
    assert json.loads(result.tool_records[0].result)["user"] == "real"


async def test_unknown_tool_and_bad_json_become_tool_errors():
    model = ScriptedModel([call("nope", {}), call("echo", "{not json", "c2"), say("sorry")])
    result = await Agent(spec(), model=model, tools=registry()).run("go", ToolContext())
    errors = [r.result for r in result.tool_records]
    assert "unknown tool 'nope'" in errors[0]
    assert "JSON object" in errors[1]
    # No synthetic user messages were injected.
    assert [m["role"] for m in result.messages].count("user") == 1


async def test_role_restricted_tools_are_not_offered():
    model = ScriptedModel([say("hello")])
    agent = Agent(spec(tools=["echo", "admin_only"]), model=model, tools=registry())
    await agent.run("go", ToolContext(roles=frozenset({"staff"})))
    offered = [t["function"]["name"] for t in model.requests[0]["tools"]]
    assert offered == ["echo"]


async def test_tool_call_event_fires_before_handler():
    events: list = []
    model = ScriptedModel([call("echo", {"text": "x"}), say("ok")])
    await Agent(spec(), model=model, tools=registry(events)).run(
        "go", ToolContext(), on_event=lambda e: events.append((e.kind, e.data["tool"]))
    )
    assert events[:3] == [("tool_call", "echo"), ("handler", "x"), ("tool_result", "echo")]


async def test_max_iterations_forces_a_final_answer_without_tools():
    model = ScriptedModel(
        [call("echo", {"text": str(i)}, f"c{i}") for i in range(2)] + [say("final")]
    )
    result = await Agent(spec(max_iterations=2), model=model, tools=registry()).run(
        "go", ToolContext()
    )
    assert result.stop_reason == "max_iterations"
    assert result.text == "final"
    assert model.requests[-1]["tools"] is None


async def test_guardrail_blocks_repeated_identical_failures():
    failing = [call("echo", {"text": "boom"}, f"c{i}") for i in range(4)]
    model = ScriptedModel([*failing, say("giving up")])
    agent = Agent(
        spec(max_iterations=10, guardrails=GuardrailConfig(exact_failure_block_after=3)),
        model=model,
        tools=registry(),
    )
    result = await agent.run("go", ToolContext())
    assert result.stop_reason == "guardrail"
    assert "Blocked echo" in result.tool_records[-1].result
    assert result.text == "giving up"


async def test_system_prompt_is_reused_verbatim():
    model = ScriptedModel([say("a"), say("b")])
    agent = Agent(spec(), model=model, tools=registry())
    first = await agent.run("one", ToolContext(), volatile=["Time: 9:00"])
    await agent.run(
        "two",
        ToolContext(),
        system_prompt=first.system_prompt,
        history=first.messages[1:],
        volatile=["Time: 10:00"],
    )
    assert model.requests[1]["messages"][0]["content"] == first.system_prompt
    assert "9:00" in first.system_prompt


async def test_missing_tool_is_a_configuration_error():
    try:
        Agent(spec(tools=["ghost"]), model=ScriptedModel([say("x")]), tools=registry())
    except ValueError as exc:
        assert "ghost" in str(exc)
    else:
        raise AssertionError("expected ValueError")


# --- Hermes v0.23.0 ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("returned", "failed"),
    [
        ('{"success": false, "error": "x"}', True),
        ('{"error": "record not found"}', True),
        ('{"status": "failed", "detail": "upstream refused"}', True),
        ('{"results": [{"error": "denied"}, {"error": "denied"}]}', True),
        ('{"results": [{"error": "denied"}, {"id": 2}]}', False),  # partial: not a failure
        ('{"items": [{"id": 1, "error": null}], "failed": 0}', False),
        ('{"error": null, "rows": 3}', False),
        ('{"message": "3 rows updated"}', False),
        ('{"note": "the word \\"error\\" inside content"}', False),
        ("plain text", False),
    ],
)
async def test_tool_failure_is_judged_by_top_level_shape(returned, failed):
    tools = ToolRegistry()

    @tools.tool(name="raw", description="Returns a fixed string.")
    def raw(args, ctx):
        return returned

    outcome = await tools.dispatch(tools.get("raw"), {}, ToolContext())
    assert outcome.failed is failed


def test_throttled_retries_do_not_count_as_identical_failures():
    guard = GuardrailController(GuardrailConfig())
    throttled = '{"success": false, "error": "Rate limit exceeded", "retry_after": 2}'
    for _ in range(4):
        assert guard.before_call("search", {"q": "x"}).allows_execution
        assert guard.after_call("search", {"q": "x"}, throttled, True).action == "allow"
    # Still counted per tool, so a dead endpoint is bounded.
    assert guard.after_call("search", {"q": "x"}, throttled, True).action == "halt"


def test_ordinary_identical_failures_still_warn_and_block():
    guard = GuardrailController(GuardrailConfig())
    error = '{"success": false, "error": "bad query"}'
    guard.after_call("search", {"q": "x"}, error, True)
    assert guard.after_call("search", {"q": "x"}, error, True).action == "warn"
    guard.after_call("search", {"q": "x"}, error, True)
    assert guard.before_call("search", {"q": "x"}).action == "block"


async def test_guardrail_halt_is_not_overwritten_by_later_parallel_tool_call():
    from cairnkit import ModelResponse, ToolCall

    events: list = []
    batch = ModelResponse(
        content=None,
        tool_calls=[
            ToolCall("c1", "echo", '{"text": "boom"}'),
            ToolCall("c2", "echo", '{"text": "after-halt"}'),
        ],
    )
    model = ScriptedModel([batch, say("stopped safely")])
    agent = Agent(
        spec(max_iterations=5, guardrails=GuardrailConfig(same_tool_failure_halt_after=1)),
        model=model,
        tools=registry(events),
    )
    result = await agent.run("go", ToolContext())
    assert result.stop_reason == "guardrail"
    assert result.text == "stopped safely"
    # Second tool call in the batch was skipped rather than executed, and paired in messages.
    assert events == [("handler", "boom")]
    assert len(result.tool_records) == 2
    assert "skipped" in result.tool_records[1].result
    tool_ids = [m["tool_call_id"] for m in result.messages if m.get("role") == "tool"]
    assert tool_ids == ["c1", "c2"]


async def test_passing_full_messages_as_history_does_not_duplicate_system_prompt():
    model = ScriptedModel([say("first"), say("second")])
    agent = Agent(spec(), model=model, tools=registry())
    first = await agent.run("turn 1", ToolContext(), volatile=["Time: 9:00"])
    second = await agent.run("turn 2", ToolContext(), history=first.messages)
    sent = model.requests[1]["messages"]
    assert [m["role"] for m in sent].count("system") == 1
    assert sent[0]["content"] == first.system_prompt
    assert second.system_prompt == first.system_prompt


async def test_tool_access_is_exposed_in_events_and_records():
    from cairnkit import ModelResponse, ToolCall

    tools = ToolRegistry()

    @tools.tool(name="inspect_rec", description="Read.", access="read")
    def inspect_rec(args, ctx):
        if args.get("fail"):
            raise ToolError("read failed")
        return {"ok": True}

    @tools.tool(name="stage_draft", description="Propose.", access="propose")
    def stage_draft(args, ctx):
        return {"draft": 1}

    @tools.tool(name="commit_row", description="Write.", access="write")
    def commit_row(args, ctx):
        return {"saved": 1}

    events = []
    batch_halt = ModelResponse(
        content=None,
        tool_calls=[
            ToolCall("c3", "inspect_rec", '{"fail": true}'),
            ToolCall("c4", "commit_row", "{}"),
        ],
    )
    model = ScriptedModel(
        [
            call("stage_draft", {}, "c1"),
            call("inspect_rec", {}, "c2"),
            batch_halt,
            say("finished"),
        ]
    )
    agent = Agent(
        spec(
            tools=["inspect_rec", "stage_draft", "commit_row"],
            max_iterations=5,
            guardrails=GuardrailConfig(same_tool_failure_halt_after=1),
        ),
        model=model,
        tools=tools,
    )
    result = await agent.run("run all", ToolContext(), on_event=events.append)
    assert [(r.name, r.access, r.failed) for r in result.tool_records] == [
        ("stage_draft", "propose", False),
        ("inspect_rec", "read", False),
        ("inspect_rec", "read", True),
        ("commit_row", "write", True),  # skipped after halt, still preserves declared access
    ]
    call_events = [
        (e.kind, e.data["tool"], e.data["access"])
        for e in events
        if e.kind in ("tool_call", "tool_result")
    ]
    assert call_events[:4] == [
        ("tool_call", "stage_draft", "propose"),
        ("tool_result", "stage_draft", "propose"),
        ("tool_call", "inspect_rec", "read"),
        ("tool_result", "inspect_rec", "read"),
    ]
