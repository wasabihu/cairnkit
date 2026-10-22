"""A complete offline proposal → human review → host write example.

Run ``uv run python examples/approval.py`` and approve or reject in the terminal.
``--decision approve`` scripts that human choice for repeatable tests and recordings.
The model is ScriptedModel: no network, API key, or real customer data is used.

The host owns this in-memory store and its review function. cairnkit does NOT turn
an access label into an approval workflow. There is deliberately no save/approve
tool exposed to this agent. This is an example, not a production auth or database layer.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path

from cairnkit import (
    Agent,
    AgentSpec,
    ModelResponse,
    ScriptedModel,
    ToolCall,
    ToolContext,
    ToolError,
    ToolRegistry,
)

TICKET_ID = "TICKET-1042"
TICKET_TEXT = "Please send future invoices to billing@example.com."
STAFF = ToolContext(
    principal={"id": "support-01", "name": "Sam"},
    roles=frozenset({"support"}),
    scope={"ticket_id": TICKET_ID},
)
REVIEWER = ToolContext(
    principal={"id": "reviewer-01", "name": "Alex"},
    roles=frozenset({"reviewer"}),
    scope={"ticket_id": TICKET_ID},
)


@dataclass(frozen=True)
class Draft:
    id: str
    source: str
    proposed_by: str
    before: str
    after: str
    base_version: int
    status: str = "pending"
    reviewed_by: str | None = None


class ApprovalDemo:
    """Host-side example policy; all state disappears when the process exits."""

    def __init__(self) -> None:
        self.record = {"invoice_email": "accounts@example.com", "version": 1}
        self.draft: Draft | None = None
        self.events: list[dict] = []
        self.tools = ToolRegistry()
        self.tools.tool(
            name="read_ticket",
            description="Read the ticket selected by the host application.",
            roles={"support"},
        )(self.read_ticket)
        self.tools.tool(
            name="propose_invoice_email",
            description="Queue a proposed invoice email change for a human reviewer.",
            parameters={
                "type": "object",
                "properties": {"email": {"type": "string"}},
                "required": ["email"],
                "additionalProperties": False,
            },
            access="propose",
            roles={"support"},
        )(self.propose_invoice_email)

    def snapshot(self, stage: str, actor: str) -> None:
        self.events.append(
            {
                "stage": stage,
                "actor": actor,
                "record": deepcopy(self.record),
                "draft": asdict(self.draft) if self.draft else None,
            }
        )

    @staticmethod
    def check_scope(ctx: ToolContext) -> None:
        if not ctx.principal.get("id") or ctx.scope.get("ticket_id") != TICKET_ID:
            raise ToolError("This ticket is not in the acting person's scope.")

    def read_ticket(self, args: dict, ctx: ToolContext) -> dict:
        self.check_scope(ctx)
        if args:
            raise ToolError("Ticket identity is supplied by the host, not tool arguments.")
        self.snapshot("read", ctx.principal["name"])
        return {"ticket_id": TICKET_ID, "text": TICKET_TEXT}

    def propose_invoice_email(self, args: dict, ctx: ToolContext) -> dict:
        self.check_scope(ctx)
        email = args.get("email")
        # Handlers validate too: a tool schema is not a security boundary.
        if (
            set(args) != {"email"}
            or not isinstance(email, str)
            or len(email) > 254
            or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email)
        ):
            raise ToolError("Only a valid email may be proposed.")
        if self.draft is not None:
            raise ToolError("This demo already has a proposal; start a new run.")
        self.draft = Draft(
            id="DRAFT-01",
            source=TICKET_ID,
            proposed_by=ctx.principal["id"],
            before=self.record["invoice_email"],
            after=email,
            base_version=self.record["version"],
        )
        self.snapshot("draft", ctx.principal["name"])
        return {"draft_id": self.draft.id, "status": "pending", "record_updated": False}

    def review(self, decision: str, ctx: ToolContext) -> None:
        """A host-controlled human action; never registered as a model tool."""
        self.check_scope(ctx)
        if "reviewer" not in ctx.roles:
            raise PermissionError("Only a reviewer may approve or reject a draft.")
        if decision not in {"approve", "reject"}:
            raise ValueError("Choose approve or reject.")
        if self.draft is None or self.draft.status != "pending":
            raise ValueError("There is no pending draft to review.")
        if decision == "approve" and self.record["version"] != self.draft.base_version:
            raise ValueError("The record changed after the proposal; review a fresh draft.")
        # A real host does the version check, update and audit in one transaction.
        if decision == "approve":
            self.record["invoice_email"] = self.draft.after
            self.record["version"] += 1
        self.draft = Draft(
            **{
                **asdict(self.draft),
                "status": "approved" if decision == "approve" else "rejected",
                "reviewed_by": ctx.principal["id"],
            }
        )
        self.snapshot("saved" if decision == "approve" else "rejected", ctx.principal["name"])

    async def propose(self, model: ScriptedModel | None = None) -> str:
        self.snapshot("request", STAFF.principal["name"])
        model = model or ScriptedModel(
            [
                ModelResponse(None, [ToolCall("read-1", "read_ticket", "{}")]),
                ModelResponse(
                    None,
                    [
                        ToolCall(
                            "draft-1", "propose_invoice_email", '{"email":"billing@example.com"}'
                        )
                    ],
                ),
                ModelResponse("A draft is ready for review. The saved invoice email is unchanged."),
            ]
        )
        spec = AgentSpec(
            name="ticket_assistant",
            description="Prepare invoice email changes for human review.",
            persona="Read the selected ticket and propose a change. Never claim it is saved.",
            tools=self.tools.names(),
            max_iterations=4,
        )
        result = await Agent(spec, model=model, tools=self.tools).run(
            "Read the selected ticket and prepare an invoice email change for review.", STAFF
        )
        if self.draft is not None:
            self.snapshot("review", REVIEWER.principal["name"])
        return result.text

    def export(self, path: Path, *, scripted_decision: bool) -> None:
        """Export this run for visual replay; the browser is not a live backend."""
        trace = {
            "mode": "Offline ScriptedModel · fictional data",
            "decision_source": "scripted CLI choice" if scripted_decision else "terminal review",
            "ticket_id": TICKET_ID,
            "source_text": TICKET_TEXT,
            "tools": self.tools.names(),
            "events": self.events,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "window.CAIRNKIT_DEMO = " + json.dumps(trace, indent=2).replace("<", "\\u003c") + ";\n",
            encoding="utf-8",
        )


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decision", choices=("approve", "reject"))
    parser.add_argument("--export", type=Path, help="Write a trace.js for the visual replay.")
    args = parser.parse_args()
    demo = ApprovalDemo()
    print("OFFLINE DEMO · ScriptedModel · fictional data · in-memory state\n")
    print(f"Source ({TICKET_ID}): {TICKET_TEXT}")
    print("Agent tools:", ", ".join(demo.tools.names()))
    print(await demo.propose())
    print("Saved record:", demo.record["invoice_email"])
    assert demo.draft is not None
    print(f"Pending draft: {demo.draft.before} → {demo.draft.after}")
    try:
        decision = args.decision or input("\nReview as Alex [approve/reject, default reject]: ")
    except EOFError:
        decision = "reject"
    decision = decision.strip().lower()
    # An empty or unexpected response never grants approval.
    demo.review("approve" if decision == "approve" else "reject", REVIEWER)
    print(f"\nReview: {demo.draft.status} by {demo.draft.reviewed_by}")
    print("Saved record:", demo.record["invoice_email"])
    if args.export:
        demo.export(args.export, scripted_decision=args.decision is not None)
        print("Visual replay trace:", args.export)


if __name__ == "__main__":
    asyncio.run(main())
