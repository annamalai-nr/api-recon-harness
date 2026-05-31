"""LiteLLM transport for the harness's bounded steps.

The only place the model is called. Model selection is config-driven
(`config.yaml`, per north_stars); callers pass a system + user prompt and get
back parsed JSON. Prompt text lives in `prompts/`; step orchestration lives in
`llm_steps.py` / `draft.py`. This module is just transport.
"""

import json
from functools import lru_cache

import yaml

from api_recon_harness.paths import CONFIG_PATH


@lru_cache(maxsize=1)
def _cfg() -> dict:
    """Load the llm config on first use (not at import) so it's cheap + overridable."""
    return yaml.safe_load(CONFIG_PATH.read_text())["llm"]


def _kwargs(cfg: dict) -> dict:
    kwargs: dict = {"max_tokens": cfg.get("max_tokens", 8000)}
    reasoning = cfg.get("reasoning_effort")
    if reasoning and reasoning != "none":
        kwargs["reasoning_effort"] = reasoning
    if "temperature" in cfg:
        kwargs["temperature"] = cfg["temperature"]
    return kwargs


def complete_json(system: str, user: str) -> dict:
    """One constrained completion → parsed JSON object (schema-validated by callers)."""
    import litellm  # local import keeps modules importable for offline tests
    cfg = _cfg()
    resp = litellm.completion(
        model=cfg["model_name"],
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        response_format={"type": "json_object"},
        drop_params=True,
        **_kwargs(cfg),
    )
    return json.loads(resp.choices[0].message.content)
