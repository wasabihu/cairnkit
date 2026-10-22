# Show HN draft — use after the example and assets are public

Status: draft, not submitted. Be available to answer technical questions after posting.

## Title

Show HN: Cairnkit – A Python agent runtime with host-controlled tools and storage

## URL

https://github.com/wasabihu/cairnkit

## First comment

I open-sourced cairnkit for applications that already have users, roles and shared records.
The question behind it is: when an agent proposes an edit, what actually authorizes the write?

There is an offline example that reads a fictional support ticket, creates an invoice-email
draft, and asks you to approve or reject it in the terminal. The original record is unchanged
until the host's review function applies the draft. It runs without an API key:

    git clone https://github.com/wasabihu/cairnkit.git
    cd cairnkit
    uv run python examples/approval.py

You need Python 3.12+ and uv. The example uses ScriptedModel, not a live LLM.

The host supplies identity and scope through ToolContext. The registry filters tools by role
and checks the role again on dispatch. Approval and persistence remain application code;
marking a tool as "propose" does not itself enforce an approval workflow.

The core uses the standard library and httpx. It includes a tool loop, memory-edit plans,
skills, history search and context compression. Many mechanisms are ported from Hermes Agent
v0.22.2 (MIT, Nous Research); attribution and a porting map are in the repo. This is not
affiliated with Nous Research.

It is early-stage and not on PyPI. I would appreciate feedback on the boundary between an
agent runtime and an existing application's review/storage layer, or reports of a rough
edge in the example.
