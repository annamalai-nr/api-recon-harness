# Spec — API-Recon Harness (Python + TypeScript)

> **Provenance note.** This is the original design spec, imported verbatim from the
> repository where the harness was first built (a sibling project). Internal path
> references (e.g. `north_stars.md`, `AGENTS.md`, and other repo-relative paths)
> point at that original layout, not this standalone project. In this project the
> implementation lives under
> `api_recon_harness/`, conventions in `north_stars.md` / `llm_rules.md`, and the
> built artifacts may differ from the spec where the README documents a deviation
> (e.g. the docs→config agent is a bounded completion rather than LangGraph
> `create_agent`). Kept unedited as an archived reference.

**Status:** Draft v1 · **Scope:** single GET endpoint, header/API-key auth · **Target:** a thin deterministic harness around the existing `get-api-recon-v3.1` skill.

## 1. Purpose & intent

Turn the API-recon *skill* (AI decides the orchestration at runtime) into a *harness* (deterministic
code owns the orchestration; the LLM is a bounded suggestion engine). Same empirical output — probe a
black-box GET endpoint, capture evidence, derive findings and downstream policies — but reproducible,
budget-safe, and verifiable. Reuse the existing `probe_runner.py` unchanged as the execution kernel;
this spec adds only the deterministic control plane around it and a minimal UI to launch and review runs.

Keep it small. A direct wrapper, not a platform. Prefer the standard library; add a dependency only
when it clearly saves work.

## 2. Goals / non-goals

**Goals.** Deterministic probe sequencing, scope gating, and budget enforcement in code; raw evidence
captured before any interpretation; every LLM claim traceable to logged evidence; parity + secret-leak
verification; a human review gate; a run replayable from its own directory.

**Non-goals (v1) — rejected at intake (per v3.1 scope).** Non-GET methods, request/form bodies,
path-param-only APIs (`{id}` placeholders), OAuth / multi-step auth, pagination/cursor traversal,
multi-endpoint orchestration, destructive/state-changing probes, secrets as query parameters,
**joint-value-space probing** (combinatorial variation of two params together), and **semantic-pair
probing** (`start_date > end_date` swaps, equal-value cases). Each parameter is probed one at a time,
companions held constant. Also no live trace streaming, no diff UI, no config/version hashing — the
frozen config file plus the run directory are the reproducibility artifact. Don't widen scope or invent behavior.

## 3. Control boundary (the core rule)

**Deterministic Python owns:** scope validation, URL construction, redirect policy
(`follow_redirects=False`), retry/throttle policy, call-budget gate, probe order, raw-evidence capture,
`probe_log.jsonl` parsing, mechanical finding candidates, parity + secret-scan checks, and run status.

**The LLM owns only bounded judgment.** Most LLM steps are *single constrained completions* with no
tools and no loop: turn *structured* evidence into finding prose, assign each finding a **Severity
(Major/Minor)**, run the **cross-parameter consolidation** pass, and derive **downstream-specific
policies** from the findings. The one genuine agent is optional — when a docs URL is supplied, a small
tool-using agent drafts a candidate probe config by reading the docs — and even then the deterministic
validator owns the verdict. Every LLM output is schema- or markdown-validated before it becomes a final
artifact. Untrusted API bodies reach the model only through quoted, labeled, size-limited envelopes —
never raw (a prompt-injection payload was already found at `/`).

Per v3.1, keep the two artifacts separate: **`findings.md` is downstream-agnostic** (the API misbehaves
the same way regardless of caller); **`policies.md` is downstream-specific**. The downstream context
drives *policy generation only* — never probe design — so policies can be regenerated from cached
findings when the downstream changes, with no re-probing.

## 4. Architecture

A small Python package plus a single-page TypeScript UI. Each run is a directory on disk; the backend
is otherwise stateless and synchronous.

```
TypeScript UI (reviewer/inspector)   Python backend (thin control plane)
  read status / view findings <··      intake → plan → execute → analyze → verify
  approve / reject findings            probe_runner.py  (execution kernel, unchanged)
                                       output_dir: probe_config.json, *.raw, probe_log.jsonl, status.json,
                                                   findings.md, policies.md, report.html
       (UI reads files in v1; a local launcher wrapper only if runs must start from the browser)
```

**Backend — Python.** Five plain steps, each a module-scope function over a typed config, writing to
the run directory so a run can be replayed by pointing at its config:

1. **Intake & scope gate.** Accept a request (endpoint URL, auth header + env var name, parameters with
   per-parameter `pinned_companions`, docs URL, timeout, output dir, `run_auth_edges`). Run the
   **independence gate** for multi-parameter configs and reject out-of-scope work *before any network call*
   with pure-Python validation. Missing fields → return a short question list, never guess (don't guess
   parameter names). The LLM may pre-fill a draft request; the validator owns the verdict.
2. **Plan.** Build a typed `probe_config.json`: require `parameters_independence_declared` for
   multi-parameter runs, 6–10 Tier-1 values per parameter, each with a `purpose`; per-parameter
   `pinned_companions` (literal, non-secret, "boringly valid"); shared Tier-3 edge labels and Tier-4
   adversarial bait. Do a light **docs lookup** (supplied URL, else WebSearch/WebFetch) to fill the API
   Available Info section. **Resolve downstream context**: use it if given (fetch a URL if provided), else
   ask offering four archetypes (chat/agent, batch ETL, dashboard, backend service), else make an informed
   guess and state it in the scope header. Optional cheap preflight (one valid call per parameter) so bad
   values fail before the full sweep spends budget.
3. **Execute.** Run `probe_runner.py` with the frozen config: the **7 probe categories** —
   per-parameter (1 schema diversity, 2 cache/determinism, 3 input edges, 5p protocol edges) and
   endpoint-level (4 adversarial/injection, 5e protocol edges, 6 auth edges [optional], 7 concurrency).
   Fixed order, no redirect following, HTTP-200-throttle-in-body detected and **retried internally up to
   3×**, body-bearing responses saved as flat `*.raw` files under `output_dir` (`save_raw` skips empty
   bodies; throttled calls add a `*.throttled_first.raw`), every body scanned against the 8 injection
   heuristics. Because we reuse the runner unchanged, the **budget gate is planned-call only**: the wrapper
   computes the *planned* probe count from the config and refuses to start if it exceeds `max_calls`; it
   cannot cap the runner's internal retries, so *actual* calls and retries are reported afterward in
   `status.json` (exit code, timestamps, planned vs actual counts, output files). Hard total-call
   enforcement would require modifying the runner — out of scope for v1.
4. **Analyze.** Deterministic parsing of `probe_log.jsonl` + raw files yields candidate signals (status
   distributions, repeated `body_sha256`, redirect targets + `redirect_to_http` security flags,
   size/latency outliers, injection-heuristic hits, throttle bodies, per-parameter validity rates →
   **dependency detection**). The LLM then turns candidates into `findings.md` per the **findings
   contract** below; a finding without an evidence pointer is rejected. `policies.md` is generated from
   cached `findings.md` with the resolved downstream context — no re-probing.

**Findings & report contract (mandatory, per v3.1).** `findings.md`, `policies.md`, and `report.html`
each begin with the **scope header** (endpoint, parameters, pinned companions, "joint behaviors not
tested", auth-edge status, **downstream assumption**) and an **API Available Info** section (Service,
Endpoint, Parameters tested, Pinned companions, Purpose, Auth, Documentation, Documented response shape,
Documentation gaps). Each finding carries **Severity (Major | Minor)**, Observation (with JSONL labels +
counts), Mechanism, Reliability (from the controlled-vocabulary table, with counts), and **Parameters as
the last field** (the parity regex captures from `**Parameters**:` to the next heading, so earlier
placement breaks it). Findings are grouped **Cross-parameter** (promoted by a consolidation pass when a
behavior is shared across ⌈P/2⌉+ parameters at the same severity) then **Per-parameter**, each section
sorted Major-first; `findings.md` ends with a **Ruled-out hypotheses** section. When dependency detection
fires, `report.html` shows the **dependency banner** with its possible causes (pinned companions may be
invalid, Tier-1 too niche, undeclared dependency).
5. **Verify & review.** Run `verify_report_parity.py` plus cheap checks: scope header present in all
   artifacts, no auth value in logs/reports, no raw injection payload in any LLM prompt, every cited
   evidence label exists in the log, every policy maps to a real finding. Pass → `complete`; fail →
   `needs_revision` with a one-line repair task. A human approves LLM-proposed findings/policies before
   they're finalized.

**Frontend — TypeScript.** In v1 the UI is a **reviewer/inspector only**: it reads the run directory
(`status.json`, `findings.md`, `policies.md`, `report.html`, `*.raw`) and offers approve/reject — it does
**not** launch runs (a static browser page cannot start a Python process). Runs are started from the CLI.
If launching from the browser is required, add a **minimal local Node/HTTP wrapper** that shells out to the
CLI and serves the run directory; that wrapper is the only thing that turns the file interface into HTTP.
Presentation only — no orchestration in the client. Plain `fetch`/file reads + polling; no streaming.

**Agent implementation (the one tool-using step).** The optional docs→config drafting agent follows the
reference implementations at `smart_research/.../references/langgraph_examples/`: use LangChain v1
`create_agent` for the docs-to-config drafting step, with `ToolCallLimitMiddleware` enforcing tool-call
limits, and the read/fetch tool envelope-escaped. Pin `langchain>=1.0`, `langgraph>=1.0`. Everything else
stays plain stdlib + single completions; LangGraph is confined to this step so it doesn't bloat the harness.

## 5. Inputs & output (typed contract)

The harness takes one `RequestObject` and produces one run directory. Types are language-neutral
(mirror as Pydantic in Python / interfaces in TS).

**Mandatory inputs**

- `endpoint_url`: `string` — the single GET endpoint under recon.
- `auth_header_name`: `string` — header carrying the key (e.g. `Authorization`, `X-API-Key`).
- `auth_env_var`: `string` — name of the env var holding the key (the value is loaded from `.env`, never passed inline).
- `parameters`: `list<ParameterSpec>` — where `ParameterSpec = { name: string, purpose: string, tier1_values: list<string> (6–10), pinned_companions?: list<{name: string, value: string}>, tier3_edges_override?: list<{label: string, value: string}> }`. Companions are per-parameter, literal, and non-secret. (`tier3_edges_override` entries need both `label` and `value` — the runner uses both.)

**Optional inputs** (with defaults)

- `parameters_independence_declared`: `bool` — must be `true` for multi-parameter runs. Default `false`.
- `shared_tier3_edges`: `list<{label: string}>` — edge labels applied to every parameter. Sensible default set.
- `tier4_adversarial`: `list<{label: string, value: string}>` — injection bait for the endpoint-level probe. Default set provided.
- `docs_url`: `string | null` — if set, enables the optional docs→config drafting agent and enriches API Available Info. Default `null`.
- `downstream_context`: `string | null` — the application that will consume the API (archetype or free-form). **Drives policy generation only — not probe design.** Default `null` → harness makes an informed guess and states it in the scope header.
- `timeout_seconds`: `float` — per-request timeout. Default `30`.
- `output_dir`: `path` — where the run directory is written. Default `./outputs/api_recon/<endpoint_slug>/` (per v3.1).
- `run_auth_edges`: `bool` — run Category 6 auth-failure edge probes. Default `true` (matches the runner).
- `run_preflight`: `bool` — one valid call per parameter before the full sweep. Default `true`.
- `max_calls`: `int | null` — **harness-added** ceiling on the *planned* probe count (not in v3.1). Gated before execution; cannot bound the runner's internal throttle retries (see §4 step 3). Default `null` → no ceiling, calls bounded only by the config.

**Expected output** — a run directory whose primary deliverables are a **set of Markdown files**
(`findings.md`, `policies.md`) and an **HTML report** (`report.html`, as in skill v3.1), alongside the
machine-readable artifacts below and a returned `RunStatus`:

- `probe_config.json`: `ProbeConfig` — the frozen, validated probe plan (v3.1 name; the runner consumes it directly).
- `*.raw`: flat untrusted-byte files written directly under `output_dir` (`{ts}_{label}.raw`, plus `*.throttled_first.raw` on throttle). Body-less responses are skipped, so the raw-file count need not equal the call count.
- `probe_log.jsonl`: `list<ProbeLogEntry>` — one JSON object per call.
- `findings.json` / `findings.md`: `list<Finding>` / `markdown` (downstream-agnostic) — `Finding = { id: string, severity: enum{Major, Minor}, scope: enum{cross_parameter, per_parameter}, parameters: list<string>, observation: string, mechanism: string, reliability: string, evidence_ref: list<string> }`. Both files carry the scope header + API Available Info; `findings.md` is grouped cross-parameter then per-parameter (Major-first) and ends with a Ruled-out hypotheses section.
- `policies.json` / `policies.md`: `list<Policy>` / `markdown` (downstream-specific) — `Policy = { finding_id: string, detection_signal: string, policy_statement: string, code_implication: string }`, one per finding, proportional to its reliability.
- `report.html`: `html` — styled report reproducing all of both markdown files (parity-checked); cross-parameter cards expanded, per-parameter collapsed, dependency banner when it fires.
- `status.json` → returned `RunStatus`: `{ run_id: string, state: enum{complete, needs_revision, error}, expected_calls: int, actual_calls: int, exit_code: int, started_at: timestamp, ended_at: timestamp, artifacts: list<path> }`.

## 6. Interface

**v1 default: a file + subprocess interface, no HTTP.** The harness is a CLI/library that reads a request
object and writes the run directory; the TypeScript reviewer reads those files (`status.json`,
`findings.md`, `policies.md`, `report.html`, `*.raw`) directly. Runs start from the CLI, not the browser.

**Add a local launcher only if runs must start from the browser.** A static page cannot spawn Python, so
this requires a minimal local Node/HTTP wrapper that shells out to the CLI and serves the run directory.
Keep it to the smallest surface that works — for example:

- `POST /runs` → validate + start a run via the CLI; returns `run_id` or a validation verdict / question list.
- `GET /runs/{id}` → serve `status.json` + findings (the UI polls this).
- `POST /runs/{id}/findings/{fid}/review` → approve / reject / edit.

(Request/response bodies are the typed records from §5.)

## 7. Constraints

API key from `.env`, never logged, echoed, or written to any artifact (including `probe_log.jsonl` URLs
and `.raw` files — the reason secrets-as-query-params are out of scope). All remote responses untrusted;
envelope/escape before any LLM context. Minimum calls / maximum signal: when `max_calls` is set, the
*planned* probe count is gated before execution; *actual* calls (including the runner's internal throttle
retries) are reported afterward, not capped. Synchronous by default. Model name stays config-driven (not
in this spec). Keep modules single-responsibility and the public surface small.

**Build on existing repo configuration — do not scaffold a new platform.** Reuse the existing terminal
environment, the existing `pyproject.toml`, the existing allowed-models / reference docs, and the existing
`.env` loading conventions. Do **not** create a new allowed-models file, a new north-stars file, or
duplicate any pyproject/env/model config. Add only the code directly needed for the API-recon harness, on
top of the unchanged v3.1 skill.

## 8. Acceptance criteria

1. Same request + config ⇒ identical planned probe sequence (one sanity test asserts this).
2. Out-of-scope requests rejected before any network call (incl. path-param-only, joint-value-space, semantic-pair).
3. When `max_calls` is set, the budget gate stops an over-*planned*-count run before any request is made; actual calls/retries are reported in `status.json`.
4. Every body-bearing response is saved as a `*.raw` file when available before analysis (body-less responses are skipped and throttle retries add `*.throttled_first.raw`, so raw-file count may differ from the JSONL call count); a run is replayable from its directory.
5. Every LLM finding/policy cites a label present in `probe_log.jsonl`; unsourced claims rejected.
6. `verify_report_parity.py` passes (title, severity labels + Major-first sort, finding/policy counts, API Available Info fields, scope header, auth-edge status, ruled-out, per-parameter sections, dependency banner) before `complete`.
7. Every finding has a Severity; sections are Major-first; `**Parameters**` is the last field in each block.
8. Secret-scan: no API key or auth value in any log, report, prompt, or `.raw`/`.jsonl` URL.
9. The UI can read a run directory, show its status, and approve a finding (launching, if needed, goes through the local Node/HTTP launcher — not the static page).

## 9. Build order

`schemas.py` (typed records) → `intake.py` (scope gate) → `budget.py` (call calculator + gate) →
`plan.py` (config + optional preflight) → `execute.py` (runner wrapper + status) → `evidence.py`
(log parser + candidates) → `validators.py` (parity / secret / reference) → CLI entry + run directory →
the single-page UI reading those files (add a thin sync HTTP layer only if the UI needs it). LLM steps
added last: plain completions for findings/policies/summary, and the
optional `create_agent`-based docs→config agent (per the `langgraph_examples` reference) — all behind
envelope + schema validation. One or two sanity tests against real runs, not a full suite.

## 10. Test cases & evals

Two tiers, matching the control boundary: deterministic checks for the Python harness (plain test
scripts, real runs per `north_stars.md`), and small fixture-based evals for the bounded LLM steps.

**Deterministic harness checks (must all pass):**

1. *Determinism* — same `RequestObject` ⇒ byte-identical `probe_config.json` and identical planned probe sequence across two runs.
2. *Scope gate* — each out-of-scope request (non-GET, request body, path-param-only, OAuth, pagination, multi-endpoint, secret in query string, joint-value-space, semantic-pair) is rejected **before any network call**.
3. *Budget gate (planned)* — a config whose *planned* probe count exceeds `max_calls` refuses to start with zero requests made; `status.json` reports planned vs actual after a run.
4. *Missing-field intake* — omitting a mandatory field returns a question list, not a guessed value.
5. *Evidence-first* — every body-bearing response is on disk as a `*.raw` before analysis runs; raw-file count may legitimately differ from the JSONL call count (empty bodies skipped, throttle retries add files).
6. *Secret hygiene* — the API key / auth value appears in no log, report, prompt, or artifact (scan the whole run dir).
7. *Redirect safety* — a trailing-slash / redirect response is not followed (`follow_redirects=False`).
8. *Evidence-reference integrity* — every `Finding.evidence_ref` resolves to a label present in `probe_log.jsonl`; an unsourced finding is rejected.
9. *Policy mapping* — every `Policy.finding_id` maps to a real `Finding.id`.
10. *Report parity* — `verify_report_parity.py` confirms `report.html` faithfully reproduces `findings.md` + `policies.md`; a mismatch yields `state = needs_revision`.
11. *Replay* — re-running from a saved `probe_config.json` reproduces the same plan and run-directory shape.

**LLM-step evals (fixture-based).** Reuse v3.1's own eval taxonomy (`evals/evals.json`, 21 cases) for the
judgment steps, plus harness-specific ones:

- *Shape classification* — single-param, independent multi-param, joint-required (recommend `pinned_companions`), and hierarchical-dependency (fire the dependency banner) are each classified correctly.
- *Out-of-scope refusal* — POST, path-param-only, OAuth, and auth-as-query are declined with the right reason, no improvised config.
- *Severity* — e.g. a WAF/HTML-body 403 or plaintext 429 → Major; case-insensitive search → Minor.
- *Consolidation* — shared behavior across ⌈P/2⌉+ params merges to one cross-parameter finding; mechanistically distinct behavior stays separate.
- *`pinned_companions` config* — produces valid, "boringly valid" companion pins for a joint-required endpoint.
- *Dependency banner copy* — lists all three causes at equal weight.
- *Findings faithfulness* — generated `findings.md` cites only existing evidence labels, invents nothing, `**Parameters**` last.
- *Injection resistance* — a raw body carrying the planted payload is envelope-escaped; LLM output unaffected.
- *Docs→config agent* — drafted `ProbeConfig` is schema-valid and respects the `ToolCallLimitMiddleware` budget.

A run is marked `complete` only when every deterministic check passes; eval regressions block changes to the LLM steps.

---

*Sources:* repo `north_stars.md`, `AGENTS.md`, `backend/api_recon/api_recon_report.md`; skill internals per
`../codex/api_recon_agent_harness_report.md` (`probe_runner.py`, `probe_config.json`, `verify_report_parity.py`);
agent-build reference `smart_research/backend/agents/agent_02_steps_meta_coder/references/langgraph_examples/`
(current LangChain/LangGraph v1.x: `create_agent` + `ToolCallLimitMiddleware`, verified May 2026).
