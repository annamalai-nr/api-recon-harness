"""Docs → candidate-config drafter (spec §4 "the one genuine agent", §9 last step).

Given an endpoint + a docs URL but no hand-written parameters, draft a candidate
RequestObject from the documentation, then let the *deterministic* intake gate
own the verdict. A single constrained completion (prompt in `prompts/draft.py`,
transport in `llm_client.py`); the docs blob is envelope-escaped because remote
content is untrusted.

Swapping in LangChain v1 `create_agent` + `ToolCallLimitMiddleware` for
multi-tool doc exploration is a drop-in replacement for `_draft_parameters`;
the intake validator stays the authority either way.
"""

from api_recon_harness.intake import IntakeResult, intake
from api_recon_harness.llm_client import complete_json
from api_recon_harness.models import DraftResponse
from api_recon_harness.prompts import DRAFT_SYSTEM_PROMPT, draft_instruction


def _draft_parameters(req_partial: dict, docs_text: str) -> dict:
    data = complete_json(DRAFT_SYSTEM_PROMPT, draft_instruction(req_partial, docs_text))
    draft = DraftResponse.model_validate(data).model_dump()
    # Query-parameter values are always strings; coerce so an otherwise-valid
    # draft is not rejected on a numeric-literal type mismatch.
    for p in draft["parameters"]:
        p["tier1_values"] = [str(v) for v in p.get("tier1_values", [])]
        for c in p.get("pinned_companions", []) or []:
            c["value"] = str(c.get("value", ""))
    return draft


def draft_request_from_docs(req_partial: dict, docs_text: str | None) -> tuple[dict, IntakeResult]:
    """Draft parameters from docs, merge into the request, and run the intake gate.

    Returns (completed_request_dict, intake_verdict). The deterministic validator
    owns the verdict — a drafted config is never trusted on its own.
    """
    completed = dict(req_partial)
    if not completed.get("parameters") and docs_text:
        draft = _draft_parameters(req_partial, docs_text)
        completed["parameters"] = draft["parameters"]
        if len(draft["parameters"]) > 1:
            completed["parameters_independence_declared"] = draft["parameters_independence_declared"]
    return completed, intake(completed)
