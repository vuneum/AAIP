#!/usr/bin/env python3
"""
AAIP + AEP Demo
===============
One command. Full agent economy loop.

    python demo.py
    python demo.py "Your custom task here"
    python demo.py --fast
"""

import sys
import pathlib

# Make local package importable without install
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from aaip.orchestrator import run_demo_task

if __name__ == "__main__":
    argv = sys.argv[1:]
    fast = "--fast" in argv
    argv = [a for a in argv if a != "--fast"]
    task = " ".join(argv) if argv else "Analyse Q1 2026 earnings across FAANG companies"
    run_demo_task(task=task, fast=fast)
