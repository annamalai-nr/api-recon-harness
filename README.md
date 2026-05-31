# API-Recon Harness

A deterministic control plane around the unchanged `get-api-recon` probe kernel.
Turns the API-recon *skill* (LLM owns orchestration at runtime) into a *harness*
(deterministic code owns orchestration; the LLM is a bounded suggestion engine).
Same empirical output — probe a black-box GET endpoint, capture evidence, derive
findings and downstream policies — but reproducible, budget-safe, and verifiable.

Spec & design notes: [`docs/spec.md`](docs/spec.md),
[`docs/harness_engineering_note.md`](docs/harness_engineering_note.md),
[`docs/spec_driven_development_note.md`](docs/spec_driven_development_note.md).

## Setup

```bash
# Python 3.11+ (developed on 3.12). Use a fresh env or an existing one.
conda activate elyosai            # or: conda create -n api_recon python=3.12 && conda activate api_recon
pip install -e .                  # installs deps + the `api-recon` / `api-recon-web` console scripts

# Provide keys in .env at the project root:
#   OPENAI_API_KEY=...            (or another provider from allowed_models.csv)
#   ELYOS_API_KEY=...             (only if probing the Elyos endpoint)
# Public, no-auth endpoints need no key (the harness uses a dummy for DUMMY_API_KEY).
```

## Architecture

One **FastAPI process** (`server.py`) is the front door: it serves a single-page
app and exposes a tiny API. The browser is where you **give inputs, watch
progress, and inspect output** — three views: **Input → Progress → Results**.

```
  Browser SPA (ui/index.html)            FastAPI (server.py)            Deterministic core (run.py)
  ── give inputs ───────────▶  POST /runs  ──(intake gate)──▶  background thread:
  ── poll phase/status ─────▶  GET  /runs/{id}                  intake→plan→budget→execute→
  ── inspect report ────────▶  GET  /runs/{id}/report           evidence→llm→render→verify
  ── draft from docs ───────▶  POST /draft                      writes a run directory on disk
```

The server is **just transport** — it never touches the pipeline logic. Runs are
synchronous Python executed in a background thread; the SPA polls for the live
phase. `python -m api_recon_harness --serve`, then open the browser.

## Control boundary

**Deterministic Python owns:** scope validation, URL construction, redirect
policy, retry/throttle policy (in the kernel), the planned-call budget gate,
probe order, raw-evidence capture, `probe_log.jsonl` parsing, parity + secret
scans, run status, and **all report formatting** (Major-first sort, canonical
finding ids, `**Parameters**`-last field order, scope header, dependency banner).

**The LLM owns only bounded judgment** (`llm_steps.py`): turn structured
evidence into finding prose, assign severity, consolidate cross-parameter
findings, and derive downstream policies. Each is a single constrained
completion with schema-validated JSON output. Untrusted API bodies reach the
model only through the `envelope`. Because formatting is deterministic,
`verify_report_parity.py` passes by construction.

## Layout

```
api_recon_harness/
  models.py            all Pydantic data models (request, evidence, findings, LLM envelopes, status)
  paths.py             filesystem constants — single source of truth (REPO_ROOT, KERNEL_DIR, RUNS_DIR…)
  config.yaml          model selection (config-driven, per north_stars)
  llm_client.py        the only LiteLLM call — complete_json(system, user)
  prompts/             prompt text + user-message builders, one module per step
    findings.py · policies.py · api_info.py · draft.py
  envelope.py          untrusted-body wrapper for any LLM context
  intake.py            scope gate + missing-field question list (no network)
  budget.py            planned-call calculator + gate (mirrors the kernel plan)
  plan.py              RequestObject → byte-stable probe_config.json
  execute.py           optional preflight + run the vendored kernel; count actual calls
  evidence.py          parse probe_log.jsonl → structured candidate signals
  llm_steps.py         bounded steps (findings / policies / api-info) — orchestration only
  draft.py             docs → candidate-config drafter (the optional agent); intake owns the verdict
  render.py            deterministic findings.md / policies.md / report.html
  validators.py        parity + secret + evidence-ref + policy-map review gate
  run.py               orchestrator (intake → plan → budget → execute → analyze → LLM → render → verify)
  interfaces/
    cli.py             argparse CLI entry (python -m api_recon_harness)
    server.py          FastAPI front door: /runs, /runs/{id}, /runs/{id}/report, /draft; serves the SPA
  frontend/
    index.html         single-page app: Input → Progress → Results (per-finding approve/reject)
  kernel/              probe_runner.py + verify_report_parity.py — vendored unchanged (v3.1)
  tests/run_tests.py   12 offline self-tests (--validate)
```

This mirrors `backend/chat/` and the `smart_research` conventions: data models in
`models.py`, prompts in a `prompts/` folder, UI interfaces in `interfaces/`, and the
JS web UI in `frontend/`. `report.html` and `frontend/index.html` share a light-mode
"forensic dossier" design (Fraunces display + IBM Plex Sans/Mono; crimson=Major,
slate=Minor). The report's look is genuine harness output — `render.py` emits the
self-contained CSS — and every parity-critical string is preserved, so
`verify_report_parity.py` still passes.

## Usage — two distinct entry points

```bash
conda activate elyosai

# Web app (browser-driven): give inputs → watch progress → inspect output
python -m api_recon_harness.interfaces.server      # → http://127.0.0.1:8000
#   (console script: `api-recon-web`)

# Headless CLI (scripting / CI)
python -m api_recon_harness --request <req.json>             # full run
python -m api_recon_harness --request <req.json> --plan-only # plan + budget, no network
python -m api_recon_harness --request <req.json> --no-llm    # probes + evidence only
python -m api_recon_harness --request <partial.json> --draft # docs→config agent, then gate
python -m api_recon_harness --validate                       # 12 offline self-tests
python -m api_recon_harness --evals                          # live LLM-step evals
#   (console script: `api-recon`)
```

In the web app, type the endpoint + parameters (or "Draft from docs"), hit **Run**,
watch the live phase, and inspect the report. Public no-auth endpoints work out of
the box (the server provides a dummy header value; you never type a key). For the
Elyos run set the auth env var to `ELYOS_API_KEY` (read from `.env`).

**Every run — web or CLI — writes one directory `./outputs/api_recon/runs/<run_id>/`**:
`probe_config.json`, `*.raw`, `probe_log.jsonl`, `run_state.json` (live phase),
`findings.md`, `policies.md`, `report.html`, `status.json` (final). The run is
replayable from its own `probe_config.json`. (`--plan-only` is a no-run diagnostic
and writes `probe_config.json` under `./outputs/api_recon/<endpoint_slug>/`.)

### Example requests (`examples/`)

| File | Shape | Auth |
|---|---|---|
| `request_jsonplaceholder.json` | single-param (`userId`) | none (public) |
| `request_openmeteo.json` | joint-required multi-param (`latitude`/`longitude` + companions) | none (public) |
| `request_weather.json` | single-param (`location`) | Elyos `ELYOS_API_KEY` |

Public, no-auth endpoints use a dummy header + `run_auth_edges: false`; no key is
needed (the harness supplies a dummy value for `DUMMY_API_KEY`):

```bash
python -m api_recon_harness --request api_recon_harness/examples/request_openmeteo.json
```

Each invocation writes a real run directory under `outputs/api_recon/runs/<run_id>/`
(gitignored): LLM-written `findings.md`/`policies.md`, the deterministically rendered
`report.html`, and `status.json` — every run is parity-verified before it is marked
`complete`. These examples have been run for real against the live public endpoints
and the Elyos `/weather` API.

## The docs→config agent (`draft.py`)

The spec's one optional tool-using step. Given an endpoint + a `docs_url` but no
hand-written `parameters`, it fetches the docs (envelope-escaped — remote content
is untrusted), drafts a candidate parameter set via one constrained completion,
and then **the deterministic `intake` gate owns the verdict** — a drafted config
is never trusted on its own. Run it with `--draft`.

It is the bounded-completion form of the spec's agent; swapping in LangChain v1
`create_agent` + `ToolCallLimitMiddleware` for multi-tool doc exploration is a
drop-in replacement for `draft._draft_parameters` (the intake validator stays the
authority either way). The lighter form avoids pulling `langchain>=1.0` /
`langgraph>=1.0` into an otherwise stdlib-plus-Pydantic harness.

## Design notes

- **Distinct entry points.** The headless CLI (`interfaces/cli.py`) and the web app
  (`interfaces/server.py`) are separate; `__main__.py` delegates to the CLI. Console
  scripts: `api-recon` and `api-recon-web`.
- **The server is stateless.** There is no in-memory run registry — a run's identity
  is its directory, `run.py` is the sole writer of `run_state.json`/`status.json`, and
  every `GET` reads the run directory from disk. A restarted server still reports any
  past run. (If the process dies *mid-run* the in-process thread stops and that run's
  `run_state.json` is left at its last phase — a known limitation of in-process
  execution, not of the reporting path.)
- **One run-directory policy.** Web and CLI both write `outputs/api_recon/runs/<run_id>/`.
- **Config is loaded lazily** (`llm_client._cfg`, `@lru_cache`), not at import time.
- **The deterministic core is unchanged** across all of this; the LLM transport
  (`llm_client.py`) and prompts (`prompts/`) are isolated, and the bounded LLM steps
  have their own live eval harness (`evals/`, `--evals`) alongside the 12 offline tests.
- **No keys in the browser.** The server reads keys from its own env/`.env`; the page
  only carries the env-var *name*. Public no-auth endpoints get a dummy value.
