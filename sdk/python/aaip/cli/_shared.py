"""
aaip/cli/_shared.py
Shared utilities: colours, formatters, banner, client factory.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import click

# ── Colours ───────────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
BLUE   = "\033[94m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

def g(t: str) -> str: return f"{GREEN}{t}{RESET}"
def b(t: str) -> str: return f"{BLUE}{t}{RESET}"
def y(t: str) -> str: return f"{YELLOW}{t}{RESET}"
def r(t: str) -> str: return f"{RED}{t}{RESET}"
def c(t: str) -> str: return f"{CYAN}{t}{RESET}"
def bold(t: str) -> str: return f"{BOLD}{t}{RESET}"
def dim(t: str) -> str: return f"{DIM}{t}{RESET}"

def tick(msg: str) -> None: click.echo(f"  {g('✓')} {msg}")
def fail(msg: str) -> None: click.echo(f"  {r('✗')} {msg}")
def info(msg: str) -> None: click.echo(f"  {b('→')} {msg}")
def warn(msg: str) -> None: click.echo(f"  {y('!')} {msg}")

def banner() -> None:
    click.echo(f"""
{CYAN}{BOLD}
  ░░░ AAIP — Autonomous Agent Infrastructure Protocol ░░░
{RESET}{DIM}  Identity · Discovery · Reputation · Payments{RESET}
""")

def get_client(api_key: str | None = None, base_url: str | None = None):
    from aaip.client import AAIPClient
    key = api_key or os.environ.get("AAIP_API_KEY", "")
    url = base_url or os.environ.get("AAIP_BASE_URL", "https://api.aaip.dev")
    return AAIPClient(api_key=key, base_url=url)

def load_manifest(path: str = ".aaip.json") -> dict | None:
    p = Path(path)
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return None

def save_manifest(data: dict, path: str = ".aaip.json") -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
