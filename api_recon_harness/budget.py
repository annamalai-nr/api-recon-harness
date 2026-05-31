"""Planned-call calculator + budget gate (spec §4 step 3, §8.3).

The kernel runner is reused unchanged, so the gate is *planned-call only*: it
mirrors the runner's fixed probe plan and refuses to start a run whose planned
count exceeds `max_calls`. It cannot cap the runner's internal throttle retries;
actual calls are reported afterward in status.json.
"""

from api_recon_harness.models import RequestObject

PER_PARAM_PROTOCOL = 3       # cat 5p: wrong_param, no_params, dup_param
ENDPOINT_PROTOCOL = 2        # cat 5e: OPTIONS, trailing slash
ENDPOINT_AUTH = 3            # cat 6: no_key, wrong_key, lowercase_hdr
ENDPOINT_CONCURRENCY = 5     # cat 7


def _per_param_calls(p, shared_edges_n: int) -> int:
    t1 = len(p.tier1_values)
    cat1 = t1
    cat2 = min(2, t1)
    cat3 = len(p.tier3_edges_override) if p.tier3_edges_override else shared_edges_n
    return cat1 + cat2 + cat3 + PER_PARAM_PROTOCOL


def planned_calls(req: RequestObject) -> int:
    """Deterministic count of probes the run will plan (preflight + runner plan)."""
    shared_n = len(req.shared_tier3_edges)
    per_param = sum(_per_param_calls(p, shared_n) for p in req.parameters)
    endpoint = (
        len(req.tier4_adversarial)
        + ENDPOINT_PROTOCOL
        + (ENDPOINT_AUTH if req.run_auth_edges else 0)
        + ENDPOINT_CONCURRENCY
    )
    preflight = len(req.parameters) if req.run_preflight else 0
    return per_param + endpoint + preflight


def gate(req: RequestObject) -> tuple[bool, int, str]:
    """Return (allowed, planned, message). allowed=False blocks before any call."""
    planned = planned_calls(req)
    if req.max_calls is not None and planned > req.max_calls:
        return False, planned, (
            f"Planned probe count {planned} exceeds max_calls={req.max_calls}. "
            "Reduce tier1_values / edges / disable auth edges, or raise max_calls. "
            "No request was made."
        )
    return True, planned, f"Planned {planned} calls (max_calls={req.max_calls})."
