"""Filesystem constants for the harness — single source of truth."""

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
KERNEL_DIR = PACKAGE_DIR / "kernel"
# Frontend lives outside the Python package, as a top-level sibling of the
# backend — a PROJECT_ROOT-relative resource like `outputs/` and `.env`.
FRONTEND_DIR = PROJECT_ROOT / "frontend"
CONFIG_PATH = PACKAGE_DIR / "config.yaml"
OUTPUTS_DIR = PROJECT_ROOT / "outputs" / "api_recon"
RUNS_DIR = OUTPUTS_DIR / "runs"
ENV_PATH = PROJECT_ROOT / ".env"
