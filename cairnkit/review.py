# Adapted from hermes-agent v0.22.2 (d923a5e): agent/background_review.py
# Copyright (c) 2025 Nous Research. MIT License.
"""Background review: after a turn, a forked agent asks "should anything be remembered?".

The fork replays the finished conversation under the *same* system prompt (so the
provider's prefix cache is reused), receives the review instruction as the next user
message, and may only use the reviewer agent's own tools (typically the memory tool).
It never touches the main conversation: its messages are discarded and only the side
effects of its tools remain. Hosts run it off the request path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cairnkit.tools import ToolContext
from cairnkit.types import Message

if TYPE_CHECKING:
    from cairnkit.loop import Agent, RunResult

REVIEW_INSTRUCTION = (
    "Background review of the conversation above. You are not talking to the user now. "
    "Decide whether it contains durable facts worth saving to memory: facts the user stated, "
    "not guesses. If so, make all changes in one call to your memory tool, patching or "
    "removing entries that the conversation shows are outdated. If nothing is worth saving, "
    "answer exactly: Nothing to save."
)


async def review_conversation(
    reviewer: Agent,
    transcript: list[Message],
    ctx: ToolContext,
    *,
    instruction: str = REVIEW_INSTRUCTION,
) -> RunResult:
    """Run ``reviewer`` over a finished ``transcript`` (system message first)."""
    if not transcript or transcript[0].get("role") != "system":
        raise ValueError("transcript must start with the conversation's system message")
    persona = reviewer.spec.persona
    return await reviewer.run(
        f"{persona}\n\n{instruction}",
        ctx,
        history=[dict(m) for m in transcript[1:]],
        system_prompt=str(transcript[0]["content"]),
    )
