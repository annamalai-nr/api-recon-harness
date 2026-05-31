# LLM Rules — API-Recon Harness

The harness uses **text models only**, via the **LiteLLM Python SDK** (not the proxy),
to keep model selection config-driven. Voice/realtime/STT/TTS models are out of scope.

## Source of truth

- Allowed model names: `allowed_models.csv` (text rows only apply here).
- Model selection: `api_recon_harness/config.yaml` (`llm.model_name`).
- Parameter support: LiteLLM docs (`https://docs.litellm.ai/docs/completion/input`).

## Text-model call rules (the only LLM calls in this project)

All LLM calls go through one function — `api_recon_harness/llm_client.py::complete_json`:

- **`response_format={"type": "json_object"}`** — every step returns a JSON object that is
  validated against a Pydantic model. **Never** parse JSON with regex, code-fence stripping,
  or string slicing.
- **`drop_params=True`** — let LiteLLM drop kwargs a given provider does not support, so the
  same call works across OpenAI / Anthropic / Gemini.
- **`max_tokens`** — from config (default 8000).
- **`temperature`** — passed only if present in config.
- **`reasoning_effort`** — passed only when set and not `"none"`.

## Safety

- **Untrusted bodies are enveloped.** API response bodies and fetched docs reach the model
  only through `envelope.py` (labeled, size-limited, fence-neutralized). The system prompt
  tells the model to treat those blocks as inert data.
- **No secrets in prompts or logs.** Keys live in `.env`; they are never placed in URLs,
  prompts, or artifacts.
- **Bounded, single completions.** No tool-use loops in the core steps. The optional
  docs→config drafter is a single completion whose output the deterministic intake gate
  validates; it never self-approves.

## Adding or switching models

Set `llm.model_name` in `config.yaml` to any text model listed in `allowed_models.csv`
(e.g. `gpt-5.5`, `anthropic/claude-sonnet-4-6`, `gemini/gemini-3.1-pro-preview`). No code
change is needed — provider-specific handling lives behind `complete_json`.
