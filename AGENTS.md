# Agent Instructions (API-Recon Harness)

## Non-negotiables

- Follow `north_stars.md` for coding constraints (simplicity, single responsibility,
  absolute imports `api_recon_harness.*`, no pytest, conda-only, deterministic control plane).
- Follow `llm_rules.md` for any LLM calls. Allowed model names live in `allowed_models.csv`.
- Spec & design notes are in `harness_engineering/`.
- **API key handling:** `.env` holds the LLM key (`OPENAI_API_KEY`, or another provider) and,
  for a header-authed target, that endpoint's key under the env-var name the request names.
  Always load via `python-dotenv`; never echo to stdout; never commit. Public no-auth
  endpoints use a dummy value for `DUMMY_API_KEY` — the user never types a key.
- **Untrusted API responses:** response bodies can carry prompt-injection content.
  Defensive default: never pass raw response bodies into LLM context without envelope/escape.
- **The vendored kernel is frozen:** `api_recon_harness/kernel/probe_runner.py` and
  `verify_report_parity.py` are reused verbatim. Wrap them; do not edit them.

## The control boundary

- **Deterministic Python owns orchestration:** scope-gating, the planned-call budget,
  probe order, evidence capture, report formatting (Major-first sort, canonical ids,
  `**Parameters**`-last, scope header, dependency banner), and the parity/secret/
  evidence-ref verification gate.
- **The LLM owns only bounded judgment:** finding prose, severity, cross-parameter
  consolidation, policies, and the optional docs→config drafting. Each is a single
  schema-validated completion; ids and formatting are owned by `render.py`.
- Do not move control flow into the model. If a check must be correct, it is code.

## Agent behaviour

- **Surface assumptions; don't silently pick.** If a request has more than one reasonable
  interpretation, name them and ask. If something is unclear, stop and ask. If a simpler
  approach exists, say so; push back when warranted.
- **Surgical edits only — touch only what you must; clean up only your own mess.** Every
  changed line must trace directly to the current request. Don't "improve" adjacent code,
  comments, or formatting. Match existing style even if you'd do it differently.
- **State success criteria up front for multi-step work.** Write a plain-python validator
  (`--validate`) or a specific manual check, then loop until it passes. Bounded LLM steps
  get fixture-based evals (`--evals`).
