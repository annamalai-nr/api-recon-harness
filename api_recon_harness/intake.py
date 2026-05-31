"""Intake & scope gate — pure-Python validation before any network call.

Rejects out-of-scope work (per the v3.1 GET-only scope) and returns a question
list for missing mandatory fields instead of guessing. No network here.
"""

from urllib.parse import urlsplit

from pydantic import BaseModel

from api_recon_harness.models import RequestObject

# Names that mean "auth is being passed as a query parameter" — out of scope,
# secrets would leak into probe_log.jsonl URLs.
_AUTH_LIKE_NAMES = {
    "apikey", "api_key", "api-key", "authorization", "token",
    "access_token", "accesstoken", "key", "secret", "password",
}

# Request shapes outside the GET-only scope. If any of these keys is present in
# the raw request, decline before any network call (mirrors the kernel's
# UNSUPPORTED_KEYS, applied one layer earlier).
_UNSUPPORTED_KEYS = {
    "method": "non-GET HTTP methods are not supported",
    "request_body": "request bodies are not supported",
    "json_body": "JSON request bodies are not supported",
    "path_params": "path-parameter APIs are not supported",
    "extra_params": "joint multi-parameter variation is not supported",
    "pagination": "pagination / cursor traversal is not supported",
    "oauth": "OAuth and multi-step auth flows are not supported",
    "endpoints": "multi-endpoint orchestration is not supported",
    "semantic_pairs": "semantic-pair probing (e.g. start_date > end_date) is not supported",
    "joint_value_space": "joint-value-space probing is not supported",
}

MANDATORY = ("endpoint_url", "auth_header_name", "auth_env_var", "parameters")


class IntakeResult(BaseModel):
    ok: bool
    request: RequestObject | None = None
    questions: list[str] = []
    rejection: str | None = None


def _missing_field_questions(raw: dict) -> list[str]:
    q: list[str] = []
    for field in MANDATORY:
        if not raw.get(field):
            q.append(f"What is the `{field}`? (required — I will not guess it.)")
    for i, p in enumerate(raw.get("parameters") or []):
        if not isinstance(p, dict):
            continue
        if not p.get("name"):
            q.append(f"parameters[{i}]: what is the parameter `name`?")
        if not p.get("tier1_values"):
            q.append(f"parameters[{i}]: I need 6-10 valid `tier1_values` to probe.")
    return q


def _scope_rejection(raw: dict) -> str | None:
    for key, why in _UNSUPPORTED_KEYS.items():
        if key in raw:
            return f"Out of scope: {why} (request declares `{key}`)."

    url = raw.get("endpoint_url", "")
    if url and urlsplit(url).scheme not in ("http", "https"):
        return f"Endpoint URL must be http(s); got `{url}`."
    path = urlsplit(url).path
    if "{" in path or "}" in path:
        return ("Path-parameter-only APIs are out of scope (endpoint path contains "
                "`{...}` placeholders). This harness probes query parameters only.")
    if urlsplit(url).query:
        return ("Pass query parameters via the `parameters` list, not baked into "
                "`endpoint_url`; the endpoint URL must be path-only.")

    params = raw.get("parameters") or []
    if len(params) > 1 and not raw.get("parameters_independence_declared"):
        return ("Multi-parameter runs require `parameters_independence_declared: true`. "
                "If the parameters can only be characterized as a joint value space, "
                "that is out of scope (probe one at a time with pinned companions).")

    secret = (raw.get("auth_env_var") or "")
    auth_header = (raw.get("auth_header_name") or "").lower()
    for p in params:
        if not isinstance(p, dict):
            continue
        names = [p.get("name", "")] + [c.get("name", "") for c in (p.get("pinned_companions") or [])]
        for n in names:
            low = (n or "").lower()
            if low in _AUTH_LIKE_NAMES or (auth_header and low == auth_header):
                return (f"Parameter/companion `{n}` looks like an auth credential. "
                        "Auth-as-query-parameter is out of scope — secrets would leak "
                        "into probe logs. Pass the key via the auth header only.")
        values = list(p.get("tier1_values") or []) + \
            [c.get("value", "") for c in (p.get("pinned_companions") or [])]
        if secret and any(secret == v for v in values):
            return (f"A probe value equals the auth env-var name `{secret}`. "
                    "Companions/values are literal and logged; never place secrets there.")
    return None


def intake(raw: dict) -> IntakeResult:
    """Validate a raw request dict. Questions for missing fields; reject out-of-scope."""
    questions = _missing_field_questions(raw)
    if questions:
        return IntakeResult(ok=False, questions=questions)

    rejection = _scope_rejection(raw)
    if rejection:
        return IntakeResult(ok=False, rejection=rejection)

    try:
        request = RequestObject.model_validate(raw)
    except Exception as e:  # noqa: BLE001 — surface validation loudly
        return IntakeResult(ok=False, rejection=f"Invalid request: {e}")

    return IntakeResult(ok=True, request=request)
