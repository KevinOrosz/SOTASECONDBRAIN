#!/usr/bin/env python3
"""kb_testkit.py — the shared miniature-KB fixture for the second-brain loop suites.

fixture(tmp, ...) builds a throwaway repo under tmp and returns its root:
  KB/wiki (routing + 2 taxonomy + 3 typed articles, 0 FAIL / 0 WARN under kb-lint), KB/RAW, KB/output
              index pages carry the live anchors kb-write land bumps: Status, category rows, Recent
              Updates, Articles, | [[stem]] | claim | rows; KB/CATALOG.md carries **Articles:**
              KB/output/retrieval-eval.json: 2 hand-labeled questions for kb-eval
  indexes     KB/output/kb-index.json, content-seeds.json, kb-graph.json, KB/output/kb-search.html
  git         git init + one commit of the whole tree (kb-write unland reads prior bytes from git)
  registry    skills/REGISTRY.md (one LIVE, one DRAFT, one RETIRED skill)
  router      config/router.json (registered_names = agents)
  baseline    evals/kb-health-baseline.json (graph + staleness_days; no lint key)
  loglog      logs/loop-log.md (header + empty Runs table)
  agents      agents/{NAME}/soul.md
tree_digest(path) hashes a tree for non-mutation proofs.

Every suite imports this (spec §1.1); test-kb-graph.py keeps its own fixture. Index builds run
with root=<fixture>, so the live KB/output/kb-search.html is never touched.
regressions=True writes evals/regressions.jsonl (REGRESSION_CASES: one active retrieval case that forbids
stem "fourth" for a query only that page would match, one active artifact case, one dormant answer case).
spine / progress raise until the first suite that consumes them defines their shape.
Stdlib only, Python 3.9 compatible.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import subprocess
from pathlib import Path

TOOLS = Path(__file__).resolve().parent

WIKI = {
    "_index.md": """# KB Index

**Updated:** 2026-01-01
**Type:** routing
**Status:** 3 articles | fixture

## Categories

| Category | Articles | Scope |
|----------|----------|-------|
| [[alpha/_index | alpha]] | 2 | First and second |
| [[beta/_index | beta]] | 1 | Third |

## Recent Updates
| Date | Article | Action |
|------|---------|--------|
| 2026-01-03 | [[third]] | created |
""",
    "alpha/_index.md": """# Alpha

**Articles:** 2
**Updated:** 2026-01-01
**Type:** taxonomy

| Article | Core Claim |
|---------|------------|
| [[first]] | First claim here. |
| [[second]] | Second claim. |
""",
    "alpha/first.md": """# First

**Category:** alpha
**Sources:** [[RAW/source-one.md]]
**Updated:** 2026-01-01
**Type:** article
**Depends-On:** second
**Consumers:** skill:brain-think, agent:RESEARCHER
**Confidence:** high
**Last-Verified:** 2026-01-02

## Core Claim
First claim here.

## Evidence
Body text mentioning zebrafish only here.

## Connections
- [[second]] — the relation prose
""",
    "alpha/second.md": """# Second

**Category:** alpha
**Sources:** [[RAW/source-two.md]]
**Updated:** 2026-01-02
**Type:** article

## Core Claim
Second claim.

## Connections
- [[first]] — points back
""",
    "beta/_index.md": """# Beta

**Articles:** 1
**Updated:** 2026-01-03
**Type:** taxonomy

| Article | Core Claim |
|---------|------------|
| [[third]] | Third claim. |
""",
    "beta/third.md": """# Third

**Category:** beta
**Sources:** [[RAW/source-one.md]]
**Updated:** 2026-01-03
**Type:** article
**Confidence:** moderate
**Provenance:** inbox RESEARCHER/2026-01-03-third · proposed RESEARCHER · endorsed owner 2026-01-03 · ledger 1

## Core Claim
Third claim.
""",
}

RAW = {"source-one.md": "raw one\n", "source-two.md": "raw two\n"}

CATALOG = """# KB CATALOG (fixture)

**Articles:** 3 canonical (excludes 3 `_index.md`)
"""

RETRIEVAL_EVAL = {
    "note": "fixture gold, written from titles and claims",
    "questions": [
        {"id": 1, "shape": "lookup", "q": "first claim", "gold": ["first"]},
        {"id": 2, "shape": "body", "q": "zebrafish", "gold": ["first"]},
    ],
}

REGISTRY = """# Skill Registry (fixture)

| # | Skill | Area | Tier | Trigger | Min model | Agent | Status |
|---|-------|------|------|---------|-----------|-------|--------|
| 1 | `brain-think` | knowledge | S | Answer from the KB | mid | RESEARCHER | LIVE |
| 2 | `kb-ingest` | knowledge | S | New canon material | mid | RESEARCHER | DRAFT — unproven |
| 3 | `content-repurpose` | content | A | RETIRED into REPURPOSER | — | REPURPOSER | RETIRED (canonical: agents/REPURPOSER/program.md) |
"""

BASELINE = {
    "captured": "2026-01-01",
    "article_count": 3,
    "graph": {"internal_occurrences": 4, "resolved_occurrences": 4, "unresolved_occurrences": 0,
              "resolution_rate": 100.0},
    "staleness_days": 90,
    "note": "fixture baseline",
}

def _case(**kw):
    base = {"q": "", "expected": [], "forbidden": [], "landed": "2026-01-01", "status": "active",
            "gold_source": "evidence-scan", "gold_locked": "", "evidence_stems": [], "named_stems": [],
            "retrieval_at": "", "pages": [], "targets": [], "ranker": "kb-query", "k": 10,
            "failing_version": "seed", "landed_version": "seed", "ledger_seq": None}
    base.update(kw)
    return base


REGRESSION_CASES = [
    _case(id="r-0001", kind="retrieval", q="inbox write-back gate ledger seal", forbidden=["fourth"],
          origin="correction:C-0001"),
    _case(id="r-0002", kind="retrieval", q="first claim", expected=["first"], origin="correction:C-0002",
          evidence_stems=["first"], gold_locked="2026-01-01T00:00:00Z", retrieval_at="2026-01-01T00:00:01Z"),
    _case(id="r-0003", kind="artifact", origin="rule:no-parity-word", gold_source="rules",
          targets=["KB/CATALOG.md"], expected=["Articles:"], forbidden=["\\bparity\\b"]),
    _case(id="r-0004", kind="answer", q="how is voice judged", expected=["literal and direct"],
          origin="rule:fixture-voice", gold_source="rules", status="dormant"),
]

LOOP_LOG = """# ORCHESTRATOR Loop Log

## Runs

| Date | Agent | Mode | Topic | Type | Score | Iters | Result | Notes |
|------|-------|------|-------|------|-------|-------|--------|-------|
"""


def load(name: str):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_")[:-3], TOOLS / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def tree_digest(path: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(Path(path).rglob("*")):
        if p.is_file():
            h.update(p.relative_to(path).as_posix().encode("utf-8"))
            h.update(p.read_bytes())
    return h.hexdigest()


def state_digest(root: Path) -> dict:
    """rel -> sha256 of every file under KB/ and evals/, minus what recovery itself owns (the ledger,
    _objects/, _ops/): equal before an op and after its rollback means byte-identical restored state."""
    skip = ("KB/inbox/_ledger.jsonl", "KB/inbox/_objects/", "KB/inbox/_ops/")
    out = {}
    for top in ("KB", "evals"):
        for p in sorted((Path(root) / top).rglob("*")):
            rel = p.relative_to(root).as_posix()
            if p.is_file() and not rel.startswith(skip):
                out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def fixture(tmp, *, indexes=True, registry=True, router=True, baseline=True, loglog=True,
            agents=("RESEARCHER", "ORCHESTRATOR", "BUILDER"), git=False, spine=False, progress=False, regressions=False) -> Path:
    for flag, name in ((spine, "spine"), (progress, "progress")):
        if flag:
            raise NotImplementedError(name + "=True: shape lands with the first suite that consumes it")
    root = Path(tmp) / "repo"
    for rel, text in WIKI.items():
        _write(root / "KB" / "wiki" / rel, text)
    for name, text in RAW.items():
        _write(root / "KB" / "RAW" / name, text)
    _write(root / "KB" / "CATALOG.md", CATALOG)
    _write(root / "KB" / "output" / "retrieval-eval.json", json.dumps(RETRIEVAL_EVAL, indent=1) + "\n")
    if regressions:
        _write(root / "evals" / "regressions.jsonl",
               "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in REGRESSION_CASES))
    if registry:
        _write(root / "skills" / "REGISTRY.md", REGISTRY)
    if router:
        _write(root / "config" / "router.json",
               json.dumps({"registered_names": list(agents)}, indent=2) + "\n")
    if baseline:
        _write(root / "evals" / "kb-health-baseline.json", json.dumps(BASELINE, indent=2) + "\n")
    if loglog:
        _write(root / "logs" / "loop-log.md", LOOP_LOG)
    for name in agents:
        _write(root / "agents" / name / "soul.md", "# %s — Soul (fixture)\n" % name)
    if indexes:
        with contextlib.redirect_stdout(io.StringIO()):
            if load("kb-index.py").build(root) != 0:
                raise RuntimeError("fixture kb-index build failed")
        out = root / "KB" / "output"
        graph, errors = load("kb-graph.py").build(root, out, quiet=True)
        if graph is None or errors:
            raise RuntimeError("fixture kb-graph build failed: %s" % errors)
        (out / "kb-graph.json").write_text(json.dumps(graph, ensure_ascii=False, indent=1), encoding="utf-8")
    if git:
        for args in (["init", "-q"], ["add", "-A"],
                     ["-c", "user.name=fixture", "-c", "user.email=fixture@localhost", "-c", "commit.gpgsign=false",
                      "-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "fixture"]):
            subprocess.run(["git", "-C", str(root)] + args, check=True, capture_output=True)
    return root
