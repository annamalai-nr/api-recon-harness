"""Analyze: deterministic parse of probe_log.jsonl into structured candidates.

This is the boundary between code and judgment. Everything here is mechanical;
the LLM step downstream only turns these candidates into prose findings. Body
previews are carried raw and untrusted — they enter the LLM only via envelope.
"""

import json
from collections import defaultdict
from pathlib import Path

from api_recon_harness.models import (
    DependencySignal,
    EvidenceBundle,
    InjectionHit,
    RedirectSignal,
    ShaCollision,
)

_VALID_BODY_MIN = 10


def _load(log_file: Path) -> list[dict]:
    records = []
    with open(log_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records


def _per_param_validity(records: list[dict], param_names: list[str]) -> dict[str, float]:
    validity: dict[str, float] = {}
    for pname in param_names:
        cat12 = [r for r in records
                 if r.get("parameter") == pname and not r.get("endpoint_level")
                 and any(str(r.get("label", "")).startswith(f"{pname}_{t}") for t in ("t1_", "t2_"))]
        if not cat12:
            continue
        populated = sum(1 for r in cat12
                        if r.get("status") == 200 and (r.get("body_bytes_len") or 0) > _VALID_BODY_MIN)
        validity[pname] = round(populated / len(cat12), 3)
    return validity


def _dependencies(validity: dict[str, float]) -> list[DependencySignal]:
    if len(validity) < 2:
        return []
    max_rate = max(validity.values())
    ordered = sorted(validity.values())
    median = ordered[len(ordered) // 2]
    out = []
    for pname, rate in validity.items():
        if rate <= 0.30 or (max_rate > 0 and rate <= max_rate * 0.50):
            out.append(DependencySignal(parameter=pname, validity_rate=rate,
                                        median_rate=round(median, 3), max_rate=round(max_rate, 3)))
    return out


def analyze(log_file: Path, param_names: list[str]) -> EvidenceBundle:
    records = _load(log_file)

    status_dist: dict[str, int] = defaultdict(int)
    per_param: dict[str, int] = defaultdict(int)
    sha_to_labels: dict[str, list[str]] = defaultdict(list)
    injection: list[InjectionHit] = []
    redirects: list[RedirectSignal] = []
    empties: list[str] = []
    throttles: list[str] = []
    previews: dict[str, str] = {}
    labels: list[str] = []

    for r in records:
        label = str(r.get("label", "?"))
        labels.append(label)
        status_dist[str(r.get("status"))] += 1
        if r.get("parameter") and not r.get("endpoint_level"):
            per_param[r["parameter"]] += 1
        sha = (r.get("body_sha256") or "")[:12]
        if sha:
            sha_to_labels[sha].append(label)
        if r.get("heuristic_hits"):
            injection.append(InjectionHit(label=label, hits=list(r["heuristic_hits"])))
        if r.get("redirect_target"):
            redirects.append(RedirectSignal(label=label, target=r["redirect_target"],
                                            security_flag=r.get("security_flag")))
        if (r.get("body_bytes_len") or 0) < _VALID_BODY_MIN:
            empties.append(label)
        if r.get("throttle_retries", 0) > 0:
            throttles.append(label)
        if r.get("body_preview"):
            previews[label] = r["body_preview"]

    collisions = [ShaCollision(sha=sha, labels=lbls)
                  for sha, lbls in sha_to_labels.items() if len(lbls) > 1]
    validity = _per_param_validity(records, param_names)

    return EvidenceBundle(
        total_calls=len(records),
        labels=labels,
        status_distribution=dict(status_dist),
        per_param_call_counts=dict(per_param),
        sha_collisions=collisions,
        injection_hits=injection,
        redirects=redirects,
        empty_responses=empties,
        throttles=throttles,
        dependencies=_dependencies(validity),
        per_param_validity=validity,
        body_previews=previews,
    )
