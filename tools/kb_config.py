#!/usr/bin/env python3
"""kb_config.py — the one reader of KB/kb.json, the instance settings every tool shares.

Every key is optional and has a neutral default, so a bare KB/ folder works. Path keys are relative
to the instance root (the folder holding KB/). Unknown keys are ignored. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import json
from pathlib import Path

CONFIG = "KB/kb.json"
DEFAULTS = {
    "owner": "owner",                                # the one human id that endorses lands (lowercase)
    "title": "Knowledge Base",                       # shown in the search dashboard header
    "require_signed_lands": False,
    "allowed_signers": "",
    "agents": [],                                    # extra agent ids (UPPERCASE) allowed to propose
    "agents_glob": "agents/*/soul.md",               # each match's parent folder name is an agent id
    "dashboard": "KB/output/kb-search.html",         # kb-index writes the search page here
    "regressions": "evals/regressions.jsonl",        # kb-eval --regressions cases; land gates on it
    "baseline": "evals/kb-health-baseline.json",     # lint + doctor baselines
    "catalog": "KB/CATALOG.md",                      # optional page whose **Articles:** count land bumps
    "registry": "skills/REGISTRY.md",                # optional skill table for skill: consumers
    "router": "config/router.json",                  # optional {"registered_names": [...]} for agent: consumers
    "spine": "KB/spine.md",                          # optional hand-written theme map for graph-query themes
}
PATH_KEYS = ("agents_glob", "dashboard", "regressions", "baseline", "catalog", "registry", "router", "spine")


def load(root: Path) -> dict:
    """Defaults overlaid with KB/kb.json. Raises ValueError on invalid JSON."""
    cfg = dict(DEFAULTS)
    p = Path(root) / CONFIG
    if p.is_file():
        data = json.loads(p.read_text(encoding="utf-8"))
        cfg.update({k: v for k, v in data.items() if k in cfg})
    return cfg


def rel(root: Path, key: str) -> str:
    """Root-relative path string for a path key."""
    try:
        return str(load(root)[key])
    except ValueError:
        return DEFAULTS[key]


def path(root: Path, key: str) -> Path:
    return Path(root) / rel(root, key)
