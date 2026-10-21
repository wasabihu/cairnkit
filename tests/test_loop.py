import json

from cairnkit import (
    Agent,
    AgentSpec,
    GuardrailConfig,
    ScriptedModel,
    ToolContext,
    ToolError,
    ToolRegistry,
)
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
