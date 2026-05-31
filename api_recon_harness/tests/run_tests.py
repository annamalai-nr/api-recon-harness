"""Harness self-tests — plain Python, no pytest, no network, no LLM (north_stars).

Covers the deterministic acceptance criteria (spec §10): determinism, scope
gate, budget gate, missing-field intake, evidence-ref integrity, policy mapping,
secret hygiene, redirect safety, and the render→parity contract.

Run: python -m api_recon_harness --validate
"""

import tempfile
from pathlib import Path

from api_recon_harness import budget, plan, render, validators
from api_recon_harness.intake import intake
from api_recon_harness.models import (
    ApiAvailableInfo,
    Companion,
    Finding,
    ParameterSpec,
    Policy,
    RequestObject,
)
from api_recon_harness.paths import KERNEL_DIR as KERNEL


# ─── Fixtures ────────────────────────────────────────────────────────────

def _multi_param_request() -> RequestObject:
    return RequestObject(
        endpoint_url="https://api.open-meteo.com/v1/forecast",
        auth_header_name="X-API-Key",
        auth_env_var="DUMMY_API_KEY",
        parameters_independence_declared=True,
        run_auth_edges=False,
        parameters=[
            ParameterSpec(name="latitude", purpose="WGS84 latitude",
                          tier1_values=["51.5", "48.8", "35.7", "-33.9", "0", "60"],
                          pinned_companions=[Companion(name="longitude", value="0")]),
            ParameterSpec(name="longitude", purpose="WGS84 longitude",
                          tier1_values=["0", "-74", "139.7", "151.2", "100", "-50"],
                          pinned_companions=[Companion(name="latitude", value="51.5")]),
        ],
    )


def _fixture_findings() -> list[Finding]:
    return [
        Finding(title="Trailing slash redirects to an http endpoint",
                severity="Major", scope="cross_parameter",
                parameters=["latitude", "longitude"],
                observation="The trailing-slash probe returned a redirect to an http target "
                            "for both probed parameters, a transport downgrade.",
                mechanism="The server normalizes the path and emits a Location header over "
                          "plain http rather than https.",
                reliability="Observed for tested input only across two parameters (2/2).",
                evidence_ref=["t5e_trailing_slash"]),
        Finding(title="Latitude accepts out of range values silently",
                severity="Major", scope="per_parameter", parameters=["latitude"],
                observation="Latitude value sixty returned a populated body with no validation "
                            "error, suggesting no range enforcement on the input.",
                mechanism="The endpoint clamps or ignores latitude bounds rather than "
                          "rejecting values beyond ninety degrees.",
                reliability="Observed in 1/6 tested examples: latitude value sixty.",
                evidence_ref=["latitude_t1_60_5"]),
        Finding(title="Empty latitude returns a tiny body",
                severity="Minor", scope="per_parameter", parameters=["latitude"],
                observation="The empty edge probe for latitude returned a very small body well "
                            "under the typical forecast payload size.",
                mechanism="An empty value short circuits the handler before forecast assembly.",
                reliability="Observed for tested input only for the empty latitude edge.",
                evidence_ref=["latitude_t3_empty"]),
        Finding(title="Longitude unicode input is echoed unchanged",
                severity="Minor", scope="per_parameter", parameters=["longitude"],
                observation="A cjk unicode longitude value was reflected in the response body "
                            "without normalization or rejection of the input.",
                mechanism="The parameter is passed through to a templating layer without "
                          "unicode sanitization of the value.",
                reliability="Observed for tested input only for the unicode longitude edge.",
                evidence_ref=["longitude_t3_unicode_cjk"]),
    ]


def _fixture_policies(findings: list[Finding]) -> list[Policy]:
    out = []
    for f in findings:
        out.append(Policy(
            finding_id=f.id,
            detection_signal=f"Watch the {f.parameters[0]} responses for the behavior described "
                             "in the matching finding during client integration.",
            policy_statement=f"The client must account for {f.title.lower()} when calling this "
                             "endpoint and not assume strict server side validation.",
            code_implication="Add an explicit guard in the client layer and a regression check "
                             "so the behavior cannot silently reach downstream consumers.",
        ))
    return out


def _api_info(req: RequestObject) -> ApiAvailableInfo:
    return ApiAvailableInfo(
        service="open-meteo",
        endpoint=f"GET {req.endpoint_url}",
        purpose="Returns weather forecast data for a coordinate pair and selected variables.",
        auth="API key via X-API-Key header (auth edges skipped this pass).",
        documentation="No public documentation found during this recon pass.",
        documented_response_shape="Not documented.",
        documentation_gaps="No documentation was consulted in this pass.",
    )


def _render_ctx(req: RequestObject) -> render.RenderContext:
    raw = _fixture_findings()
    findings = render.normalize_findings(raw, [p.name for p in req.parameters])
    policies = _fixture_policies(findings)
    return render.RenderContext(
        base_url="https://api.open-meteo.com", endpoint="/v1/forecast",
        title_desc="open-meteo /v1/forecast", params=req.parameters,
        run_auth_edges=req.run_auth_edges,
        downstream="a backend service serving other applications",
        api_info=_api_info(req), findings=findings, policies=policies,
        ruled_out=["Coordinate passed as a single comma string was rejected with 422 — not supported."],
        dependency_params=["longitude"],
    )


# ─── Tests ───────────────────────────────────────────────────────────────

def t_determinism() -> tuple[bool, str]:
    req = _multi_param_request()
    a = plan.config_json(plan.build_probe_config(req))
    b = plan.config_json(plan.build_probe_config(req))
    return a == b, "probe_config.json byte-identical across two plans" if a == b else "config differs"


def t_scope_gate() -> tuple[bool, str]:
    def base(**over):
        raw = {"endpoint_url": "https://api.x.com/s", "auth_header_name": "X-API-Key",
               "auth_env_var": "K",
               "parameters": [{"name": "a", "tier1_values": ["1", "2", "3", "4", "5", "6"]}]}
        raw.update(over)
        return raw
    cases = {
        "path_param": base(endpoint_url="https://api.x.com/users/{id}/repos"),
        "query_in_url": base(endpoint_url="https://api.x.com/s?q=1"),
        "non_http_scheme": base(endpoint_url="ftp://api.x.com/s"),
        "non_get_method": base(method="POST"),
        "request_body": base(request_body={"a": 1}),
        "oauth": base(oauth={"flow": "client_credentials"}),
        "pagination": base(pagination={"cursor": "next"}),
        "multi_endpoint": base(endpoints=["/a", "/b"]),
        "semantic_pairs": base(semantic_pairs=[["start", "end"]]),
        "joint_value_space": base(joint_value_space=True),
        "multi_no_indep": base(parameters=[
            {"name": "a", "tier1_values": ["1", "2", "3", "4", "5", "6"]},
            {"name": "b", "tier1_values": ["1", "2", "3", "4", "5", "6"]}]),
        "auth_as_query": base(parameters=[
            {"name": "api_key", "tier1_values": ["1", "2", "3", "4", "5", "6"]}]),
    }
    for name, raw in cases.items():
        if intake(raw).ok:
            return False, f"out-of-scope case '{name}' was NOT rejected"
    return True, f"all {len(cases)} out-of-scope shapes rejected before any network call"


def t_budget_gate() -> tuple[bool, str]:
    req = _multi_param_request().model_copy(update={"max_calls": 5})
    allowed, planned, _ = budget.gate(req)
    if allowed:
        return False, f"budget gate allowed an over-budget run (planned={planned})"
    req2 = req.model_copy(update={"max_calls": planned})
    allowed2, _, _ = budget.gate(req2)
    return allowed2, f"over-budget blocked (planned={planned}); exact-budget allowed"


def t_missing_field_intake() -> tuple[bool, str]:
    res = intake({"endpoint_url": "https://api.x.com/s", "auth_header_name": "X-API-Key",
                  "parameters": [{"name": "a"}]})  # missing auth_env_var + tier1_values
    if res.ok or not res.questions:
        return False, "missing fields did not produce a question list"
    return True, f"returned {len(res.questions)} questions instead of guessing"


def t_evidence_ref_integrity() -> tuple[bool, str]:
    findings = render.normalize_findings(_fixture_findings(), ["latitude", "longitude"])
    ok, _ = validators.evidence_ref_integrity(findings, ["t5e_trailing_slash", "latitude_t1_60_5",
                                                          "latitude_t3_empty", "longitude_t3_unicode_cjk"])
    bad_ok, _ = validators.evidence_ref_integrity(findings, ["only_one_label"])
    return (ok and not bad_ok), "known labels pass; unknown label rejected"


def t_policy_mapping() -> tuple[bool, str]:
    findings = render.normalize_findings(_fixture_findings(), ["latitude", "longitude"])
    policies = _fixture_policies(findings)
    ok, _ = validators.policy_mapping(policies, findings)
    bad = policies + [Policy(finding_id="nonexistent.9", detection_signal="x",
                             policy_statement="y", code_implication="z")]
    bad_ok, _ = validators.policy_mapping(bad, findings)
    return (ok and not bad_ok), "valid mapping passes; dangling finding_id rejected"


def t_secret_hygiene() -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as d:
        run = Path(d)
        (run / "clean.md").write_text("no secrets here", encoding="utf-8")
        ok_clean, _ = validators.secret_scan(run, "SUPERSECRETKEY")
        (run / "leak.jsonl").write_text('{"k":"SUPERSECRETKEY"}', encoding="utf-8")
        ok_leak, offenders = validators.secret_scan(run, "SUPERSECRETKEY")
    return (ok_clean and not ok_leak and "leak.jsonl" in offenders), "clean passes; planted secret caught"


def t_redirect_safety() -> tuple[bool, str]:
    src = (KERNEL / "probe_runner.py").read_text(encoding="utf-8")
    ok = "_NoRedirectHandler" in src and "redirect_request" in src and "return None" in src
    return ok, "kernel installs a no-redirect handler"


def t_evidence_first() -> tuple[bool, str]:
    """Every body-bearing response is on disk as a .raw before analysis parses it."""
    import json as _json
    from api_recon_harness import evidence
    with tempfile.TemporaryDirectory() as d:
        run = Path(d)
        rec_full = {"label": "location_t1_london_0", "status": 200, "body_bytes_len": 412,
                    "body_sha256": "a" * 64, "body_preview": "{\"temp\": 12}", "parameter": "location",
                    "endpoint_level": False, "heuristic_hits": []}
        rec_empty = {"label": "location_t3_empty", "status": 200, "body_bytes_len": 0,
                     "parameter": "location", "endpoint_level": False, "heuristic_hits": []}
        (run / "probe_log.jsonl").write_text(
            _json.dumps(rec_full) + "\n" + _json.dumps(rec_empty) + "\n", encoding="utf-8")
        # The body-bearing response must already be captured as a .raw file.
        (run / "20260101_000000_location_t1_london_0.raw").write_text(
            "HTTP 200\n\n{\"temp\": 12}", encoding="utf-8")
        ev = evidence.analyze(run / "probe_log.jsonl", ["location"])
        raws = {p.name for p in run.glob("*.raw")}
        for label in ev.body_previews:
            if not any(name.endswith(f"{label}.raw") for name in raws):
                return False, f"no .raw on disk for body-bearing label '{label}'"
        ok = (ev.total_calls == 2 and "location_t3_empty" in ev.empty_responses
              and "location_t1_london_0" in ev.body_previews)
    return ok, "body-bearing response captured as .raw before analysis; empty body flagged"


def t_replay() -> tuple[bool, str]:
    """Re-running the plan from the same request reproduces the same run-dir shape."""
    req = _multi_param_request()
    with tempfile.TemporaryDirectory() as d:
        a = plan.write_probe_config(plan.build_probe_config(req), Path(d) / "probe_config.json")
        first = a.read_bytes()
        b = plan.write_probe_config(plan.build_probe_config(req), Path(d) / "probe_config.json")
        second = b.read_bytes()
        # And the written config re-validates through the (unchanged) kernel loader.
        import importlib.util
        spec = importlib.util.spec_from_file_location("_pr", KERNEL / "probe_runner.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cfg = mod.load_and_validate_config(str(b))
    ok = first == second and [p["name"] for p in cfg["parameters"]] == ["latitude", "longitude"]
    return ok, "config byte-identical on replay and re-validates through the kernel loader"


def t_server_routes() -> tuple[bool, str]:
    """The HTTP front door rejects out-of-scope in-band and parses findings."""
    from fastapi.testclient import TestClient
    from api_recon_harness.interfaces import server
    client = TestClient(server.app)
    # Out-of-scope POST /runs returns ok:false with a reason, starts no run thread.
    r = client.post("/runs", json={
        "endpoint_url": "https://api.x.com/users/{id}/repos",
        "auth_header_name": "X-API-Key", "auth_env_var": "DUMMY_API_KEY",
        "parameters": [{"name": "a", "tier1_values": ["1", "2", "3", "4", "5", "6"]}]})
    body = r.json()
    rejected = (r.status_code == 200 and body.get("ok") is False and bool(body.get("rejection")))
    # The SPA is served at /.
    served = client.get("/").status_code == 200
    # Findings parser extracts id/title/severity from rendered markdown.
    parsed = server._parse_findings(
        "### Finding C1: Trailing slash downgrade\n\n**Severity**: Major\n\n**Observation**: x")
    ok_parse = parsed == [{"id": "C1", "title": "Trailing slash downgrade", "severity": "Major"}]
    return (rejected and served and ok_parse), "POST /runs gates out-of-scope; SPA served; findings parsed"


def t_render_parity() -> tuple[bool, str]:
    req = _multi_param_request()
    ctx = _render_ctx(req)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        plan.write_probe_config(plan.build_probe_config(req), out / "probe_config.json")
        (out / "findings.md").write_text(render.render_findings_md(ctx), encoding="utf-8")
        (out / "policies.md").write_text(render.render_policies_md(ctx), encoding="utf-8")
        (out / "report.html").write_text(render.render_report_html(ctx), encoding="utf-8")
        ok, output = validators.verify_parity(out / "findings.md", out / "policies.md",
                                               out / "report.html", out / "probe_config.json")
    return ok, "verify_report_parity passed on rendered artifacts" if ok \
        else "parity FAILED:\n" + "\n".join(l for l in output.splitlines() if "FAIL" in l)


TESTS = [
    ("determinism", t_determinism),
    ("scope_gate", t_scope_gate),
    ("budget_gate", t_budget_gate),
    ("missing_field_intake", t_missing_field_intake),
    ("evidence_ref_integrity", t_evidence_ref_integrity),
    ("policy_mapping", t_policy_mapping),
    ("secret_hygiene", t_secret_hygiene),
    ("redirect_safety", t_redirect_safety),
    ("evidence_first", t_evidence_first),
    ("replay", t_replay),
    ("server_routes", t_server_routes),
    ("render_parity", t_render_parity),
]


def run_all() -> bool:
    print("API-recon harness self-tests")
    print("=" * 60)
    all_pass = True
    for name, fn in TESTS:
        try:
            ok, detail = fn()
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"EXCEPTION: {type(e).__name__}: {e}"
        all_pass &= ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} — {detail}")
    print("=" * 60)
    print("  All passed." if all_pass else "  FAILURES present.")
    return all_pass


if __name__ == "__main__":
    import sys
    sys.exit(0 if run_all() else 1)
