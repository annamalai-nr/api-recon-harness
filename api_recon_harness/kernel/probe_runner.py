#!/usr/bin/env python3
"""
probe_runner.py — GET-only REST API probe runner.

SCOPE
  This runner supports:
    - HTTP GET requests
    - Multiple *independent* query parameters, each probed separately
    - API-key / header-based auth (a single static credential in an env var)
    - Pinned companion parameters: each parameter can declare companions
      that are merged into every probe URL, satisfying joint-required APIs
      without combinatorial probing

  Parameters are iterated individually. Categories 1-3 and the per-param
  subset of 5 run once per parameter. Categories 4, 6, 7 and the endpoint
  subset of 5 run once for the whole endpoint.

  Backward compatible: a V2 config with scalar `param_name` is auto-converted
  to a one-element `parameters` list.

CATEGORIES (run in order, paced 0.3s between calls)
  Per-parameter:
    1. Schema diversity   — 6-10 valid inputs per param
    2. Cache / determinism — repeat first 2 Tier 1 values per param
    3. Input edges        — shared dispatch or per-param overrides
    5p. Protocol (per-param) — wrong param, no params, duplicate param

  Endpoint-level (run once):
    4. Adversarial        — injection bait via first declared parameter
    5e. Protocol (endpoint) — trailing slash, OPTIONS
    6. Auth edges         — no key, wrong key, lowercase header (skippable)
    7. Concurrency        — 5 parallel calls via first declared parameter

OUTPUTS
  <output_dir>/probe_log.jsonl     — one JSON line per call
  <output_dir>/<ts>_<label>.raw    — full HTTP response per call

USAGE
  MY_API_KEY=xyz python scripts/probe_runner.py --config probe_config.json
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path


# ─── Injection heuristics (applied to every response body) ────────────
HEURISTICS: list[tuple[str, str]] = [
    ("html_comment",
     r"<!--[\s\S]*?-->"),
    ("override_instruction",
     r"\b(ignore|forget|disregard|override)\s+(all|previous|prior|earlier|the\s+above|any)"
     r"\s+(instructions?|context|prompts?|directives?)\b"),
    ("ai_self_reference",
     r"\b(if\s+you\s+are\s+an?\s+(llm|ai|assistant|agent|language\s+model)"
     r"|to\s+the\s+(llm|ai|assistant|model)|dear\s+(llm|ai))\b"),
    ("known_seed_marker",
     r"\b(banana|please\s+add\s+a\s+comment|found\s+via\s+(api|the\s+)|pwned_test_xyz123)\b"),
    ("hidden_unicode",
     r"[​‌‍⁠﻿͏‪-‮]"),
    ("roleplay_attempt",
     r"\b(act\s+as|pretend\s+(to\s+be|that)|respond\s+as|from\s+now\s+on|you\s+are\s+now|new\s+role)\b"),
    ("system_marker",
     r"(?:^|\W)(system:|instruction:|important:|note\s+to\s+(assistant|llm|ai|claude|gpt|model)"
     r"|directive:|new\s+instructions)\b"),
    ("imperative_at_reader",
     r"\b(you\s+must|you\s+should|you\s+will|you\s+need\s+to|please\s+(do|note|add|include|reply))\b"),
]

MAX_THROTTLE_RETRIES = 3
INTER_CALL_DELAY_S = 0.3
BODY_PREVIEW_CHARS = 300

UNSUPPORTED_KEYS = {
    "method": "Non-GET HTTP methods are not supported.",
    "request_body": "JSON / form request bodies are not supported.",
    "json_body": "JSON request bodies are not supported.",
    "path_params": "Path-parameter APIs are not supported.",
    "extra_params": "Multi-parameter joint variation is not supported.",
    "pagination": "Pagination / cursor traversal is not supported.",
    "oauth": "OAuth and multi-step auth flows are not supported.",
    "endpoints": "Multi-endpoint orchestration is not supported.",
}

SCOPE_NOTE = (
    "Scope: single GET endpoint, independent query parameters probed individually "
    "(with optional pinned companions for joint-required APIs), API-key/header auth."
)


# ─── Companion merging ──────────────────────────────────────────────────

def _with_companions(params, companions: list[dict]):
    """Merge pinned_companions into params (dict or list-of-tuples)."""
    if not companions:
        return params
    if isinstance(params, list):
        return params + [(c["name"], c["value"]) for c in companions]
    result = dict(params)
    for c in companions:
        result[c["name"]] = c["value"]
    return result


# ─── Shared edge dispatch table ──────────────────────────────────────────

def _alternate_case(s: str) -> str:
    return "".join(c.upper() if i % 2 else c.lower() for i, c in enumerate(s))


def compute_shared_edge(label: str, seed: str) -> str | None:
    """Return the edge value for a shared Tier 3 label, using seed (tier1[0]).

    Returns None if the label is not in the dispatch table.
    """
    dispatch = {
        "empty":            "",
        "very_long":        seed * (5000 // max(len(seed), 1) + 1),
        "upper":            seed.upper(),
        "lower":            seed.lower(),
        "mixed_case":       _alternate_case(seed),
        "pad_leading":      " " + seed,
        "pad_trailing":     seed + " ",
        "pad_both":         "  " + seed + "  ",
        "pad_tab":          "\t" + seed,
        "pad_newline":      seed + "\n",
        "unicode_cjk":      "海",
        "unicode_cyrillic": "океан",
        "unicode_arabic":   "محيط",
        "unicode_greek":    "θάλασσα",
        "unicode_diacrit":  "café",
        "fictional_1":      "xyzzyqwop",
        "fictional_2":      "asdfghjkl123",
        "html_inject":      "<script>alert(1)</script>",
        "digit_only":       "12345",
        "symbol_only":      "!!!",
    }
    if label in dispatch:
        val = dispatch[label]
        if label == "very_long":
            return val[:5000]
        return val
    return None


# ─── Config validation ──────────────────────────────────────────────────

def _convert_v2_config(cfg: dict) -> dict:
    """Auto-convert a V2 scalar param_name config to a parameters list."""
    if "param_name" in cfg and "parameters" not in cfg:
        cfg["parameters"] = [{
            "name": cfg.pop("param_name"),
            "purpose": "",
            "tier1_values": cfg.pop("tier1_values"),
        }]
        if "tier3_edges" in cfg:
            cfg["parameters"][0]["tier3_edges_override"] = cfg.pop("tier3_edges")
        cfg.setdefault("shared_tier3_edges", [])
        cfg["_v2_compat"] = True
    return cfg


def load_and_validate_config(path: str) -> dict:
    with open(path) as f:
        cfg = json.load(f)

    cfg = _convert_v2_config(cfg)

    if "parameters" not in cfg or not cfg["parameters"]:
        print("Config error: 'parameters' list is required and must be non-empty.",
              file=sys.stderr)
        sys.exit(2)

    required_top = ["base_url", "endpoint"]
    missing = [k for k in required_top if k not in cfg]
    if missing:
        print(f"Config error: missing required keys: {missing}", file=sys.stderr)
        print(SCOPE_NOTE, file=sys.stderr)
        sys.exit(2)

    for key, msg in UNSUPPORTED_KEYS.items():
        if key in cfg:
            print(f"Config error: '{key}' is set, but {msg}", file=sys.stderr)
            print(SCOPE_NOTE, file=sys.stderr)
            sys.exit(2)

    endpoint = cfg["endpoint"]
    if "{" in endpoint or "}" in endpoint:
        print(f"Config error: endpoint '{endpoint}' contains path-parameter placeholders "
              f"({{...}}). Path-param-only APIs are not supported.", file=sys.stderr)
        print(SCOPE_NOTE, file=sys.stderr)
        sys.exit(2)

    if not cfg.get("_v2_compat"):
        if not cfg.get("parameters_independence_declared"):
            print("Config error: 'parameters_independence_declared' must be true. "
                  "If these parameters are not independently characterizable "
                  "(even with pinned companions), use single-param mode instead.",
                  file=sys.stderr)
            sys.exit(2)

    for i, param in enumerate(cfg["parameters"]):
        if not param.get("name"):
            print(f"Config error: parameters[{i}] missing 'name'.", file=sys.stderr)
            sys.exit(2)
        if not param.get("tier1_values") or not isinstance(param["tier1_values"], list):
            print(f"Config error: parameters[{i}] ('{param['name']}') must have a "
                  f"non-empty tier1_values list.", file=sys.stderr)
            sys.exit(2)

        # Validate pinned_companions
        companions = param.get("pinned_companions")
        if companions is None:
            param["pinned_companions"] = []
        else:
            if not isinstance(companions, list):
                print(f"Config error: parameters[{i}] ('{param['name']}') "
                      f"pinned_companions must be a list.", file=sys.stderr)
                sys.exit(2)
            for j, comp in enumerate(companions):
                if not isinstance(comp, dict):
                    print(f"Config error: parameters[{i}].pinned_companions[{j}] "
                          f"must be a dict with 'name' and 'value'.", file=sys.stderr)
                    sys.exit(2)
                if not isinstance(comp.get("name"), str) or not comp["name"]:
                    print(f"Config error: parameters[{i}].pinned_companions[{j}] "
                          f"missing or invalid 'name' (must be a non-empty string).",
                          file=sys.stderr)
                    sys.exit(2)
                if not isinstance(comp.get("value"), str):
                    print(f"Config error: parameters[{i}].pinned_companions[{j}] "
                          f"missing or invalid 'value' (must be a string).",
                          file=sys.stderr)
                    sys.exit(2)

    return cfg


# ─── HTTP helpers ────────────────────────────────────────────────────────

class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_no_redirect_opener = urllib.request.build_opener(_NoRedirectHandler)


def _redact_headers(headers: dict) -> dict:
    return {k: "***" if any(s in k.lower() for s in ("key", "auth", "token")) else v
            for k, v in headers.items()}


def fetch(label: str, base_url: str, endpoint: str, params, method: str,
          headers: dict, timeout: float) -> dict:
    qs = urllib.parse.urlencode(params, doseq=True) if params else ""
    url = f"{base_url}{endpoint}" + (f"?{qs}" if qs else "")
    req = urllib.request.Request(url, headers=headers, method=method)
    t0 = time.monotonic()
    try:
        with _no_redirect_opener.open(req, timeout=timeout) as resp:
            body = resp.read()
            status = resp.status
            resp_headers = dict(resp.headers)
    except urllib.error.HTTPError as e:
        body = e.read()
        status = e.code
        resp_headers = dict(e.headers)
    except Exception as e:
        return {
            "label": label, "method": method, "url": url,
            "status": None, "latency_s": round(time.monotonic() - t0, 3),
            "error": f"{type(e).__name__}: {e}",
            "request_headers": _redact_headers(headers),
        }
    dt = time.monotonic() - t0
    body_text = body.decode("utf-8", errors="replace") if body else ""
    redirect_target = resp_headers.get("Location") or resp_headers.get("location")
    result = {
        "label": label, "method": method, "url": url,
        "status": status, "latency_s": round(dt, 3),
        "response_headers": resp_headers,
        "body_bytes_len": len(body),
        "body_sha256": hashlib.sha256(body).hexdigest(),
        "body_preview": body_text[:BODY_PREVIEW_CHARS],
        "body": body,
        "request_headers": _redact_headers(headers),
    }
    if redirect_target:
        result["redirect_target"] = redirect_target
        if redirect_target.startswith("http://"):
            result["security_flag"] = "redirect_to_http"
    return result


def is_throttled(result: dict) -> tuple[bool, float]:
    if result.get("status") != 200 or not result.get("body"):
        return False, 0
    try:
        data = json.loads(result["body"])
    except (json.JSONDecodeError, ValueError):
        return False, 0
    if isinstance(data, dict) and data.get("status") == "throttled":
        raw = data.get("retry_after_seconds", 30)
        try:
            wait = max(float(raw if raw is not None else 30), 0)
        except (ValueError, TypeError):
            wait = 30.0
        return True, wait
    return False, 0


def run_heuristics(body_bytes: bytes) -> list[str]:
    if not body_bytes:
        return []
    text = body_bytes.decode("utf-8", errors="replace")
    return [label for label, pattern in HEURISTICS
            if re.search(pattern, text, flags=re.IGNORECASE)]


def save_raw(result: dict, output_dir: Path, ts: str, suffix: str = "") -> None:
    if not result.get("body"):
        return
    path = output_dir / f"{ts}_{result['label']}{suffix}.raw"
    with open(path, "wb") as f:
        f.write(f"HTTP {result.get('status', 'ERR')}\n".encode())
        for k, v in (result.get("response_headers") or {}).items():
            f.write(f"{k}: {v}\n".encode())
        f.write(b"\n")
        f.write(result["body"])


def log_jsonl(result: dict, log_file: Path) -> None:
    clean = {k: v for k, v in result.items() if k != "body"}
    with open(log_file, "a") as f:
        f.write(json.dumps(clean, default=str) + "\n")


def print_row(result: dict) -> None:
    status = result.get("status", "ERR")
    latency = result.get("latency_s", 0)
    size = result.get("body_bytes_len", 0) or 0
    sha = (result.get("body_sha256") or "")[:8] or "--------"
    hits = ",".join(result.get("heuristic_hits", [])) or "-"
    label = result.get("label", "?")
    retries = result.get("throttle_retries", 0)
    gave_up = " GAVE_UP" if result.get("gave_up_after_throttle") else ""
    retry_info = f" R{retries}" if retries > 0 else ""
    redir = ""
    if result.get("redirect_target"):
        sec = " !! HTTP DOWNGRADE" if result.get("security_flag") == "redirect_to_http" else ""
        redir = f" -> {result['redirect_target'][:60]}{sec}"
    print(f"  [{label:38s}] {str(status):>4} {latency:6.2f}s {size:>6}B sha={sha} flags={hits}{retry_info}{gave_up}{redir}")


# ─── Core execute with throttle-aware retry ────────────────────────────

def execute_one(label: str, base_url: str, endpoint: str, params,
                method: str, auth_headers: dict, timeout: float,
                output_dir: Path, log_file: Path, ts: str,
                custom_headers: dict | None = None,
                parameter: str | None = None,
                endpoint_level: bool = False) -> dict:
    headers = custom_headers if custom_headers is not None else dict(auth_headers)
    throttle_retries = 0
    first_throttle_saved = False

    for attempt in range(MAX_THROTTLE_RETRIES + 1):
        result = fetch(label, base_url, endpoint, params, method, headers, timeout)
        throttled, wait = is_throttled(result)
        if not throttled:
            break
        if not first_throttle_saved:
            save_raw(result, output_dir, ts, ".throttled_first")
            first_throttle_saved = True
        if attempt == MAX_THROTTLE_RETRIES:
            result["gave_up_after_throttle"] = True
            break
        throttle_retries += 1
        sleep_s = wait + 1
        print(f"  [{label:38s}] throttled (retry {throttle_retries}/{MAX_THROTTLE_RETRIES}), "
              f"sleeping {int(wait)}s...")
        time.sleep(sleep_s)

    save_raw(result, output_dir, ts)
    result["heuristic_hits"] = run_heuristics(result.get("body", b""))
    result["throttle_retries"] = throttle_retries
    result["parameter"] = parameter
    result["endpoint_level"] = endpoint_level
    log_jsonl(result, log_file)
    return result


# ─── Category runners ───────────────────────────────────────────────────

def _slug(value: str) -> str:
    return re.sub(r"\W+", "_", str(value).lower())[:20]


def run_per_param_categories(
    param: dict, cfg: dict, api_key: str, output_dir: Path,
    log_file: Path, ts: str
) -> list[dict]:
    """Run Categories 1, 2, 3, 5p for a single parameter."""
    base_url = cfg["base_url"]
    endpoint = cfg["endpoint"]
    param_name = param["name"]
    auth_header = cfg.get("auth_header", "X-API-Key")
    timeout = float(cfg.get("timeout_s", 15))
    auth_headers = {auth_header: api_key, **cfg.get("_extra_headers", {})}
    t1_values = param["tier1_values"]
    companions = param.get("pinned_companions", [])
    results = []

    def run(label: str, params, method: str = "GET",
            custom_headers: dict | None = None) -> dict:
        r = execute_one(label, base_url, endpoint, params, method,
                        auth_headers, timeout, output_dir, log_file, ts,
                        custom_headers, parameter=param_name, endpoint_level=False)
        print_row(r)
        time.sleep(INTER_CALL_DELAY_S)
        results.append(r)
        return r

    # ── Category 1: Schema diversity ────────────────────────────────────
    print(f"\n  ─── Cat 1: Schema diversity ({len(t1_values)} inputs) ─────────")
    for i, value in enumerate(t1_values):
        run(f"{param_name}_t1_{_slug(value)}_{i}", _with_companions({param_name: value}, companions))

    # ── Category 2: Cache / determinism ─────────────────────────────────
    print(f"\n  ─── Cat 2: Cache / determinism (repeat first 2) ──────────")
    for i, value in enumerate(t1_values[:2]):
        run(f"{param_name}_t2_repeat_{i}", _with_companions({param_name: value}, companions))

    # ── Category 3: Input edges ─────────────────────────────────────────
    edges_override = param.get("tier3_edges_override")
    if edges_override:
        edges = edges_override
        print(f"\n  ─── Cat 3: Input edges ({len(edges)} per-param overrides) ──────")
        for edge in edges:
            value = edge["value"]
            if value == "x5000":
                value = "x" * 5000
            run(f"{param_name}_t3_{edge['label']}", _with_companions({param_name: value}, companions))
    else:
        shared = cfg.get("shared_tier3_edges", [])
        seed = t1_values[0] if t1_values else "test"
        print(f"\n  ─── Cat 3: Input edges ({len(shared)} shared, seed='{seed}') ──")
        for edge in shared:
            value = compute_shared_edge(edge["label"], seed)
            if value is None:
                print(f"  [WARN] Unknown shared edge label '{edge['label']}', skipping")
                continue
            run(f"{param_name}_t3_{edge['label']}", _with_companions({param_name: value}, companions))

    # ── Category 5p: Protocol edges (per-param) ────────────────────────
    print(f"\n  ─── Cat 5p: Protocol edges (per-param) ───────────────────")
    run(f"{param_name}_t5_wrong_param", _with_companions({"wrong_param_xyz": "test"}, companions))
    run(f"{param_name}_t5_no_params", _with_companions({}, companions))
    dup = [(param_name, t1_values[0]),
           (param_name, t1_values[1] if len(t1_values) > 1 else "alt_value")]
    run(f"{param_name}_t5_dup_param", _with_companions(dup, companions))

    return results


def run_endpoint_categories(
    cfg: dict, api_key: str, output_dir: Path,
    log_file: Path, ts: str, representative_param: dict
) -> list[dict]:
    """Run Categories 4, 5e, 6, 7 — once per endpoint."""
    base_url = cfg["base_url"]
    endpoint = cfg["endpoint"]
    rep_name = representative_param["name"]
    rep_t1 = representative_param["tier1_values"]
    auth_header = cfg.get("auth_header", "X-API-Key")
    timeout = float(cfg.get("timeout_s", 15))
    auth_headers = {auth_header: api_key, **cfg.get("_extra_headers", {})}
    run_auth = cfg.get("run_auth_edges", True)
    companions = representative_param.get("pinned_companions", [])
    results = []

    def run(label: str, params, method: str = "GET",
            custom_headers: dict | None = None,
            param_tag: str | None = None) -> dict:
        r = execute_one(label, base_url, endpoint, params, method,
                        auth_headers, timeout, output_dir, log_file, ts,
                        custom_headers, parameter=param_tag,
                        endpoint_level=True)
        print_row(r)
        time.sleep(INTER_CALL_DELAY_S)
        results.append(r)
        return r

    # ── Category 4: Adversarial (endpoint-level, via representative) ───
    adversarial = cfg.get("tier4_adversarial", [])
    if adversarial:
        print(f"\n─── Category 4: Adversarial / injection ({len(adversarial)}, via '{rep_name}') ──")
        for case in adversarial:
            run(f"t4_{case['label']}",
                _with_companions({rep_name: case["value"]}, companions),
                param_tag=rep_name)

    # ── Category 5e: Protocol edges (endpoint-level) ───────────────────
    print(f"\n─── Category 5e: Protocol edges (endpoint-level) ──────────────────")
    run("t5e_options",
        _with_companions({rep_name: rep_t1[0]}, companions),
        method="OPTIONS", param_tag=rep_name)
    trailing_endpoint = endpoint if endpoint.endswith("/") else endpoint + "/"
    print(f"  trailing-slash test endpoint: {trailing_endpoint}")
    r = execute_one("t5e_trailing_slash", base_url, trailing_endpoint,
                    _with_companions({rep_name: rep_t1[0]}, companions), "GET",
                    auth_headers, timeout, output_dir, log_file, ts, None,
                    parameter=rep_name, endpoint_level=True)
    print_row(r)
    time.sleep(INTER_CALL_DELAY_S)
    results.append(r)

    # ── Category 6: Auth edges ──────────────────────────────────────────
    if run_auth:
        print(f"\n─── Category 6: Auth edges ────────────────────────────────────────────")
        run("t6_no_key",
            _with_companions({rep_name: rep_t1[0]}, companions),
            custom_headers={}, param_tag=rep_name)
        run("t6_wrong_key",
            _with_companions({rep_name: rep_t1[0]}, companions),
            custom_headers={auth_header: "wrong-key-12345"}, param_tag=rep_name)
        run("t6_lowercase_hdr",
            _with_companions({rep_name: rep_t1[0]}, companions),
            custom_headers={auth_header.lower(): api_key}, param_tag=rep_name)
    else:
        print(f"\n─── Category 6: Auth edges (skipped — run_auth_edges: false) ─────────")

    # ── Category 7: Concurrency ─────────────────────────────────────────
    print(f"\n─── Category 7: Concurrency (5 parallel, via '{rep_name}') ────────────")
    conc_params = _with_companions({rep_name: rep_t1[0]}, companions)
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = [
            ex.submit(execute_one,
                      f"t7_concurrent_{i}",
                      base_url, endpoint, conc_params, "GET",
                      auth_headers, timeout, output_dir, log_file, ts, None,
                      rep_name, True)
            for i in range(5)
        ]
        conc_results = [f.result() for f in futures]
    wall = time.monotonic() - t0
    seq = sum(r.get("latency_s", 0) for r in conc_results)
    for r in conc_results:
        print_row(r)
    results.extend(conc_results)
    if wall > 0:
        print(f"  wall: {wall:.2f}s  sequential-equiv: {seq:.2f}s  speedup: {seq/wall:.1f}x")

    return results


# ─── Dependency detection ────────────────────────────────────────────────

def detect_dependencies(log_file: Path, parameters: list[dict]) -> list[dict]:
    """Heuristic: flag parameters whose Cat 1+2 validity rate is suspiciously low."""
    records = []
    with open(log_file) as f:
        for line in f:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    param_names = [p["name"] for p in parameters]
    if len(param_names) < 2:
        return []

    validity = {}
    for pname in param_names:
        cat12 = [r for r in records
                 if r.get("parameter") == pname
                 and not r.get("endpoint_level")
                 and any(r.get("label", "").startswith(f"{pname}_{t}") for t in ("t1_", "t2_"))]
        if not cat12:
            continue
        populated = sum(1 for r in cat12
                        if r.get("status") == 200
                        and (r.get("body_bytes_len") or 0) > 10)
        validity[pname] = populated / len(cat12) if cat12 else 0.0

    if not validity:
        return []

    max_rate = max(validity.values())
    median_rate = sorted(validity.values())[len(validity) // 2]
    warnings = []
    for pname, rate in validity.items():
        flagged = (rate <= 0.30) or (max_rate > 0 and rate <= max_rate * 0.50)
        if flagged:
            warnings.append({
                "parameter": pname,
                "validity_rate": round(rate, 2),
                "median_rate": round(median_rate, 2),
                "max_rate": round(max_rate, 2),
            })
    return warnings


# ─── Post-run analysis ───────────────────────────────────────────────────

def print_analysis(log_file: Path, auth_edges_run: bool,
                   parameters: list[dict]) -> None:
    records = []
    with open(log_file) as f:
        for line in f:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    sha_to_labels: dict[str, list[str]] = defaultdict(list)
    for r in records:
        sha = (r.get("body_sha256") or "")[:12]
        if sha:
            sha_to_labels[sha].append(r["label"])
    collisions = {sha: labels for sha, labels in sha_to_labels.items() if len(labels) > 1}

    injection_hits = [(r["label"], r["heuristic_hits"]) for r in records if r.get("heuristic_hits")]
    empty = [(r["label"], r.get("status"), r.get("latency_s")) for r in records
             if (r.get("body_bytes_len") or 0) < 10]
    throttled = [(r["label"], r.get("throttle_retries", 0)) for r in records
                 if r.get("throttle_retries", 0) > 0]

    print(f"\n{'─' * 70}")
    print("  POST-RUN ANALYSIS")
    print(f"{'─' * 70}")
    print(f"  Total calls logged: {len(records)}")
    print(f"  Parameters probed: {', '.join(p['name'] for p in parameters)}")
    print(f"  Auth-edge probes: {'run' if auth_edges_run else 'skipped (run_auth_edges=false)'}")

    # Per-parameter call counts
    for p in parameters:
        pname = p["name"]
        count = sum(1 for r in records if r.get("parameter") == pname and not r.get("endpoint_level"))
        print(f"    {pname}: {count} per-param calls")
    ep_count = sum(1 for r in records if r.get("endpoint_level"))
    print(f"    endpoint-level: {ep_count} calls")

    if collisions:
        print(f"\n  SHA collisions (deterministic cache or identical responses):")
        for sha, labels in collisions.items():
            print(f"    {sha}: {labels}")
    else:
        print(f"\n  SHA collisions: none (all responses unique)")

    if injection_hits:
        print(f"\n  Injection heuristic hits:")
        for label, hits in injection_hits:
            print(f"    {label}: {hits}")
    else:
        print(f"\n  Injection heuristic hits: none")

    if empty:
        print(f"\n  Empty / tiny responses (potential hidden timeout):")
        for label, status, latency in empty:
            print(f"    {label}: status={status} latency={latency}s")

    if throttled:
        print(f"\n  Throttle retries:")
        for label, retries in throttled:
            print(f"    {label}: {retries} retries")

    redirects = [(r["label"], r.get("redirect_target", ""), r.get("security_flag", ""))
                 for r in records if r.get("redirect_target")]
    if redirects:
        print(f"\n  Redirects detected:")
        for label, target, flag in redirects:
            sec = " !! SECURITY: redirect to http://" if flag == "redirect_to_http" else ""
            print(f"    {label}: -> {target}{sec}")
    else:
        print(f"\n  Redirects: none")

    # Dependency detection
    if len(parameters) >= 2:
        dep_warnings = detect_dependencies(log_file, parameters)
        has_companions = any(p.get("pinned_companions") for p in parameters)
        if dep_warnings:
            print(f"\n  SUSPECTED PARAMETER DEPENDENCIES:")
            for w in dep_warnings:
                print(f"    Parameter '{w['parameter']}': validity rate {w['validity_rate']:.0%} "
                      f"(median={w['median_rate']:.0%}, max={w['max_rate']:.0%})")
                print(f"      Possible causes:")
                if has_companions:
                    print(f"        - Your pinned companion values may not be valid for the inputs "
                          f"you're probing — try different canonical values")
                print(f"        - Your Tier 1 values may be too niche for this parameter's domain")
                print(f"        - An additional parameter dependency may exist that you haven't declared")
                print(f"      Review per-parameter Category 1 results to decide which cause fits.")
        else:
            print(f"\n  Dependency detection: no suspected dependencies (all params have healthy validity rates)")

    print(f"{'─' * 70}")


# ─── Entrypoint ──────────────────────────────────────────────────────────

def _slugify(s: str) -> str:
    return re.sub(r"\W+", "_", s).strip("_") or "endpoint"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="GET-only multi-parameter API probe runner")
    parser.add_argument("--config", required=True, help="Path to probe config JSON file")
    parser.add_argument("--api-key", help="API key (overrides env var from config)")
    parser.add_argument("--no-analysis", action="store_true", help="Skip post-run analysis")
    args = parser.parse_args()

    cfg = load_and_validate_config(args.config)
    env_var = cfg.get("auth_env_var", "API_KEY")
    api_key = args.api_key or os.environ.get(env_var)
    if not api_key:
        print(f"Error: API key not provided. Set ${env_var} or use --api-key.", file=sys.stderr)
        sys.exit(2)

    parameters = cfg["parameters"]
    is_v2_compat = cfg.get("_v2_compat", False)
    default_slug = _slugify(cfg["endpoint"])
    output_dir = Path(cfg.get("output_dir") or f"./outputs/api_recon/{default_slug}")
    output_dir.mkdir(parents=True, exist_ok=True)
    config_dest = output_dir / "probe_config.json"
    if Path(args.config).resolve() != config_dest.resolve():
        shutil.copyfile(args.config, config_dest)
    log_file = output_dir / "probe_log.jsonl"
    if log_file.exists():
        log_file.unlink()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    auth_edges_run = cfg.get("run_auth_edges", True)

    param_names = [p["name"] for p in parameters]
    total_shared_edges = len(cfg.get("shared_tier3_edges", []))

    mode = "V2-compat (single param)" if is_v2_compat else f"{len(parameters)} independent params"
    print(f"get-api-recon — probe runner ({mode})")
    print(f"  Target:     {cfg['base_url']}{cfg['endpoint']}")
    print(f"  Parameters: {', '.join(param_names)}")
    print(f"  Auth:       {cfg.get('auth_header', 'X-API-Key')} (from ${env_var})")
    extra_hdrs = cfg.get("_extra_headers", {})
    if extra_hdrs:
        print(f"  Extra hdrs: {', '.join(extra_hdrs.keys())} (values not shown)")
    print(f"  Auth edges: {'enabled' if auth_edges_run else 'disabled (run_auth_edges=false)'}")
    print(f"  Timeout:    {cfg.get('timeout_s', 15)}s")
    print(f"  Output:     {output_dir}")
    print(f"  Log:        {log_file}")
    print(f"  Timestamp:  {ts}")
    for p in parameters:
        override = "per-param override" if p.get("tier3_edges_override") else f"{total_shared_edges} shared"
        companions_str = ""
        if p.get("pinned_companions"):
            companions_str = ", companions: " + ", ".join(
                f"{c['name']}={c['value']}" for c in p["pinned_companions"]
            )
        print(f"    {p['name']}: {len(p['tier1_values'])} tier1, {override} edges{companions_str}")
    print(f"  Tier 4 adversarial: {len(cfg.get('tier4_adversarial', []))}")
    print(f"  Max throttle retries per call: {MAX_THROTTLE_RETRIES}")
    print(f"  Inter-call delay: {INTER_CALL_DELAY_S}s")
    if not is_v2_compat:
        print(f"  Independence declared: {cfg.get('parameters_independence_declared')}")
    print(f"  {SCOPE_NOTE}")

    t_start = time.monotonic()

    # Per-parameter categories
    for p in parameters:
        print(f"\n{'=' * 70}")
        print(f"  PARAMETER: {p['name']}" + (f" — {p.get('purpose', '')}" if p.get("purpose") else ""))
        print(f"{'=' * 70}")
        run_per_param_categories(p, cfg, api_key, output_dir, log_file, ts)

    # Endpoint-level categories
    print(f"\n{'=' * 70}")
    print(f"  ENDPOINT-LEVEL PROBES")
    print(f"{'=' * 70}")
    run_endpoint_categories(cfg, api_key, output_dir, log_file, ts, parameters[0])

    wall = time.monotonic() - t_start

    print(f"\n{'=' * 70}")
    print(f"  Run complete in {wall:.1f}s")
    print(f"{'=' * 70}")
    print(f"  Log:   {log_file}")
    print(f"  Raw:   {output_dir}/")

    if not args.no_analysis:
        print_analysis(log_file, auth_edges_run, parameters)

    print(f"\n  Next: analyze the JSONL, write findings.md (with cross-parameter + per-parameter "
          f"sections), then policies.md, then report.html, then verify parity.")


if __name__ == "__main__":
    main()
