"""Bounded LLM steps — orchestration only.

Each step is a single constrained completion: structured evidence in,
schema-validated JSON out. Prompt text lives in `prompts/`; the LiteLLM call
lives in `llm_client.py`. This module just wires them and validates output.
Untrusted API bodies reach the model only via the envelope (inside the prompts);
ids and formatting are owned by `render.py`, not the model.
"""

from urllib.parse import urlsplit

from api_recon_harness import prompts
from api_recon_harness.llm_client import complete_json
from api_recon_harness.models import (
    ApiAvailableInfo,
    EvidenceBundle,
    Finding,
    FindingsResponse,
    ParameterSpec,
    PoliciesResponse,
    Policy,
    RequestObject,
)


def generate_findings(ev: EvidenceBundle, params: list[ParameterSpec]) -> list[Finding]:
    data = complete_json(prompts.FINDINGS_SYSTEM_PROMPT, prompts.findings_instruction(ev, params))
    return FindingsResponse.model_validate(data).findings


def generate_policies(findings: list[Finding], downstream: str) -> list[Policy]:
    data = complete_json(prompts.POLICIES_SYSTEM_PROMPT,
                         prompts.policies_instruction(findings, downstream))
    return PoliciesResponse.model_validate(data).policies


def build_api_info(req: RequestObject, docs_text: str | None) -> ApiAvailableInfo:
    domain = urlsplit(req.endpoint_url).netloc
    service = domain.split(".")[0] if domain else "unknown service"
    documentation = (req.docs_url or
                     ("No public documentation found during this recon pass." if not docs_text else "see docs"))
    if not docs_text:
        return ApiAvailableInfo(
            service=service,
            endpoint=f"GET {req.endpoint_url}",
            purpose=f"GET endpoint at {req.endpoint_url}; behavior characterized empirically.",
            auth=f"API key via {req.auth_header_name} header.",
            documentation=documentation,
            documented_response_shape="Not documented.",
            documentation_gaps="No documentation was consulted in this pass.",
        )
    data = complete_json(prompts.API_INFO_SYSTEM_PROMPT,
                         prompts.api_info_instruction(service, req.endpoint_url, docs_text))
    return ApiAvailableInfo(
        service=service,
        endpoint=f"GET {req.endpoint_url}",
        purpose=data.get("purpose", "")[:500] or "See documentation.",
        auth=f"API key via {req.auth_header_name} header.",
        documentation=documentation,
        documented_response_shape=data.get("documented_response_shape", "Not documented.")[:500],
        documentation_gaps=data.get("documentation_gaps", "")[:500] or "None noted.",
    )
