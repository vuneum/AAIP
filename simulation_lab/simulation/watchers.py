"""
AAIP Simulation Lab — Watchers (standalone module)
Re-exports SimWatcher and build_watcher_set from validators.py for clean imports.
"""
from .validators import SimWatcher, build_watcher_set

__all__ = ["SimWatcher", "build_watcher_set"]
