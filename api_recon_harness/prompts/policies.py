"""Prompts for the policies step (downstream-agnostic findings → policies)."""

import json

from api_recon_harness.models import Finding

POLICIES_SYSTEM_PROMPT = (
    "You translate downstream-agnostic API findings into downstream-specific "
    "engineering policies. Output ONLY JSON.\n\n"
    "Rules:\n"
    "- Exactly one policy per finding, keyed by finding_id.\n"
    "- Each policy: finding_id, detection_signal, policy_statement, code_implication.\n"
    "- Make policies proportional to the finding's reliability (don't over-commit on weak evidence).\n"
    "- Tailor to the downstream context provided."
)


def policies_instruction(findings: list[Finding], downstream: str) -> str:
    digest = [
        {"finding_id": f.id, "title": f.title, "severity": f.severity,
         "reliability": f.reliability, "observation": f.observation}
        for f in findings
    ]
    return (
        f"Downstream context: {downstream}\n\n"
        f"Findings (one policy each, key by finding_id):\n{json.dumps(digest, indent=2)}\n\n"
        'Return JSON: {"policies": [ {policy}, ... ]}.'
    )
