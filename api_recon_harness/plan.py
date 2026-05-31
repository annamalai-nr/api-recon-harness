"""Plan: translate a validated RequestObject into the kernel's native ProbeConfig.

Pure and deterministic — the same RequestObject yields a byte-identical
probe_config.json (no timestamps, no ordering surprises), which is the
reproducibility artifact (spec §8.1).
"""

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from api_recon_harness.models import ProbeConfig, RequestObject


def _split_url(endpoint_url: str) -> tuple[str, str]:
    parts = urlsplit(endpoint_url)
    base_url = f"{parts.scheme}://{parts.netloc}"
    endpoint = parts.path or "/"
    return base_url, endpoint


def endpoint_slug(endpoint_url: str) -> str:
    _, endpoint = _split_url(endpoint_url)
    return re.sub(r"\W+", "_", endpoint).strip("_") or "endpoint"


def _param_dict(p) -> dict:
    d: dict = {
        "name": p.name,
        "purpose": p.purpose,
        "tier1_values": list(p.tier1_values),
        "pinned_companions": [{"name": c.name, "value": c.value} for c in p.pinned_companions],
    }
    if p.tier3_edges_override:
        d["tier3_edges_override"] = [
            {"label": e.label, "value": e.value} for e in p.tier3_edges_override
        ]
    return d


def build_probe_config(req: RequestObject) -> ProbeConfig:
    base_url, endpoint = _split_url(req.endpoint_url)
    output_dir = req.output_dir or f"./outputs/api_recon/{endpoint_slug(req.endpoint_url)}"
    # The kernel requires independence to be declared for any `parameters`-list
    # config; for a single parameter there is no joint space, so it is trivially
    # independent. Intake already enforces the declaration for the multi-param case.
    independence = req.parameters_independence_declared or len(req.parameters) <= 1
    return ProbeConfig(
        base_url=base_url,
        endpoint=endpoint,
        auth_header=req.auth_header_name,
        auth_env_var=req.auth_env_var,
        timeout_s=req.timeout_seconds,
        run_auth_edges=req.run_auth_edges,
        output_dir=output_dir,
        parameters_independence_declared=independence,
        parameters=[_param_dict(p) for p in req.parameters],
        shared_tier3_edges=[{"label": e.label} for e in req.shared_tier3_edges],
        tier4_adversarial=[{"label": a.label, "value": a.value} for a in req.tier4_adversarial],
    )


def config_json(cfg: ProbeConfig) -> str:
    """Stable serialization: fixed field order (model order), 2-space indent."""
    return json.dumps(cfg.model_dump(), indent=2, ensure_ascii=False) + "\n"


def write_probe_config(cfg: ProbeConfig, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(config_json(cfg), encoding="utf-8")
    return dest
