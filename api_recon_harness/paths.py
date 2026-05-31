"""Filesystem constants for the harness — single source of truth."""

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
KERNEL_DIR = PACKAGE_DIR / "kernel"
FRONTEND_DIR = PACKAGE_DIR / "frontend"
CONFIG_PATH = PACKAGE_DIR / "config.yaml"
OUTPUTS_DIR = PROJECT_ROOT / "outputs" / "api_recon"
RUNS_DIR = OUTPUTS_DIR / "runs"
ENV_PATH = PROJECT_ROOT / ".env"
