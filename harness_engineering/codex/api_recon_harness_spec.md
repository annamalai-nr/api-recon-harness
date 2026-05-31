# Spec: Minimal API Recon Harness

## Purpose

Build a small harness around `get-api-recon-v3.1` so an engineer can probe one unfamiliar GET endpoint, preserve evidence, and turn the results into findings and downstream policies. The implementation should stay prototype-friendly: Python does the real work, TypeScript gives a simple review surface, and the existing `probe_runner.py` remains the execution engine.

The north star is simplicity. Do not build a framework, workflow engine, database, web server, or multi-agent system unless a later requirement proves it is needed.

## Scope

In scope:

- One GET endpoint.
- Query parameters probed independently.
- Optional pinned companions for joint-required parameters.
- Header/API-key auth loaded from an environment variable.
- Probe execution through the existing `probe_runner.py`.
- Markdown findings, downstream policies, and an HTML report.
- A lightweight TypeScript reviewer for inspecting the run output.

Out of scope:

- Non-GET methods, request bodies, OAuth, pagination, destructive calls, and multi-endpoint orchestration.
- Joint value-space probing or semantic-pair probing.
- Auth credentials in query strings or pinned companions.
- Long-running background workers, queues, databases, or hosted dashboards.
- Passing raw untrusted API bodies directly into LLM context.

## Implementation Shape

### Python

Implement one main script, `api_recon_harness.py`, plus at most one small helper file if the script becomes hard to read.

The Python script should:

1. Read a user-authored `request.json`.
2. Validate scope before any network call.
3. Convert the request into `probe_config.json`.
4. Estimate expected call count and stop if it exceeds `max_calls`.
5. Run the existing `probe_runner.py` as a subprocess.
6. Read `probe_log.jsonl` and produce a concise `run_summary.json`.
7. Help generate or validate `findings.md`, `policies.md`, and `report.html`.
8. Run the existing `verify_report_parity.py`.

Keep the code synchronous. Prefer the standard library. Use clear errors instead of fallbacks. Keep helpers at module scope and give each helper one job.

### TypeScript

Implement a small local reviewer, not a full app platform.

The TypeScript side should read files from one completed run directory and display:

- Target endpoint and parameters.
- Probe budget and actual call count.
- Status-code summary.
- Redirect/security flags.
- Injection heuristic hits.
- Links to `findings.md`, `policies.md`, `report.html`, and raw evidence.

It does not own probe logic. It does not call the API. It does not need a backend unless plain file loading is impossible for the chosen UI approach.

## Input Contract

`request.json` contains:

- `base_url`
- `endpoint`
- `auth_header`
- `auth_env_var`
- `parameters`
- `tier1_values` per parameter
- optional `pinned_companions`
- optional `shared_tier3_edges`
- optional `tier4_adversarial`
- optional `downstream_context`
- `run_auth_edges`
- `timeout_s`
- `max_calls`
- `output_dir`

For more than one parameter, the request must include `parameters_independence_declared: true`.

## Output Directory

Each run writes one directory:

- `request.json`
- `probe_config.json`
- `probe_log.jsonl`
- per-call `.raw` files from the runner
- `run_summary.json`
- `findings.md`
- `policies.md`
- `report.html`

Do not add more generated files unless they remove real manual work.

## Validation Rules

Before running probes, Python must reject:

- endpoint paths containing `{...}` placeholders
- unsupported methods or request-body fields
- missing parameters or empty Tier 1 values
- multi-parameter requests without the independence declaration
- pinned companions containing likely secret values
- expected calls above `max_calls`

After running probes, Python must check:

- raw responses exist for calls with bodies
- `probe_log.jsonl` is readable
- auth values are not present in generated artifacts
- every finding cites evidence labels or counts
- every policy maps to a finding
- `report.html` passes parity verification

## LLM Use

LLM calls are allowed only for bounded writing tasks:

- summarize structured evidence into `findings.md`
- derive `policies.md` from findings and downstream context
- draft short explanatory text for the report

The LLM should receive structured evidence, counts, labels, hashes, and small escaped previews only when needed. Raw API responses are untrusted and should not be pasted directly into prompts.

Model names and provider-specific options stay outside this spec and follow the repo reference docs.

## Acceptance Criteria

- A valid `request.json` can run end to end with one command.
- An invalid request fails before network access with a clear reason.
- The harness uses the existing probe runner instead of duplicating probe behavior.
- Probe budget is calculated before execution.
- Evidence is saved before analysis.
- Secrets are not printed or written into artifacts.
- Findings and policies are traceable to logged evidence.
- The HTML report passes the parity verifier.
- The TypeScript reviewer can inspect a run directory without re-running probes.

## Build Order

1. Python request validation and config generation.
2. Budget calculation.
3. Subprocess wrapper for `probe_runner.py`.
4. `run_summary.json` generation from `probe_log.jsonl`.
5. Report/parity validation.
6. Minimal TypeScript reviewer.

