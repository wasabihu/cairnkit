"""Minimal ASGI + SQLite + SSE proposal/approval example with cairnkit.

Run offline: ``uv run python examples/web_approval.py``

Uses only Python's standard library (``sqlite3``, ``asyncio``, ``json``) plus ``httpx`` (already a
core dependency) and ``ScriptedModel``. Demonstrates how a web backend owns authentication,
optimistic locking, database transactions, and streaming SSE events:

- ``GET /accounts/{account_id}`` returns ``{id, billing_email, version}``.
- ``POST /tickets/{ticket_id}/propose`` reads caller identity from request headers into
  ``ToolContext``, runs ``Agent.run(..., stream=True, on_event=...)``, streams SSE frames
  (``tool_call``, ``tool_result``, ``text_delta``, ``done``), and leaves the account untouched
  while storing a ``pending`` draft row tied to ``base_version``.
- ``POST /drafts/{draft_id}/review`` is host-only (never exposed as a model tool): returns ``403``
  unless caller has the ``reviewer`` role, ``409`` if stale/already reviewed, and ``200`` when
  atomically committing the approved change.
"""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from collections.abc import Callable
from typing import Any

import httpx

from cairnkit import (
    Agent,
    AgentSpec,
    ModelResponse,
    RunEvent,
    ScriptedModel,
    ToolCall,
    ToolContext,
    ToolError,
    ToolRegistry,
)


def init_db(db_path: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS accounts (
            id TEXT PRIMARY KEY,
            billing_email TEXT NOT NULL,
            version INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tickets (
            id TEXT PRIMARY KEY,
            account_id TEXT NOT NULL,
            body TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id TEXT NOT NULL,
            account_id TEXT NOT NULL,
            proposed_by TEXT NOT NULL,
            before_email TEXT NOT NULL,
            after_email TEXT NOT NULL,
            base_version INTEGER NOT NULL,
            status TEXT NOT NULL,
            reviewed_by TEXT
        );
        """
    )
    conn.execute(
        "INSERT OR IGNORE INTO accounts (id, billing_email, version) VALUES (?, ?, ?)",
        ("ACCT-1", "accounts@example.com", 1),
    )
    conn.execute(
        "INSERT OR IGNORE INTO tickets (id, account_id, body) VALUES (?, ?, ?)",
        ("TICKET-1042", "ACCT-1", "Please update our billing email to billing@example.com."),
    )
    conn.commit()
    return conn


def _parse_headers(scope: dict[str, Any]) -> dict[str, str]:
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}


def _sse_frame(event: str, payload: dict[str, Any]) -> bytes:
    data = json.dumps(payload, ensure_ascii=False)
    return f"event: {event}\ndata: {data}\n\n".encode()


async def _read_body(receive: Callable[[], Any]) -> bytes:
    chunks: list[bytes] = []
    while True:
        message = await receive()
        chunks.append(message.get("body", b""))
        if not message.get("more_body", False):
            return b"".join(chunks)


async def _send_json(
    send: Callable[[dict[str, Any]], Any],
    status: int,
    payload: dict[str, Any],
) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body, "more_body": False})


def create_app(conn: sqlite3.Connection) -> Callable[[dict[str, Any], Any, Any], Any]:
    """Build a minimal ASGI 3.0 application backed by host SQLite tables."""

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            raise ValueError(f"Unsupported ASGI scope: {scope['type']}")

        method = scope["method"].upper()
        path = scope["path"]
        headers = _parse_headers(scope)
        raw_body = await _read_body(receive)

        if method == "GET" and path.startswith("/accounts/"):
            account_id = path.removeprefix("/accounts/")
            row = conn.execute(
                "SELECT id, billing_email, version FROM accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
            if row is None:
                await _send_json(send, 404, {"error": "account_not_found"})
                return
            await _send_json(send, 200, dict(row))
            return

        if method == "POST" and re.fullmatch(r"/tickets/[^/]+/propose", path):
            ticket_id = path.split("/")[2]
            user_id = headers.get("x-user-id", "")
            user_name = headers.get("x-user-name", "")
            user_role = headers.get("x-user-role", "")
            if not user_id or not user_role:
                await _send_json(send, 401, {"error": "missing_identity_headers"})
                return
            ticket = conn.execute(
                "SELECT id, account_id, body FROM tickets WHERE id = ?",
                (ticket_id,),
            ).fetchone()
            if ticket is None:
                await _send_json(send, 404, {"error": "ticket_not_found"})
                return

            ctx = ToolContext(
                principal={"id": user_id, "name": user_name or user_id},
                roles=frozenset({user_role}),
                scope={"ticket_id": ticket_id, "account_id": ticket["account_id"]},
            )
            tools = ToolRegistry()

            @tools.tool(
                name="read_ticket",
                description="Read the ticket selected in the caller's scope.",
                access="read",
                roles={"support"},
            )
            def read_ticket(args: dict[str, Any], tool_ctx: ToolContext) -> dict[str, Any]:
                if tool_ctx.scope.get("ticket_id") != ticket_id:
                    raise ToolError("Ticket not in caller scope.")
                return {
                    "ticket_id": ticket["id"],
                    "account_id": ticket["account_id"],
                    "body": ticket["body"],
                }

            @tools.tool(
                name="propose_billing_email",
                description="Create a pending draft change for human review.",
                parameters={
                    "type": "object",
                    "properties": {"email": {"type": "string"}},
                    "required": ["email"],
                    "additionalProperties": False,
                },
                access="propose",
                roles={"support"},
            )
            def propose_billing_email(
                args: dict[str, Any],
                tool_ctx: ToolContext,
            ) -> dict[str, Any]:
                email = args.get("email")
                if (
                    set(args) != {"email"}
                    or not isinstance(email, str)
                    or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email)
                ):
                    raise ToolError("Valid email address required.")
                with conn:
                    acct = conn.execute(
                        "SELECT billing_email, version FROM accounts WHERE id = ?",
                        (tool_ctx.scope["account_id"],),
                    ).fetchone()
                    cur = conn.execute(
                        "INSERT INTO drafts ("
                        "ticket_id, account_id, proposed_by, before_email, "
                        "after_email, base_version, status"
                        ") VALUES (?, ?, ?, ?, ?, ?, 'pending')",
                        (
                            ticket_id,
                            tool_ctx.scope["account_id"],
                            tool_ctx.principal["id"],
                            acct["billing_email"],
                            email,
                            acct["version"],
                        ),
                    )
                return {
                    "draft_id": cur.lastrowid,
                    "status": "pending",
                    "base_version": acct["version"],
                    "account_updated": False,
                }

            model = ScriptedModel(
                [
                    ModelResponse(None, [ToolCall("t1", "read_ticket", "{}")]),
                    ModelResponse(
                        None,
                        [
                            ToolCall(
                                "t2",
                                "propose_billing_email",
                                json.dumps({"email": "billing@example.com"}),
                            )
                        ],
                    ),
                    ModelResponse("Created pending draft; waiting for reviewer approval."),
                ]
            )
            spec = AgentSpec(
                name="billing_helper",
                description="Proposes billing email updates without writing production rows.",
                persona="Read the ticket and create a pending draft.",
                tools=tools.names(),
                max_iterations=4,
            )

            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"text/event-stream; charset=utf-8")],
                }
            )
            queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()

            async def on_event(ev: RunEvent) -> None:
                await queue.put((ev.kind, ev.data))

            async def run_turn() -> None:
                try:
                    result = await Agent(spec, model=model, tools=tools).run(
                        "Prepare a billing email draft from the ticket.",
                        ctx,
                        stream=True,
                        on_event=on_event,
                    )
                    draft = conn.execute(
                        "SELECT id, status, after_email, base_version "
                        "FROM drafts ORDER BY id DESC LIMIT 1"
                    ).fetchone()
                    await queue.put(
                        (
                            "done",
                            {
                                "reply": result.text,
                                "draft": dict(draft) if draft else None,
                            },
                        )
                    )
                except Exception as exc:  # pragma: no cover - defensive SSE error frame
                    await queue.put(("done", {"error": str(exc)}))

            task = asyncio.create_task(run_turn())
            while True:
                ev_name, payload = await queue.get()
                is_last = ev_name == "done"
                await send(
                    {
                        "type": "http.response.body",
                        "body": _sse_frame(ev_name, payload),
                        "more_body": not is_last,
                    }
                )
                if is_last:
                    break
            await task
            return

        if method == "POST" and re.fullmatch(r"/drafts/\d+/review", path):
            body = json.loads(raw_body.decode("utf-8") or "{}")
            decision = body.get("decision")
            user_id = headers.get("x-user-id", "")
            user_role = headers.get("x-user-role", "")
            if user_role != "reviewer":
                await _send_json(send, 403, {"error": "reviewer_role_required"})
                return
            if decision not in {"approve", "reject"}:
                await _send_json(send, 400, {"error": "invalid_decision"})
                return
            draft_id = int(path.split("/")[2])
            conn.execute("BEGIN IMMEDIATE")
            try:
                draft = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
                if draft is None:
                    conn.rollback()
                    await _send_json(send, 404, {"error": "draft_not_found"})
                    return
                acct = conn.execute(
                    "SELECT id, billing_email, version FROM accounts WHERE id = ?",
                    (draft["account_id"],),
                ).fetchone()
                if draft["status"] != "pending" or acct["version"] != draft["base_version"]:
                    conn.rollback()
                    await _send_json(
                        send,
                        409,
                        {
                            "error": "stale_or_reviewed",
                            "draft_status": draft["status"],
                            "current_version": acct["version"],
                            "base_version": draft["base_version"],
                        },
                    )
                    return
                if decision == "approve":
                    updated = conn.execute(
                        "UPDATE accounts SET billing_email = ?, version = version + 1 "
                        "WHERE id = ? AND version = ?",
                        (draft["after_email"], acct["id"], draft["base_version"]),
                    )
                    if updated.rowcount != 1:
                        conn.rollback()
                        await _send_json(send, 409, {"error": "version_conflict"})
                        return
                new_status = "approved" if decision == "approve" else "rejected"
                conn.execute(
                    "UPDATE drafts SET status = ?, reviewed_by = ? WHERE id = ?",
                    (new_status, user_id, draft_id),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            acct_after = dict(
                conn.execute(
                    "SELECT id, billing_email, version FROM accounts WHERE id = ?",
                    (draft["account_id"],),
                ).fetchone()
            )
            draft_after = dict(
                conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
            )
            await _send_json(send, 200, {"account": acct_after, "draft": draft_after})
            return

        await _send_json(send, 404, {"error": "not_found"})

    return app


def parse_sse_events(raw_text: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in raw_text.strip().split("\n\n"):
        if not block.strip():
            continue
        event_name = ""
        data_line = "{}"
        for line in block.splitlines():
            if line.startswith("event: "):
                event_name = line.removeprefix("event: ").strip()
            elif line.startswith("data: "):
                data_line = line.removeprefix("data: ").strip()
        events.append((event_name, json.loads(data_line)))
    return events


async def run_demo() -> dict[str, Any]:
    conn = init_db(":memory:")
    app = create_app(conn)
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            propose_resp = await client.post(
                "/tickets/TICKET-1042/propose",
                headers={
                    "x-user-id": "support-01",
                    "x-user-name": "Sam",
                    "x-user-role": "support",
                },
            )
            sse_events = parse_sse_events(propose_resp.text)
            draft_id = sse_events[-1][1]["draft"]["id"]
            before_review = (await client.get("/accounts/ACCT-1")).json()

            self_approve = await client.post(
                f"/drafts/{draft_id}/review",
                headers={"x-user-id": "support-01", "x-user-role": "support"},
                json={"decision": "approve"},
            )
            approved = await client.post(
                f"/drafts/{draft_id}/review",
                headers={"x-user-id": "reviewer-01", "x-user-role": "reviewer"},
                json={"decision": "approve"},
            )
            replay_conflict = await client.post(
                f"/drafts/{draft_id}/review",
                headers={"x-user-id": "reviewer-01", "x-user-role": "reviewer"},
                json={"decision": "approve"},
            )
            after_review = (await client.get("/accounts/ACCT-1")).json()

        return {
            "sse_event_kinds": [name for name, _ in sse_events],
            "draft_id": draft_id,
            "before_review": before_review,
            "self_approve_status": self_approve.status_code,
            "approved_status": approved.status_code,
            "replay_conflict_status": replay_conflict.status_code,
            "after_review": after_review,
        }
    finally:
        conn.close()


async def main() -> None:
    res = await run_demo()
    print("== Offline ASGI + SQLite + SSE Approval Flow ==")
    print(f"SSE stream events   : {res['sse_event_kinds']}")
    print(f"Before human review : {res['before_review']}")
    print(f"Support self-review : HTTP {res['self_approve_status']} (blocked)")
    print(f"Reviewer approve    : HTTP {res['approved_status']} -> {res['after_review']}")
    print(f"Stale replay check  : HTTP {res['replay_conflict_status']} (optimistic lock)")


if __name__ == "__main__":
    asyncio.run(main())
