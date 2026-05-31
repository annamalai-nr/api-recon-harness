# API-Recon Harness

**Turn black-box API reconnaissance into a reproducible, budget-safe, verifiable pipeline — with the LLM on a short leash.**

Point it at an unfamiliar **GET** endpoint and it probes the endpoint's behavior
(schema variability, caching, throttling, input/protocol edges, prompt-injection
bait), then writes a findings report and downstream-specific engineering policies.
Deterministic code owns the orchestration; the language model is confined to
narrow, schema-validated judgment steps. Same empirical output as an
"agent-decides-everything" approach — but **reproducible, cost-bounded, and
auditable**.

It's built around the idea of a *harness* rather than a *skill*: a framework
tells a developer how to structure an app; a harness tells the agent how to
operate safely. Here, everything that *must* be correct is ordinary Python you
can unit-test; only the parts that genuinely need judgment are delegated to the
model.

## Highlights

- **Deterministic control plane.** Scope-gating, the call budget, probe order,
  evidence capture, report formatting, and a parity/secret/evidence-reference
  verification gate are all plain, tested code.
- **The LLM is a bounded suggestion engine.** It only writes finding prose,
  assigns severity, consolidates cross-parameter findings, derives policies, and
  (optionally) drafts a probe config from docs — each a single schema-validated
  completion. Untrusted API bodies reach it only through an escaping envelope.
- **Reports verified by construction.** The model emits structured records; code
  owns all formatting, so a Markdown↔HTML parity verifier passes every time.
- **Two entry points:** a browser web app (give inputs → watch live progress →
  inspect the report) and a headless CLI for scripting/CI.
- **Reproducible runs.** Every run is one directory on disk and replayable from
  its own frozen `probe_config.json`. The web server is stateless.
- **Tested:** 12 offline self-tests + 4 live LLM-step evals (incl. an
  injection-resistance check).

## Quickstart

```bash
# Python 3.11+ (developed on 3.12)
conda create -n api_recon python=3.12 -y && conda activate api_recon   # or any venv
pip install -e .                 # installs deps + the api-recon / api-recon-web console scripts

# Put an LLM key in .env at the project root (any text model from allowed_models.csv):
#   OPENAI_API_KEY=...
```

**Web app** — give inputs, watch progress, inspect output:

```bash
python -m api_recon_harness.interfaces.server      # → http://127.0.0.1:8000   (or: api-recon-web)
```

**CLI** — run a bundled public example end-to-end (no API key for the target needed):

```bash
python -m api_recon_harness --request api_recon_harness/examples/request_openmeteo.json   # (or: api-recon)
```

That probes `https://api.open-meteo.com/v1/forecast`, then writes an LLM-authored
`findings.md`/`policies.md`, a styled `report.html`, and a `status.json` to
`outputs/api_recon/runs/<run_id>/` — parity-verified before the run is marked `complete`.

## How it works

A single **FastAPI process** is the front door: it serves a single-page app and a
tiny API. The browser is where you **give inputs, watch progress, and inspect
output** — three views: **Input → Progress → Results**.

```
  Browser SPA (frontend/index.html)      FastAPI (interfaces/server.py)    Deterministic core (run.py)
  ── give inputs ───────────▶  POST /runs  ──(intake gate)──▶  background thread:
  ── poll phase/status ─────▶  GET  /runs/{id}                  intake→plan→budget→execute→
  ── inspect report ────────▶  GET  /runs/{id}/report           evidence→llm→render→verify
  ── draft from docs ───────▶  POST /draft                      writes a run directory on disk
```

The server is **just transport** — it never touches the pipeline logic. Runs are
synchronous Python in a background thread; the page polls for the live phase.

### Control boundary

**Deterministic Python owns:** scope validation, URL construction, redirect
policy, retry/throttle policy, the planned-call budget gate, probe order,
raw-evidence capture, log parsing, parity + secret scans, run status, and **all
report formatting** (Major-first sort, canonical finding ids, `**Parameters**`-last
field order, scope header, dependency banner).

**The LLM owns only bounded judgment** (`llm_steps.py`): turning structured
evidence into finding prose, severity, cross-parameter consolidation, and
downstream policies — each a single constrained completion with schema-validated
JSON. Untrusted bodies reach the model only through the `envelope`. Because
formatting is deterministic, `verify_report_parity.py` passes by construction.

## CLI

```bash
python -m api_recon_harness --request <req.json>             # full run
python -m api_recon_harness --request <req.json> --plan-only # plan + budget, no network
python -m api_recon_harness --request <req.json> --no-llm    # probes + evidence only
python -m api_recon_harness --request <partial.json> --draft # docs→config agent, then gate
python -m api_recon_harness --validate                       # 12 offline self-tests
python -m api_recon_harness --evals                          # live LLM-step evals
```

A request is a small JSON object (endpoint URL, auth header name + env-var name,
and the query parameters to probe — each with 6–10 baseline values and optional
pinned companions). See `api_recon_harness/examples/` for single-parameter,
joint-required multi-parameter, and header-authed shapes. Out-of-scope shapes
(non-GET, path-param-only, OAuth, pagination, secrets-as-query, …) are declined by
the intake gate before any network call.

## Layout

Backend and frontend are separate top-level folders: the `api_recon_harness/`
Python package is the backend; `frontend/` holds the single-page web UI. The
server reads `frontend/index.html` from disk (a project-root resource, like
`outputs/` and `.env`), so the package stays pure Python.

```
api_recon_harness/       BACKEND — Python package (no UI inside)
  models.py            all Pydantic data models (request, evidence, findings, LLM envelopes, status)
  paths.py             filesystem constants — single source of truth (PROJECT_ROOT, KERNEL_DIR, RUNS_DIR…)
  config.yaml          model selection (config-driven)
  llm_client.py        the only LLM call — complete_json(system, user) via LiteLLM
  prompts/             prompt text + user-message builders, one module per step
  envelope.py          untrusted-body wrapper for any LLM context
  intake.py            scope gate + missing-field question list (no network)
  budget.py            planned-call calculator + gate
  plan.py              RequestObject → byte-stable probe_config.json
  execute.py           optional preflight + run the vendored kernel; count actual calls
  evidence.py          parse probe_log.jsonl → structured candidate signals
  llm_steps.py         bounded steps (findings / policies / api-info) — orchestration only
  draft.py             docs → candidate-config drafter; the intake gate owns the verdict
  render.py            deterministic findings.md / policies.md / report.html
  validators.py        parity + secret + evidence-ref + policy-map review gate
  run.py               orchestrator (intake → plan → budget → execute → analyze → LLM → render → verify)
  interfaces/cli.py    headless CLI entry
  interfaces/server.py FastAPI front door (serves the frontend + the JSON API)
  kernel/              GET probe runner + parity verifier — reused verbatim, never edited
  evals/run_evals.py   live fixture-based LLM-step evals (--evals)
  tests/run_tests.py   12 offline self-tests (--validate)

frontend/                FRONTEND — web UI (no Python)
  index.html           single-page app: Input → Progress → Results (per-finding approve/reject)
```

Conventional layout: data models in `models.py`, prompts in `prompts/`, UI
interfaces (the FastAPI server + CLI) in `interfaces/`, the JS web UI in the
top-level `frontend/`. `report.html` and the
SPA share a light-mode "forensic dossier" design (Fraunces + IBM Plex; crimson =
Major, slate = Minor); the report's CSS is emitted by `render.py`, so it's genuine
harness output and still passes the parity verifier.

## The docs→config agent

Given an endpoint + a docs URL but no hand-written parameters, `--draft` fetches
the docs (envelope-escaped — remote content is untrusted), drafts a candidate
parameter set via one constrained completion, and then **the deterministic intake
gate owns the verdict** — a drafted config is never trusted on its own. It's the
bounded-completion form of a tool-using agent; a LangChain `create_agent` +
tool-call-limit middleware would drop in as a replacement for the drafting step,
with the validator still the authority.

## Testing

```bash
python -m api_recon_harness --validate   # 12 deterministic, offline, no network/LLM
python -m api_recon_harness --evals      # 4 live LLM-step evals (needs an API key)
```

Offline tests cover determinism, the scope gate (12 out-of-scope shapes), the
budget gate, evidence-first capture, secret hygiene, redirect safety,
evidence-reference integrity, policy mapping, the render→parity contract, and the
server routes. The live evals cover findings faithfulness + injection resistance,
severity classification, cross-parameter consolidation, and policy mapping.

## Design notes

- **Stateless server.** A run's identity is its directory; `run.py` is the sole
  writer of `run_state.json`/`status.json`, and every `GET` reads from disk, so a
  restarted server still reports past runs. (If the process dies *mid-run*, that
  run's state is left at its last phase — a limit of in-process execution.)
- **One run-directory policy.** Web and CLI both write `outputs/api_recon/runs/<run_id>/`.
- **Config loaded lazily**, not at import time.
- **Model selection is config-driven** (`config.yaml`); switching providers needs no code change.
- **No keys in the browser.** The server reads keys from its own `.env`; the page
  carries only the env-var *name*. Public no-auth endpoints get a dummy value.

## Background & license

Built as an engineering exercise around a black-box GET-API recon workflow, then
generalized into this standalone tool. The original design spec and notes are
archived under [`harness_engineering/`](harness_engineering/). Conventions live in
[`north_stars.md`](north_stars.md) and [`llm_rules.md`](llm_rules.md).

No license has been chosen yet — all rights reserved by default. Open an issue if
you'd like to use it.
