"""CLI interface for the harness (headless / scripting / CI).

The browser-driven web app is a separate entry point —
`python -m api_recon_harness.interfaces.server` (or `api-recon-web`).

  --request PATH   JSON RequestObject (spec §5)
  --no-llm         run probes + evidence only; skip findings/policies/report
  --plan-only      validate + plan + budget; write probe_config.json, no network
  --draft          draft `parameters` from `docs_url` in the request, then gate
  --validate       run the harness self-tests and exit
  --evals          run the fixture-based LLM-step evals (live; needs an API key)
"""

import argparse
import json
import sys
from pathlib import Path

from api_recon_harness import budget, plan
from api_recon_harness.intake import intake
from api_recon_harness.paths import ENV_PATH


def _plan_only(raw: dict) -> int:
    result = intake(raw)
    if not result.ok:
        msg = "; ".join(result.questions) if result.questions else result.rejection
        print(f"REJECTED / INCOMPLETE: {msg}", file=sys.stderr)
        return 2
    req = result.request
    allowed, planned, msg = budget.gate(req)
    cfg = plan.build_probe_config(req)
    out = Path(cfg.output_dir)
    plan.write_probe_config(cfg, out / "probe_config.json")
    print(f"Planned calls: {planned}  ({'OK' if allowed else 'OVER BUDGET'})")
    print(f"Budget: {msg}")
    print(f"Wrote {out / 'probe_config.json'}")
    return 0 if allowed else 2


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(ENV_PATH)
    except Exception:  # noqa: BLE001
        pass


def main() -> None:
    _load_env()
    parser = argparse.ArgumentParser(description="API-recon harness")
    parser.add_argument("--request", help="Path to a JSON RequestObject")
    parser.add_argument("--no-llm", action="store_true", help="Probes + evidence only")
    parser.add_argument("--plan-only", action="store_true", help="Validate + plan, no network")
    parser.add_argument("--draft", action="store_true",
                        help="Draft parameters from docs_url, then gate (no probes)")
    parser.add_argument("--validate", action="store_true", help="Run harness self-tests")
    parser.add_argument("--evals", action="store_true", help="Run live LLM-step evals")
    args = parser.parse_args()

    if args.validate:
        from api_recon_harness.tests.run_tests import run_all
        sys.exit(0 if run_all() else 1)

    if args.evals:
        from api_recon_harness.evals.run_evals import run_all as run_evals
        sys.exit(0 if run_evals() else 1)

    if not args.request:
        parser.error("--request is required (use --validate, --evals, or the web app)")
    raw = json.loads(Path(args.request).read_text(encoding="utf-8"))

    if args.draft:
        from api_recon_harness.draft import draft_request_from_docs
        from api_recon_harness.run import fetch_docs
        completed, verdict = draft_request_from_docs(raw, fetch_docs(raw.get("docs_url")))
        print(json.dumps(completed, indent=2))
        if verdict.ok:
            print("\nIntake verdict: OK — drafted config passed the scope gate.", file=sys.stderr)
            sys.exit(0)
        why = "; ".join(verdict.questions) if verdict.questions else verdict.rejection
        print(f"\nIntake verdict: NOT OK — {why}", file=sys.stderr)
        sys.exit(2)

    if args.plan_only:
        sys.exit(_plan_only(raw))

    from api_recon_harness.run import run_recon
    status = run_recon(raw, run_llm=not args.no_llm)
    print(json.dumps(status.model_dump(), indent=2))
    sys.exit(0 if status.state == "complete" else 1)
