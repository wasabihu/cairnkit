"""Check the citations in a draft with claimcite before a person reviews it.

Run: ``uv run --with claimcite python examples/verify_citations.py``

claimcite (https://github.com/wasabihu/claimcite) looks every DOI and PMID up in doi.org,
PubMed and Crossref, and says whether the paper exists, matches the title and year written
next to it, and contains the quoted words. Wrapped as a read tool, it lets an agent check a
draft before the host puts it in front of a reviewer, so the reviewer sees which citations
are wrong instead of finding out later.

This example needs network access for the lookups. The model is ScriptedModel: no API key.
"""

from __future__ import annotations

import asyncio
import json

from cairnkit import (
    Agent,
    AgentSpec,
    ModelResponse,
    ScriptedModel,
    ToolCall,
    ToolContext,
    ToolRegistry,
    tool_result,
)

DRAFT = """\
Daily aspirin keeps healthy older people free of disability. McNeil JJ et al. (2018).
Effect of Aspirin on Disability-free Survival in the Healthy Elderly. PMID: 30221596

Vitamin D cures depression. Smith A (2022). Vitamin D for depression: a randomized trial.
JAMA. https://doi.org/10.1001/jama.2022.99999
"""

tools = ToolRegistry()


@tools.tool(
    name="verify_citations",
    description=(
        "Check every DOI and PMID in a text: does the paper exist, do the title and year "
        "match, and does it contain the quoted words. Returns one line per citation."
    ),
    parameters={
        "type": "object",
        "properties": {"text": {"type": "string", "description": "The draft to check."}},
        "required": ["text"],
        "additionalProperties": False,
    },
)
def verify_citations(args, ctx):
    from claimcite.check import check_text  # optional: only this example needs it

    # web=False: check DOIs and PMIDs only, which is quick; ordinary web links are skipped.
    findings = check_text(args["text"], web=False)
    return tool_result(
        citations=[
            {
                "id": f.ref.id,
                "line": f.ref.line,
                "status": f.status,  # ok | warning | error | unchecked
                "exists": f.exists,
                "title_match": f.title_match,
                "registry_title": f.record.title if f.record else None,
            }
            for f in findings
        ]
    )


def offline_model() -> ScriptedModel:
    def respond(messages, tools):
        if messages[-1]["role"] == "user":
            return ModelResponse(
                None, [ToolCall("c1", "verify_citations", json.dumps({"text": DRAFT}))]
            )
        found = json.loads(messages[-1]["content"])["citations"]
        bad = [c for c in found if c["status"] == "error"]
        lines = [f"- line {c['line']}: {c['id']} is {c['status']}" for c in found]
        verdict = (
            f"{len(bad)} of {len(found)} citations are wrong; fix them before review."
            if bad
            else "Every citation checks out; ready for review."
        )
        return ModelResponse("\n".join([verdict, *lines]))

    return ScriptedModel(responder=respond)


async def main() -> None:
    spec = AgentSpec(
        name="citation_checker",
        description="Checks the citations in a draft before it goes to a reviewer.",
        persona="Check the draft's citations with verify_citations and report what is wrong.",
        tools=tools.names(),
        max_iterations=3,
    )
    result = await Agent(spec, model=offline_model(), tools=tools).run(
        "Check the citations in this draft before I send it for review.",
        ToolContext(principal={"id": "editor-01", "name": "Lee"}),
    )
    print(result.text)


if __name__ == "__main__":
    asyncio.run(main())
