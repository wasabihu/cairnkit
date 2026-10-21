"""Smallest complete cairnkit program. Runs offline: `uv run python examples/minimal.py`.

Swap ScriptedModel for `openrouter("deepseek/deepseek-v4-flash", api_key=...)` to use a
real model; nothing else changes.
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

tools = ToolRegistry()


@tools.tool(
    name="opening_hours",
    description="Opening hours for a weekday.",
    parameters={"type": "object", "properties": {"day": {"type": "string"}}, "required": ["day"]},
)
def opening_hours(args, ctx):
    return tool_result(day=args["day"], hours="7am-7pm", asked_by=ctx.principal["name"])


def offline_model() -> ScriptedModel:
    def respond(messages, tools):
        if messages[-1]["role"] == "user":
            return ModelResponse(
                None, [ToolCall("c1", "opening_hours", json.dumps({"day": "Sunday"}))]
            )
        hours = json.loads(messages[-1]["content"])["hours"]
        return ModelResponse(f"We're open {hours} on Sunday.")

    return ScriptedModel(responder=respond)


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        agent_dir = Path(tmp) / "agents" / "greeter"
        agent_dir.mkdir(parents=True)
        (agent_dir / "agent.toml").write_text('tools = ["opening_hours"]\nmax_iterations = 3\n')
        (agent_dir / "SOUL.md").write_text("You answer questions about the cafe's opening hours.")
        spec = load_agents(Path(tmp) / "agents")["greeter"]

    agent = Agent(spec, model=offline_model(), tools=tools)
    result = await agent.run("When do you open on Sunday?", ToolContext(principal={"name": "Ana"}))
    print(result.text)


if __name__ == "__main__":
    asyncio.run(main())
