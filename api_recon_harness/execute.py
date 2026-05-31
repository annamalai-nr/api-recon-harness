"""Execute: optional preflight, then run the unchanged kernel runner.

The kernel owns redirect policy, throttle retries, raw-evidence capture and the
injection scan. This wrapper only sets the auth env var, times the run, counts
actual calls, and reports status. Budget is gated upstream (planned-only).
"""

import importlib.util
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from api_recon_harness.models import ProbeConfig
from api_recon_harness.paths import KERNEL_DIR


def _load_kernel():
    """Import the vendored probe_runner by path (reused unchanged)."""
    spec = importlib.util.spec_from_file_location("_probe_runner", KERNEL_DIR / "probe_runner.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def preflight(cfg: ProbeConfig, api_key: str) -> dict[str, int | None]:
    """One valid call per parameter so bad values fail before the full sweep.

    Uses the kernel's own no-redirect fetch so behavior matches the real run.
    """
    kernel = _load_kernel()
    headers = {cfg.auth_header: api_key}
    results: dict[str, int | None] = {}
    for p in cfg.parameters:
        params = {p["name"]: p["tier1_values"][0]}
        for c in p.get("pinned_companions", []):
            params[c["name"]] = c["value"]
        r = kernel.fetch(f"preflight_{p['name']}", cfg.base_url, cfg.endpoint,
                         params, "GET", headers, cfg.timeout_s)
        results[p["name"]] = r.get("status")
    return results


def run_probe(config_path: Path, api_key: str, env_var: str) -> tuple[int, str, str, str]:
    """Run the kernel runner as a subprocess. Returns (exit_code, started, ended, output)."""
    env = dict(os.environ)
    env[env_var] = api_key
    started = datetime.now().isoformat(timespec="seconds")
    proc = subprocess.run(
        [sys.executable, str(KERNEL_DIR / "probe_runner.py"), "--config", str(config_path)],
        capture_output=True, text=True, env=env,
    )
    ended = datetime.now().isoformat(timespec="seconds")
    return proc.returncode, started, ended, proc.stdout + proc.stderr


def count_calls(log_file: Path) -> int:
    if not log_file.exists():
        return 0
    return sum(1 for line in log_file.read_text(encoding="utf-8").splitlines() if line.strip())
