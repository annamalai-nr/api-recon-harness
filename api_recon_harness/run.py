"""Orchestrator: the deterministic outer loop (intake → plan → budget → execute
→ analyze → bounded-LLM → render → verify).

Each run owns a directory under `outputs/api_recon/runs/<run_id>/` and is the
single writer of its state: `run_state.json` (live phase) and `status.json`
(final). Both the CLI and the web server go through here, so the run-directory
scheme is identical regardless of entry point, and the server can stay a pure
reader of the run directory (no in-memory registry).
"""

import json
import os
import uuid
from datetime import datetime
from pathlib import Path

from api_recon_harness import budget, evidence, plan, render, validators
from api_recon_harness.execute import count_calls, preflight, run_probe
from api_recon_harness.intake import intake
from api_recon_harness.models import ProbeConfig, RequestObject, RunStatus
from api_recon_harness.paths import ENV_PATH, RUNS_DIR

RUN_STATE_FILE = "run_state.json"


# ─── run identity + on-disk state (shared by CLI and server) ─────────────

def new_run_id(raw_request: dict) -> str:
    slug = plan.endpoint_slug(raw_request.get("endpoint_url", "") or "endpoint")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{slug}_{stamp}_{uuid.uuid4().hex[:4]}"


def write_run_state(output_dir: Path, **fields) -> None:
    """Merge fields into <output_dir>/run_state.json (the live phase record)."""
    path = output_dir / RUN_STATE_FILE
    state = {}
    if path.exists():
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            state = {}
    state.update(fields)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ─── helpers ─────────────────────────────────────────────────────────────

def _load_api_key(env_var: str) -> str | None:
    try:
        from dotenv import load_dotenv
        load_dotenv(ENV_PATH)
    except Exception:  # noqa: BLE001
        pass
    key = os.environ.get(env_var)
    # Public, no-auth endpoints use the conventional DUMMY_API_KEY; supply a
    # harmless placeholder so keyless public runs work from CLI and web alike.
    # Real key names still fail loudly when unset.
    if not key and env_var == "DUMMY_API_KEY":
        return "DUMMY_KEY_UNUSED_PUBLIC"
    return key


def fetch_docs(docs_url: str | None) -> str | None:
    if not docs_url:
        return None
    try:
        import httpx
        return httpx.get(docs_url, timeout=15, follow_redirects=True).text
    except Exception:  # noqa: BLE001
        return None


def _resolve_downstream(req: RequestObject) -> str:
    if req.downstream_context:
        return req.downstream_context
    return ("informed guess — a generic backend client of this endpoint "
            "(no downstream specified; correct this in the request to refine policies)")


def _write_artifacts(ctx: render.RenderContext, out: Path) -> None:
    (out / "findings.md").write_text(render.render_findings_md(ctx), encoding="utf-8")
    (out / "policies.md").write_text(render.render_policies_md(ctx), encoding="utf-8")
    (out / "report.html").write_text(render.render_report_html(ctx), encoding="utf-8")


def _finish(out: Path, status: RunStatus, progress=None) -> RunStatus:
    """Persist the final status + run_state and return it."""
    (out / "status.json").write_text(status.model_dump_json(indent=2), encoding="utf-8")
    write_run_state(out, state=status.state, phase="done")
    if progress:
        progress("done")
    return status


# ─── orchestrator ────────────────────────────────────────────────────────

def run_recon(raw_request: dict, *, run_llm: bool = True, progress=None,
              run_id: str | None = None) -> RunStatus:
    run_id = run_id or new_run_id(raw_request)
    out = Path(raw_request.get("output_dir") or (RUNS_DIR / run_id))
    out.mkdir(parents=True, exist_ok=True)
    started = datetime.now().isoformat(timespec="seconds")
    write_run_state(out, run_id=run_id, state="running", phase="validating request",
                    started_at=started)

    def step(msg: str) -> None:
        write_run_state(out, phase=msg)
        if progress:
            progress(msg)
        else:
            print(f"  · {msg}")

    def fail(detail: str, planned: int = 0) -> RunStatus:
        ended = datetime.now().isoformat(timespec="seconds")
        return _finish(out, RunStatus(run_id=run_id, state="error", expected_calls=planned,
                                      actual_calls=0, exit_code=2, started_at=started,
                                      ended_at=ended, detail=detail), progress)

    result = intake(raw_request)
    if not result.ok:
        return fail("; ".join(result.questions) if result.questions
                    else (result.rejection or "intake failed"))
    req = result.request.model_copy(update={"output_dir": str(out)})

    allowed, planned, msg = budget.gate(req)
    if not allowed:
        return fail(msg, planned=planned)

    api_key = _load_api_key(req.auth_env_var)
    if not api_key:
        return fail(f"API key not found in env var {req.auth_env_var} (load it via .env).", planned)

    cfg: ProbeConfig = plan.build_probe_config(req)
    config_path = out / "probe_config.json"
    plan.write_probe_config(cfg, config_path)
    step(f"planned {planned} probes")

    if req.run_preflight:
        step("preflight")
        print(f"  preflight: {preflight(cfg, api_key)}")

    step(f"probing {cfg.base_url}{cfg.endpoint}")
    exit_code, _probe_started, _probe_ended, _ = run_probe(config_path, api_key, req.auth_env_var)
    log_file = out / "probe_log.jsonl"
    actual = count_calls(log_file)
    step("analyzing evidence")
    ev = evidence.analyze(log_file, [p["name"] for p in cfg.parameters])

    state = "complete" if exit_code == 0 else "error"
    detail = "probe complete" if exit_code == 0 else "kernel runner failed"

    if run_llm and exit_code == 0:
        from api_recon_harness import llm_steps
        step("writing findings (LLM)")
        api_info = llm_steps.build_api_info(req, fetch_docs(req.docs_url))
        raw_findings = llm_steps.generate_findings(ev, req.parameters)
        findings = render.normalize_findings(raw_findings, [p.name for p in req.parameters])
        downstream = _resolve_downstream(req)
        step("deriving policies (LLM)")
        policies = llm_steps.generate_policies(findings, downstream)
        ctx = render.RenderContext(
            base_url=cfg.base_url, endpoint=cfg.endpoint,
            title_desc=f"{api_info.service} {cfg.endpoint}",
            params=req.parameters, run_auth_edges=req.run_auth_edges,
            downstream=downstream, api_info=api_info, findings=findings,
            policies=policies, ruled_out=[], dependency_params=[d.parameter for d in ev.dependencies],
        )
        step("rendering report")
        _write_artifacts(ctx, out)
        step("verifying report parity + secrets")
        state, detail = validators.review(out, findings, policies, ev.labels, api_key)

    artifacts = [str(p.relative_to(out)) for p in sorted(out.glob("*"))
                 if p.suffix in {".json", ".jsonl", ".md", ".html"}]
    ended = datetime.now().isoformat(timespec="seconds")
    return _finish(out, RunStatus(run_id=run_id, state=state, expected_calls=planned,
                                  actual_calls=actual, exit_code=exit_code, started_at=started,
                                  ended_at=ended, artifacts=artifacts, detail=detail), progress)
