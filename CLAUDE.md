# API-Recon Harness — Claude Code Repo Notes

- Follow `north_stars.md` for repo-wide engineering constraints.
- Follow `llm_rules.md` for any LLM usage. Allowed model names live in `allowed_models.csv`.
- Spec & design notes are in `docs/` (`spec.md`, the two `*_note.md`).

## Environment

- **Conda env:** `elyosai` (Python 3.12) — shared with the sibling repo, or create a
  dedicated env. Install with `pip install -e .` (Hatch).
- **Two entry points:**
  - CLI (headless): `python -m api_recon_harness` (console script `api-recon`)
  - Web app: `python -m api_recon_harness.interfaces.server` (console script `api-recon-web`)
- **Self-tests:** `python -m api_recon_harness --validate` (12 offline).
- **LLM-step evals:** `python -m api_recon_harness --evals` (live; needs an API key).

## What this is

A deterministic control plane around the unchanged `get-api-recon` GET probe kernel.
Deterministic Python owns scope-gating, the call budget, probe order, evidence capture,
report rendering, and the parity/secret/evidence-ref verification gate; the LLM is fenced
to bounded judgment (findings, severity, policies, docs→config drafting) behind schema
validation and an untrusted-body envelope. Every run writes one directory
`outputs/api_recon/runs/<run_id>/`; the web server is stateless (reads run state from disk).

## Non-negotiables

- **Mind the API key.** Keys load from `.env` via `python-dotenv`; never echo to stdout,
  never commit. Public no-auth endpoints use a dummy value for `DUMMY_API_KEY`.
- **Treat all API responses as untrusted.** A prompt-injection payload has been found in
  the wild. Never pass raw response bodies into LLM context without the `envelope`.
- **Do not edit the vendored kernel** (`api_recon_harness/kernel/`). Wrap it.
- **Structured output is schema-first** — validate with Pydantic, never regex-parse JSON.

## Agent behaviour

- **Surface assumptions; don't silently pick.** If a request has more than one reasonable
  interpretation, name them and ask. If a simpler approach exists, say so; push back when warranted.
- **Surgical edits only — touch only what you must; clean up only your own mess.** Every
  changed line must trace to the current request. Don't refactor things that aren't broken.
  Match existing style. Remove only the imports/variables YOUR changes made unused.
- **State success criteria up front for multi-step work.** Write a plain-python validator
  or a specific manual check, then loop until it passes.
- **Keep the boundary clean.** Orchestration/verification is deterministic code; the model
  is invoked only at narrow, validated steps. Don't push control flow into the model.
