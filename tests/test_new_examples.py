from __future__ import annotations

import importlib.util
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def _load_example(name: str):
    path = ROOT / "examples" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"example_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_zero_call_memory_example_offline():
    mod = _load_example("zero_call_memory")
    summary = await mod.run_demo()
    assert summary["blocked_injections"] == 1
    assert summary["prepass_attempts"] == 0
    assert summary["prepass_model_calls"] == 0
    assert summary["infeasible_error"] == "capacity_unreachable"
    assert summary["canonical_count"] == 4
    assert summary["overflow_attempts"] == 1
    assert "[workspace] Billing day: 5th" in summary["merged_entries"]
    assert "Using 2 memory items" in summary["agent_reply"]


async def test_web_approval_example_offline_and_stale_lock():
    mod = _load_example("web_approval")
    summary = await mod.run_demo()
    kinds = summary["sse_event_kinds"]
    assert "tool_call" in kinds and "tool_result" in kinds and "text_delta" in kinds
    assert kinds[-1] == "done"
    assert summary["before_review"] == {
        "id": "ACCT-1",
        "billing_email": "accounts@example.com",
        "version": 1,
    }
    assert summary["self_approve_status"] == 403
    assert summary["approved_status"] == 200
    assert summary["replay_conflict_status"] == 409
    assert summary["after_review"] == {
        "id": "ACCT-1",
        "billing_email": "billing@example.com",
        "version": 2,
    }


async def test_web_approval_stale_version_conflict():
    mod = _load_example("web_approval")
    conn = mod.init_db(":memory:")
    try:
        transport = httpx.ASGITransport(app=mod.create_app(conn))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            propose = await client.post(
                "/tickets/TICKET-1042/propose",
                headers={
                    "x-user-id": "support-01",
                    "x-user-name": "Sam",
                    "x-user-role": "support",
                },
            )
            events = mod.parse_sse_events(propose.text)
            draft_id = events[-1][1]["draft"]["id"]
            # Simulate concurrent account update outside this draft
            with conn:
                conn.execute("UPDATE accounts SET version = version + 1 WHERE id = 'ACCT-1'")
            stale = await client.post(
                f"/drafts/{draft_id}/review",
                headers={"x-user-id": "reviewer-01", "x-user-role": "reviewer"},
                json={"decision": "approve"},
            )
            assert stale.status_code == 409
            acct = (await client.get("/accounts/ACCT-1")).json()
            assert acct["billing_email"] == "accounts@example.com"
            assert acct["version"] == 2
    finally:
        conn.close()
