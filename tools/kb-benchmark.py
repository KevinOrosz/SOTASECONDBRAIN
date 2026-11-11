#!/usr/bin/env python3
"""Run local retrieval or compare versioned result files from an identical frozen corpus.
External systems supply the same result schema; this tool never calls a model or a remote service.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import time

def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EVAL = load("kb-eval.py")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def validate(run):
    if run.get("schema") != 1 or run.get("case_hash") != digest(run.get("cases")):
        raise ValueError("unsupported schema or changed cases")
    if not isinstance(run.get("corpus_hash"), str) or len(run["corpus_hash"]) != 64:
        raise ValueError("corpus_hash required")
    if not run.get("system") or not run.get("version") or not isinstance(run.get("configuration"), dict):
        raise ValueError("system, version and configuration required")
    if type(run.get("k")) is not int or run["k"] < 1:
        raise ValueError("positive k required")
    cases = run["cases"]
    if not isinstance(cases, list) or not cases:
        raise ValueError("non-empty cases required")
    ids = []
    for case in cases:
        if type(case.get("id")) not in (str, int) or case["id"] == "" or not isinstance(case.get("q"), str) or not case["q"].strip():
            raise ValueError("case needs id and question")
        gold = case.get("gold")
        if not isinstance(gold, list) or not gold or not all(isinstance(s, str) and s for s in gold) or len(set(gold)) != len(gold):
            raise ValueError("gold must contain unique non-empty page stems")
        ids.append(case["id"])
    results = run["results"]
    if len(set(ids)) != len(ids) or len(results) != len(ids) or {r["id"] for r in results} != set(ids):
        raise ValueError("duplicate or missing cases/results")
    for row in results:
        hits = row.get("hits")
        if not isinstance(hits, list) or not all(isinstance(s, str) for s in hits) or len(set(hits)) != len(hits) or len(hits) > run["k"]:
            raise ValueError("invalid ranked hits")
        ms = row.get("latency_ms")
        if type(ms) not in (int, float) or not math.isfinite(ms) or ms < 0:
            raise ValueError("finite non-negative latency_ms required")


def metrics(run):
    validate(run)
    rows = {r["id"]: r for r in run["results"]}
    recalls = [len(set(c["gold"]) & set(rows[c["id"]]["hits"])) / len(c["gold"]) for c in run["cases"]]
    latencies = sorted(r["latency_ms"] for r in rows.values())
    return {"system": run["system"], "version": run["version"], "cases": len(recalls), "k": run["k"],
            "mean_recall": sum(recalls) / len(recalls), "all_gold_rate": sum(x == 1 for x in recalls) / len(recalls),
            "p50_ms": latencies[(len(latencies)-1)//2], "p95_ms": latencies[math.ceil(len(latencies)*.95)-1]}


def compare(left, right):
    for run in (left, right):
        validate(run)
    for key in ("corpus_hash", "case_hash", "k"):
        if left[key] != right[key]:
            raise ValueError("not comparable: " + key + " differs")
    return {"left": metrics(left), "right": metrics(right),
            "scope": "retrieval only; no answer-quality or correction-recurrence claim"}


def run(root, cases_path, ranker, k):
    cases = json.loads(cases_path.read_text(encoding="utf-8"))["questions"]
    provenance = load("kb-provenance.py")
    checks = []
    provenance.check_index(root, provenance.inputs_hash(root), checks)
    if any(level != "PASS" for level, _ in checks):
        raise ValueError("index/graph missing or stale; run bin/kb index")
    before = EVAL.corpus_seal(root)
    result = {"schema": 1, "system": "SOTASECONDBRAIN", "version": EVAL.tools_hash(root),
              "configuration": {"ranker": ranker}, "corpus_hash": before, "case_hash": digest(cases),
              "cases": cases, "k": k, "results": []}
    # Check input before executing queries, including empty gold and duplicate ids.
    probe = dict(result, results=[{"id": c["id"], "hits": [], "latency_ms": 0} for c in cases])
    validate(probe)
    known = {p.stem for p in (root / "KB/wiki").rglob("*.md") if p.name != "_index.md"}
    if any(not set(c["gold"]) <= known for c in cases):
        raise ValueError("gold references a missing page")
    for case in cases:
        start = time.perf_counter()
        response = EVAL.ranked(root, case["q"], ranker, k)
        result["results"].append({"id": case["id"], "hits": [h["stem"] for h in response["results"]],
                                  "latency_ms": (time.perf_counter()-start)*1000,
                                  "retrieval": response["retrieval"]})
    if EVAL.corpus_seal(root) != before or EVAL.tools_hash(root) != result["version"]:
        raise ValueError("corpus or tools changed during run; discard results")
    validate(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="verb", required=True)
    p = sub.add_parser("run")
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    p.add_argument("--cases", type=Path, required=True)
    p.add_argument("--ranker", choices=("hybrid-graph", "kb-query"), default="hybrid-graph")
    p.add_argument("--k", type=int, default=6)
    p = sub.add_parser("compare")
    p.add_argument("left", type=Path)
    p.add_argument("right", type=Path)
    args = parser.parse_args()
    try:
        result = run(args.root.resolve(), args.cases, args.ranker, args.k) if args.verb == "run" else compare(
            json.loads(args.left.read_text()), json.loads(args.right.read_text()))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
