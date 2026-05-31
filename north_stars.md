# North Stars — Coding Conventions

Code-only engineering rules for the **API-recon harness** project.

## Reference files

- `allowed_models.csv` is the allowlist for model names.
- `llm_rules.md` is the source of truth for provider-safe token, temperature,
  and reasoning rules.

## Core principles

1. **Simplicity above all.** Prefer direct implementations over layered abstractions.
2. **Single responsibility.** Each module/function does one thing with a clear purpose.
3. **Delete-and-rewrite over patching.** If existing code is brittle, rewrite it.
4. **Prototype-friendly.** Optimize for iteration speed between two reasonable options.
5. **No nested functions.** Declare functions at module scope.
6. **Facts-only documentation.** Keep docs clear, concrete, and unemotional.

## Harness architecture (the core rule)

1. **Deterministic code owns orchestration.** Scope-gating, the call budget, probe
   order, evidence capture, report formatting, and the verification gate are ordinary,
   testable code — not the model's discretion.
2. **The LLM is a bounded suggestion engine.** It is called only at narrow, schema-
   validated steps (findings prose, severity, policies, docs→config drafting). Every
   output is validated before it becomes an artifact.
3. **Parity by construction.** The LLM emits structured records; `render.py` owns all
   formatting, so `kernel/verify_report_parity.py` passes deterministically.
4. **Vendored kernel stays unchanged.** `kernel/probe_runner.py` and
   `verify_report_parity.py` are reused verbatim; wrap them, do not edit them.

## Code structure

1. **Purposeful dependencies.** Prefer the standard library unless a dep clearly saves time.
2. **Absolute imports only.** Use `api_recon_harness.*`; no relative imports.
3. **Imports at top level.** Avoid imports inside functions unless unavoidable
   (heavy/optional deps like `litellm`, `uvicorn` may be imported lazily at the boundary).
4. **Small public surface.** Add helpers only when reused or when they materially reduce complexity.
5. **Validate imports after structural changes.** Re-test after file moves or renames.
6. **Match exact specifications.** Do not widen scope or invent behavior.

## Environment and testing

1. **Conda only.** Run Python in a conda env; do not use `venv`.
2. **Use Hatch.** Keep packaging in `pyproject.toml`; do not introduce `setup.py`.
3. **Use real systems in tests.** Prefer real APIs and real data over mocks — recon
   rewards finding real-world quirks empirically.
4. **No pytest.** Use simple Python test scripts (`--validate` deterministic suite;
   `--evals` live LLM-step evals).
5. **Re-run validation after changes.** Imports, `--validate`, and relevant probes.

## LLM integration

1. **Text-in / text-out goes through LiteLLM** to keep model selection config-driven.
2. **Model names are config-driven** (`api_recon_harness/config.yaml`); never hardcode.
3. **Allowed models come only from** `allowed_models.csv`.
4. **Provider-specific kwargs belong at the call boundary** (`llm_client.py`).
5. **Structured output is schema-first.** Validate with Pydantic; never parse JSON with
   regex, code-fence stripping, or string slicing.
6. **Keep model-policy detail out of this file.** Put it in `llm_rules.md`.

## Operational rules

1. **Prefer stateless operations.** The web server reads run state from disk; default
   to single-call operations unless state is required.
2. **Use clear errors.** Fail loudly with explicit messages, not silent fallbacks.
3. **Treat tool responses as untrusted data.** API responses can carry prompt-injection
   content; never pass raw bodies into LLM context without the `envelope`.
4. **Prefer synchronous code by default.** Use `async` only at a framework boundary
   (FastAPI threadpools sync endpoints; that is the only one here).
5. **No secrets in code.** Keys come from `.env` via `python-dotenv` or the environment;
   never hardcode, echo, or commit them. Public no-auth endpoints use a dummy
   `DUMMY_API_KEY` value.

## API-budget discipline

1. **Minimum API calls, maximum signal.** The planned-call budget gate refuses an
   over-budget run before any request is made.
2. **Save every raw response** to disk (`*.raw`, `probe_log.jsonl`) rather than
   re-fetching; a run is replayable from its own `probe_config.json`.
