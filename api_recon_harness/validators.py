"""Verify & review gate (spec §4 step 5, §8).

Cheap deterministic checks plus the vendored parity verifier. A run is only
`complete` when every check passes; otherwise `needs_revision` with a one-line
repair task. The LLM cannot route around these — they are ordinary code.
"""

import subprocess
import sys
from pathlib import Path

from api_recon_harness.models import Finding, Policy
from api_recon_harness.paths import KERNEL_DIR


def scope_header_present(text: str) -> bool:
    low = text.lower()
    return ("reconnaissance of get" in low
            and "other methods" in low
            and "downstream assumption" in low
            and "auth-edge probes" in low)


def secret_scan(run_dir: Path, secret_value: str) -> tuple[bool, list[str]]:
    """No API key / auth value may appear in any artifact (spec §8.8)."""
    if not secret_value:
        return True, []
    offenders = []
    for path in run_dir.rglob("*"):
        if not path.is_file():
            continue
        try:
            if secret_value in path.read_text(encoding="utf-8", errors="ignore"):
                offenders.append(str(path.relative_to(run_dir)))
        except OSError:
            pass
    return (not offenders), offenders


def evidence_ref_integrity(findings: list[Finding], allowed: list[str]) -> tuple[bool, list[str]]:
    """Every cited evidence label must exist in probe_log.jsonl (spec §8.5)."""
    allowed_set = set(allowed)
    bad = []
    for f in findings:
        if not f.evidence_ref:
            bad.append(f"{f.id or f.title}: no evidence_ref")
        for ref in f.evidence_ref:
            if ref not in allowed_set:
                bad.append(f"{f.id or f.title}: unknown label '{ref}'")
    return (not bad), bad


def policy_mapping(policies: list[Policy], findings: list[Finding]) -> tuple[bool, list[str]]:
    """Every policy must map to a real finding id (spec §8.9)."""
    ids = {f.id for f in findings}
    bad = [p.finding_id for p in policies if p.finding_id not in ids]
    return (not bad), bad


def verify_parity(findings_md: Path, policies_md: Path, report_html: Path,
                  config: Path) -> tuple[bool, str]:
    """Run the vendored parity verifier as a subprocess (spec §8.6)."""
    proc = subprocess.run(
        [sys.executable, str(KERNEL_DIR / "verify_report_parity.py"),
         "--findings", str(findings_md), "--policies", str(policies_md),
         "--html", str(report_html), "--config", str(config)],
        capture_output=True, text=True,
    )
    return proc.returncode == 0, proc.stdout + proc.stderr


def review(run_dir: Path, findings: list[Finding], policies: list[Policy],
           allowed_labels: list[str], secret_value: str) -> tuple[str, str]:
    """Aggregate gate. Returns (state, detail)."""
    ok_ref, bad_ref = evidence_ref_integrity(findings, allowed_labels)
    if not ok_ref:
        return "needs_revision", f"Evidence-ref integrity failed: {bad_ref[:3]}"

    ok_map, bad_map = policy_mapping(policies, findings)
    if not ok_map:
        return "needs_revision", f"Policy maps to unknown finding(s): {bad_map[:3]}"

    findings_md = run_dir / "findings.md"
    policies_md = run_dir / "policies.md"
    report_html = run_dir / "report.html"
    config = run_dir / "probe_config.json"
    for art in (findings_md, policies_md, report_html, config):
        if not art.exists():
            return "needs_revision", f"Missing artifact: {art.name}"

    for art in (findings_md, policies_md, report_html):
        if not scope_header_present(art.read_text(encoding="utf-8")):
            return "needs_revision", f"Scope header incomplete in {art.name}"

    ok_secret, offenders = secret_scan(run_dir, secret_value)
    if not ok_secret:
        return "needs_revision", f"Secret leaked into: {offenders[:3]}"

    ok_parity, parity_out = verify_parity(findings_md, policies_md, report_html, config)
    if not ok_parity:
        tail = parity_out.strip().splitlines()[-1:] or ["parity failed"]
        return "needs_revision", f"Report parity failed: {tail[0]}"

    return "complete", "All checks passed."
