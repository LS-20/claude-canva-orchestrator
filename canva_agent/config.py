"""Environment loading, model mapping, and pricing."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
ENV_EXAMPLE_PATH = PROJECT_ROOT / ".env.example"

MODEL_SHORTNAMES: dict[str, str] = {
    "haiku": "claude-haiku-4-5",
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-7",
}

# USD per 1M tokens (input, output)
PRICING_PER_MILLION: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-7": (5.0, 25.0),
}

DEFAULT_ANALYSIS_MODEL = "sonnet"
DEFAULT_BUILD_MODEL = "sonnet"

MCP_BETA = "mcp-client-2025-11-20"
CANVA_MCP_URL = "https://mcp.canva.com/mcp"


def resolve_model(shortname: str) -> str:
    key = shortname.lower().strip()
    if key not in MODEL_SHORTNAMES:
        valid = ", ".join(MODEL_SHORTNAMES)
        raise ValueError(f"Unknown model '{shortname}'. Choose from: {valid}")
    return MODEL_SHORTNAMES[key]


def estimate_cost(model_id: str, input_tokens: int = 2000, output_tokens: int = 1500) -> float:
    """Rough per-call cost estimate in USD."""
    rates = PRICING_PER_MILLION.get(model_id)
    if not rates:
        return 0.0
    inp_rate, out_rate = rates
    return (input_tokens / 1_000_000) * inp_rate + (output_tokens / 1_000_000) * out_rate


def format_cost_estimate(shortname: str) -> str:
    model_id = resolve_model(shortname)
    cost = estimate_cost(model_id)
    return f"~${cost:.3f}"


def ensure_env(interactive: bool = True) -> None:
    """Load .env or guide the user to create one."""
    if ENV_PATH.exists():
        load_dotenv(ENV_PATH)
        return

    print("\nMissing .env file")
    print("This project needs API keys in a local .env file (never committed to git).")
    print(f"  1. Copy {ENV_EXAMPLE_PATH.name} to .env")
    print("  2. Add your Anthropic API key and Canva access token")
    print(f"  3. See README.md for setup help\n")

    if interactive and ENV_EXAMPLE_PATH.exists():
        try:
            answer = input("Create .env from .env.example now? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer in ("y", "yes"):
            shutil.copy(ENV_EXAMPLE_PATH, ENV_PATH)
            print(f"Created {ENV_PATH.name}. Edit it with your real keys, then run again.")
        else:
            print("No .env created. Exiting.")

    sys.exit(1)


def get_api_key() -> str:
    ensure_env(interactive=False)
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key or key.startswith("sk-ant-your-key"):
        print("ANTHROPIC_API_KEY is missing or still a placeholder in .env")
        sys.exit(1)
    return key


def get_canva_token() -> str:
    ensure_env(interactive=False)
    token = os.environ.get("CANVA_ACCESS_TOKEN", "").strip()
    if not token or token.startswith("your-canva"):
        print("CANVA_ACCESS_TOKEN is missing or still a placeholder in .env")
        print("See README.md → 'Getting your Canva access token'")
        sys.exit(1)
    return token


def load_env() -> None:
    """Public entry: load env or exit with guidance."""
    ensure_env(interactive=True)
    load_dotenv(ENV_PATH)
