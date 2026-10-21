"""Writes become drafts a person approves. Runs offline: `uv run python examples/approval.py`.

The model never says who it is acting for: the host puts the signed-in person in
ToolContext. Tools declare an access level and the roles that may use them, so the same
agent offers different tools to different people.
"""

import asyncio
import json
import tempfile
from pathlib import Path

from cairnkit import (
    Agent,
    ModelResponse,
    ScriptedModel,
    ToolCall,
    ToolContext,
    ToolRegistry,
    load_agents,
    tool_result,
)

DRAFTS: list[dict] = []  # stands in for the host's database table of pending changes
tools = ToolRegistry()


@tools.tool(
    name="propose_note",
    description="Suggest a note about a customer. A manager approves it before anyone sees it.",
    parameters={
        "type": "object",
        "properties": {"customer": {"type": "string"}, "note": {"type": "string"}},
        "required": ["customer", "note"],
    },
    access="propose",
)
def propose_note(args, ctx):
    DRAFTS.append({**args, "by": ctx.principal["name"], "status": "pending"})
    return tool_result(queued=True, message="Saved as a draft for a manager to approve.")


@tools.tool(
    name="refund_order",
    description="Refund an order.",
    parameters={"type": "object", "properties": {"order": {"type": "string"}}},
    access="write",
    roles={"manager"},  # front-line staff never see this tool
)
def refund_order(args, ctx):
    return tool_result(refunded=args.get("order"))


def offline_model() -> ScriptedModel:
    def respond(messages, offered):
        names = sorted(t["function"]["name"] for t in offered or [])
        if messages[-1]["role"] == "user":
            print("tools offered:", names)
            args = {"customer": "Ana Ruiz", "note": "Prefers a window table."}
            return ModelResponse(None, [ToolCall("c1", "propose_note", json.dumps(args))])
        return ModelResponse("Noted. A manager will review it before it is saved.")

    return ScriptedModel(responder=respond)


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "agents" / "assistant"
        folder.mkdir(parents=True)
        (folder / "agent.toml").write_text(
            'tools = ["propose_note", "refund_order"]\nmax_iterations = 3\n'
        )
        (folder / "SOUL.md").write_text("You help staff look after customers.")
        spec = load_agents(Path(tmp) / "agents")["assistant"]

    agent = Agent(spec, model=offline_model(), tools=tools)
    staff = ToolContext(principal={"name": "Sam"}, roles=frozenset({"staff"}))
    result = await agent.run("Ana says she prefers a window table.", staff)
    print(result.text)
    print("drafts:", DRAFTS)


if __name__ == "__main__":
    asyncio.run(main())
