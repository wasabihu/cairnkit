"""The public demo must show real host-side decisions, not just UI labels."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from cairnkit import ScriptedModel, ToolContext
from examples.approval import REVIEWER, STAFF, ApprovalDemo
from tests.conftest import call, say


async def test_proposal_does_not_mutate_saved_record():
    demo = ApprovalDemo()
    await demo.propose()
    assert demo.record == {"invoice_email": "accounts@example.com", "version": 1}
    assert demo.draft.status == "pending"
    assert demo.draft.proposed_by == STAFF.principal["id"]
    assert demo.draft.source == STAFF.scope["ticket_id"]
    assert "approve" not in demo.tools.names()
    assert all(e["record"]["version"] == 1 for e in demo.events)


@pytest.mark.parametrize("decision", ["approve", "reject"])
async def test_human_decision_controls_saved_record(decision):
    demo = ApprovalDemo()
    await demo.propose()
    demo.review(decision, REVIEWER)
    approved = decision == "approve"
    assert demo.record["invoice_email"] == (
        "billing@example.com" if approved else "accounts@example.com"
    )
    assert demo.record["version"] == (2 if approved else 1)
    assert demo.draft.status == ("approved" if approved else "rejected")
    assert demo.draft.reviewed_by == REVIEWER.principal["id"]
    with pytest.raises(ValueError, match="no pending"):
        demo.review("approve", REVIEWER)


async def test_staff_cannot_approve_even_with_a_valid_pending_draft():
    demo = ApprovalDemo()
    await demo.propose()
    with pytest.raises(PermissionError):
        demo.review("approve", STAFF)
    assert demo.draft.status == "pending"
    assert demo.record["version"] == 1


async def test_approval_refuses_a_stale_record():
    demo = ApprovalDemo()
    await demo.propose()
    demo.record.update(invoice_email="newer@example.com", version=2)
    with pytest.raises(ValueError, match="record changed"):
        demo.review("approve", REVIEWER)
    assert demo.record["invoice_email"] == "newer@example.com"
    assert demo.draft.status == "pending"


async def test_forged_identity_in_tool_arguments_cannot_create_a_draft():
    demo = ApprovalDemo()
    model = ScriptedModel(
        [
            call("propose_invoice_email", {"email": "billing@example.com", "role": "reviewer"}),
            say("Could not create draft."),
        ]
    )
    await demo.propose(model)
    assert demo.draft is None
    assert demo.record["version"] == 1


async def test_wrong_scope_and_disallowed_role_cannot_access_ticket():
    demo = ApprovalDemo()
    wrong_scope = ToolContext(principal={"id": "support-01"}, roles=STAFF.roles)
    read = await demo.tools.dispatch(demo.tools.get("read_ticket"), {}, wrong_scope)
    assert read.failed
    propose = await demo.tools.dispatch(
        demo.tools.get("propose_invoice_email"), {"email": "billing@example.com"}, REVIEWER
    )
    assert propose.failed
    assert demo.draft is None


async def test_model_cannot_invoke_host_review():
    demo = ApprovalDemo()
    model = ScriptedModel([call("approve", {}), say("Cannot approve.")])
    await demo.propose(model)
    assert demo.record["version"] == 1
    assert demo.draft is None


async def test_export_preserves_snapshots_and_discloses_simulation(tmp_path):
    demo = ApprovalDemo()
    await demo.propose()
    demo.review("approve", REVIEWER)
    path = tmp_path / "trace.js"
    demo.export(path, scripted_decision=True)
    trace = json.loads(
        path.read_text().removeprefix("window.CAIRNKIT_DEMO = ").strip().removesuffix(";")
    )
    assert "ScriptedModel" in trace["mode"]
    assert trace["decision_source"] == "scripted CLI choice"
    assert trace["events"][0]["record"]["invoice_email"] == "accounts@example.com"
    assert trace["events"][-1]["record"]["invoice_email"] == "billing@example.com"


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("", "rejected"),
        ("maybe\n", "rejected"),
        ("reject\n", "rejected"),
        ("approve\n", "approved"),
    ],
)
def test_terminal_review_is_explicit_and_fails_closed(answer, expected):
    result = subprocess.run(
        [sys.executable, str(Path(__file__).parents[1] / "examples" / "approval.py")],
        input=answer,
        text=True,
        capture_output=True,
        check=True,
    )
    assert f"Review: {expected} by reviewer-01" in result.stdout
    email = "billing@example.com" if expected == "approved" else "accounts@example.com"
    assert result.stdout.strip().endswith(f"Saved record: {email}")
