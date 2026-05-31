"""Web interface — FastAPI front door over the deterministic core (run.py).

Stateless: there is no in-memory run registry. A run's identity is its directory
under `outputs/api_recon/runs/<run_id>/`; the server seeds `run_state.json`, runs
`run_recon` in a background thread (which is the sole writer of state), and every
`GET` reads the run directory from disk. A fresh server can report any past run.

Distinct entry point from the CLI: `python -m api_recon_harness.interfaces.server`
or the `api-recon-web` console script.
"""

import argparse
import json
import re
import threading
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from api_recon_harness.intake import intake
from api_recon_harness.paths import FRONTEND_DIR, RUNS_DIR
from api_recon_harness.run import RUN_STATE_FILE, fetch_docs, new_run_id, run_recon, write_run_state

UI = FRONTEND_DIR / "index.html"

app = FastAPI(title="API-recon harness")

# (Public no-auth runs are handled in run._load_api_key, which supplies a dummy
#  value for DUMMY_API_KEY so the user never types a key into the browser.)

_FINDING_RE = re.compile(r"^#{3,4}\s+Finding\s+([\w.:-]+):\s*(.+)$", re.MULTILINE)
_SEV_RE = re.compile(r"\*\*Severity\*\*:\s*(Major|Minor)")


def _parse_findings(md: str) -> list[dict]:
    blocks = re.split(r"^#{3,4}\s+Finding\s+", md, flags=re.MULTILINE)
    out = []
    for fid, title in _FINDING_RE.findall(md):
        block = next((b for b in blocks if b.startswith(fid + ":")), "")
        sev = (_SEV_RE.search(block) or [None, "Minor"])[1]
        out.append({"id": fid, "title": title.strip(), "severity": sev})
    return out


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _elapsed(started_at: str | None) -> float:
    if not started_at:
        return 0.0
    try:
        return round((datetime.now() - datetime.fromisoformat(started_at)).total_seconds(), 1)
    except ValueError:
        return 0.0


@app.get("/")
def index() -> FileResponse:
    return FileResponse(UI)


@app.post("/runs")
def create_run(req: dict) -> JSONResponse:
    verdict = intake(req)                       # fast, no network — fail early in-band
    if not verdict.ok:
        return JSONResponse({"ok": False, "questions": verdict.questions,
                             "rejection": verdict.rejection})
    run_id = new_run_id(req)
    out = RUNS_DIR / run_id
    out.mkdir(parents=True, exist_ok=True)
    write_run_state(out, run_id=run_id, state="running", phase="queued",
                    started_at=datetime.now().isoformat(timespec="seconds"))
    raw = dict(req, output_dir=str(out))
    threading.Thread(target=run_recon, kwargs={"raw_request": raw, "run_id": run_id},
                     daemon=True).start()
    return JSONResponse({"ok": True, "run_id": run_id})


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> JSONResponse:
    out = RUNS_DIR / run_id
    state = _read_json(out / RUN_STATE_FILE)
    status = _read_json(out / "status.json")
    if state is None and status is None:
        return JSONResponse({"error": "unknown run"}, status_code=404)
    state = state or {}
    body = {"run_id": run_id, "state": (status or state).get("state"),
            "phase": state.get("phase"), "elapsed_s": _elapsed(state.get("started_at")),
            "status": status}
    findings_md = out / "findings.md"
    if findings_md.exists():
        body["findings"] = _parse_findings(findings_md.read_text(encoding="utf-8"))
    return JSONResponse(body)


@app.get("/runs/{run_id}/report")
def get_report(run_id: str):
    report = RUNS_DIR / run_id / "report.html"
    if not report.exists():
        return JSONResponse({"error": "report not ready"}, status_code=404)
    return FileResponse(report)


@app.post("/draft")
def draft(req: dict) -> JSONResponse:
    from api_recon_harness.draft import draft_request_from_docs
    completed, verdict = draft_request_from_docs(req, fetch_docs(req.get("docs_url")))
    return JSONResponse({"ok": verdict.ok, "request": completed,
                         "questions": verdict.questions, "rejection": verdict.rejection})


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn
    print(f"API-recon harness UI → http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")


def main() -> None:
    parser = argparse.ArgumentParser(description="API-recon harness web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    serve(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
