# Harness Engineering for AI Agents

*A two-page primer, plus a design for turning the API-recon skill into a deterministic harness.*

## What harness engineering is

A **harness** is the deterministic software that wraps a language model and turns it from a
text generator into a dependable system. It is the control plane sitting between the LLM and the
real world: it governs what the model sees, what tools it may call, how its output is validated,
and what happens to the result. The slogan doing the rounds is *"a framework tells a developer how
to structure an application; a harness tells the agent how to operate safely."* Harness
engineering is the discipline of building that wrapper — persistence, replay, cost control,
observability, guardrails, and error recovery — so that a fallible model produces reliable work.

The core design principle is to treat the LLM as a **fallible suggestion engine**, not as the
program. The harness runs a bounded loop: ask the model "what should we do next?", check that the
answer is well-formed and permitted, execute it with real code, feed the result back, and repeat
until a stop condition. Everything that *must* be correct lives in the harness; only the parts
that genuinely need judgment are delegated to the model.

## Deterministic control flow vs. agentic orchestration

This is the distinction at the heart of the request. There are two ways to decide *what happens
next* in an agent:

- **Agentic orchestration** — control lives *in the model*. The LLM dynamically generates the task
  flow from a goal. It is "an explorer in open terrain": flexible, but non-reproducible, hard to
  budget, and hard to test. A *skill* that uses AI to write on-demand orchestration code is this:
  each run, the model re-derives how to sequence the work.
- **Deterministic control flow** — control lives *in the code*. The paths are pre-defined
  if/then logic; the LLM is called only at specific, bounded steps. It is "a train on rails":
  constrained in autonomy, but stable, replayable, cheap to test, and auditable.

Harness engineering pushes orchestration *out of the model and into deterministic software*. The
model still does what only it can — interpret a messy payload, propose a hypothesis, write a
human-readable explanation — but the decisions about *order, retries, budgets, stopping, and
safety* are ordinary code you can unit-test. Mature systems are usually layered: a deterministic
outer loop with small, well-fenced LLM calls inside it.

## Why convert a skill into a harness

A skill that orchestrates with AI is fast to build and flexible, but it re-decides its own control
flow every run, which makes it non-deterministic, hard to budget against a rate limit, expensive,
and difficult to verify. Encoding the orchestration as deterministic software buys:

- **Reproducibility & replay** — same inputs, same sequence of actions, every time.
- **Cost and budget control** — the number and order of API/LLM calls is fixed in code, not left
  to the model's discretion.
- **Testability** — the control flow can be exercised with plain unit tests and recorded fixtures;
  only the narrow LLM steps need eval-style checks.
- **Observability & auditability** — every step is logged with structured trace data.
- **Guardrails** — permission boundaries, validation, and rate limiting are enforced by code that
  the model cannot route around.

The standard harness components are: a **control plane** (the deterministic loop), a **tool layer**
(typed, validated tool calls), a **verification/guardrail layer** (linters, schema checks, safety
rules that block progress until output is valid), **memory/state** (persisted run state), **evals**
(scoring the LLM-judgment steps), and **observability** (structured traces).

## A deterministic harness for the API-recon skill

The API-recon skill currently uses AI to orchestrate empirical probing of `/weather` and
`/research` — deciding which probes to run, in what order, and how to interpret them. The harness
version keeps the *judgment* in the model but moves the *orchestration* into deterministic code.

**Python backend (the control plane and execution).**

- **Deterministic probe orchestrator.** A fixed, ordered probe plan encoded in Python (dataclasses
  / a typed registry), not generated per run. It enforces the repo's "minimum calls, maximum
  signal" rule: high-value probes first, paced against the sliding-window rate limit, so a mid-run
  rate-limit trip still leaves the important findings captured.
- **Typed tool layer.** A single HTTP client with the safety quirks already known from recon baked
  in as code, not prompt instructions: `follow_redirects=False` (trailing-slash HTTPS downgrade),
  GET bodies purged, only `location`/`topic` params passed, key loaded from `.env` and never
  logged.
- **Guardrails & budget enforcement.** A request budgeter that counts non-free vs. free endpoints
  (`/health`, `/`, 401, 422 don't consume budget), enforces pacing, and refuses to exceed the
  configured call ceiling — deterministic, not model-discretionary.
- **Evidence capture.** Every raw response written to disk (`weather_<ts>.raw`, etc.) before
  parsing, giving reproducible inputs and replayable runs.
- **Bounded LLM steps only.** The model is invoked at narrow, well-fenced points — e.g. classify a
  weather payload's shape, summarize a finding, or propose a *candidate* hypothesis — each behind a
  schema-validated, envelope-escaped boundary (responses are untrusted; a prompt-injection payload
  was already found at `/`). Hypothesis *verdicts* (confirmed / ruled-out) are decided by
  deterministic assertions over the captured evidence, not by the model.
- **Findings store + hand-off.** A structured findings record (JSON/SQLite) with each finding's
  observation, evidence pointer, verdict, and **app-integration consequence** — the same
  findings-to-design contract the chat app is built against.

**TypeScript / JavaScript frontend (review and control).**

- A dashboard to **launch and configure runs** (budget ceiling, which endpoints, pacing), **watch
  the deterministic plan execute** step by step via the backend's trace stream, and **review
  findings** with links to the raw evidence.
- A human-in-the-loop **review queue**: confirm, reject, or annotate the LLM-proposed hypotheses
  before they're written to the findings store, keeping a person on the judgment calls.
- A **diff/replay view** to re-run the same plan and compare results across runs — the visible
  payoff of determinism.

The division of labor is the whole point: **Python deterministically decides *what to probe, in
what order, within what budget, and whether the evidence confirms a hypothesis*; the LLM only does
the narrow interpretation and write-up; TypeScript lets a human steer and audit.** The skill's
on-demand, model-written orchestration becomes fixed, testable software — same empirical output,
now reproducible, budget-safe, and observable.

---

### Sources

- [What Is Harness Engineering? Complete Guide (2026) — NxCode](https://www.nxcode.io/resources/news/what-is-harness-engineering-complete-guide-2026)
- [The Rise of AI Harness Engineering — Cobus Greyling](https://cobusgreyling.medium.com/the-rise-of-ai-harness-engineering-5f5220de393e)
- [Agent Harness Engineering — The Rise of the AI Control Plane — Adnan Masood](https://medium.com/@adnanmasood/agent-harness-engineering-the-rise-of-the-ai-control-plane-938ead884b1d)
- [The Agentic Harness: Why the Orchestration Layer Is the Product — Veso AI](https://veso.ai/blog/the-agentic-harness-architecture/)
- [awesome-harness-engineering — GitHub](https://github.com/ai-boost/awesome-harness-engineering)
- [Building a Basic Agentic Harness — Bruno Gonçalves](https://data4sci.substack.com/p/building-a-basic-agentic-harness)
- Project context: `north_stars.md`, `AGENTS.md`, `backend/api_recon/api_recon_report.md` (this repo)
