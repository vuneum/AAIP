"""
aaip/cli/__init__.py
AAIP CLI — entry point.

Commands are split into focused modules:
    identity.py   — init, register, status, doctor
    run.py        — run, verify, demo
    simulate.py   — simulate
    explorer.py   — explorer, explore
    leaderboard.py — leaderboard, discover, evaluate, wallet
"""

from __future__ import annotations

import click

from .explorer import explore, explorer
from .identity import doctor, init, register, status
from .leaderboard import discover, evaluate, leaderboard, wallet
from .run import demo, run, verify
from .simulate import simulate


@click.group()
@click.version_option(version=__import__("aaip").__version__, prog_name="aaip")
def cli() -> None:
    """AAIP — Autonomous Agent Infrastructure Protocol CLI"""
    pass


# Register all commands
cli.add_command(init)
cli.add_command(register)
cli.add_command(status)
cli.add_command(doctor)
cli.add_command(run)
cli.add_command(verify)
cli.add_command(demo)
cli.add_command(simulate)
cli.add_command(explorer)
cli.add_command(explore)
cli.add_command(leaderboard)
cli.add_command(discover)
cli.add_command(evaluate)
cli.add_command(wallet)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
