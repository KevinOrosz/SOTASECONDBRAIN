#!/usr/bin/env python3
"""Deterministic structural health check for the local knowledge files.

Checks:
  1. Source/index freshness: KB/wiki paths and SHA-256 source hashes exactly
     match kb-index.json. Indexed-field correctness and retrieval relevance are out of scope.
  2. Wikilink regression: current link resolution has not regressed from the
     committed Phase-5 baseline.
  3. Optional vector-artifact freshness: validate derived files if present;
     report N/A under the current P3-scrapped ruling.

Usage: python3 tools/brain-doctor.py [--json] [--root PATH] [--baseline PATH]
Stdlib only. Read-only. Exit: 0 PASS, 1 FAIL, 2 WARN.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
import kb_config  # noqa: E402
RESOLVER = Path(__file__).resolve().with_name("kb-autolink.py")


def _check(name: str, status: str, message: str) -> dict[str, str]:
    return {"name": name, "status": status, "message": message}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _disk_articles(root: Path) -> list[Path]:
    wiki = root / "KB" / "wiki"
    if not wiki.is_dir():
        raise FileNotFoundError(f"wiki directory missing: {wiki}")
    return sorted(path for path in wiki.rglob("*.md") if path.name != "_index.md")


def _retrieval_check(root: Path, articles: list[Path]) -> tuple[dict[str, str], dict[str, Any]]:
    index_path = root / "KB" / "output" / "kb-index.json"
    disk_paths = {path.relative_to(root).as_posix() for path in articles}
    metrics: dict[str, Any] = {"disk_articles": len(disk_paths)}
    try:
        index = _load_json(index_path)
        rows = index["articles"]
        if not isinstance(rows, list):
            raise TypeError("articles is not a list")
        indexed_paths = [row.get("path") for row in rows if isinstance(row, dict)]
        if len(indexed_paths) != len(rows) or any(not isinstance(path, str) or not path for path in indexed_paths):
            raise ValueError("one or more article rows lack a path")
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        return _check("retrieval", "FAIL", f"index unreadable or malformed: {exc}"), metrics

    path_counts = Counter(indexed_paths)
    indexed_set = set(indexed_paths)
    missing = sorted(disk_paths - indexed_set)
    ghosts = sorted(indexed_set - disk_paths)
    duplicates = sorted(path for path, count in path_counts.items() if count > 1)
    claim = index.get("article_count")
    metrics.update(
        {
            "index_articles": len(rows),
            "index_claim": claim,
            "path_coverage_pct": round(100 * len(disk_paths & indexed_set) / max(1, len(disk_paths)), 2),
            "missing_paths": missing,
            "ghost_paths": ghosts,
            "duplicate_paths": duplicates,
        }
    )
    faults: list[str] = []
    if claim != len(disk_paths) or len(rows) != len(disk_paths):
        faults.append(f"count disk={len(disk_paths)} rows={len(rows)} claim={claim}")
    if missing:
        faults.append(f"missing={len(missing)} ({', '.join(missing[:2])})")
    if ghosts:
        faults.append(f"ghost={len(ghosts)} ({', '.join(ghosts[:2])})")
    if duplicates:
        faults.append(f"duplicates={len(duplicates)} ({', '.join(duplicates[:2])})")

    indexed_hashes = {
        row["path"]: row.get("content_hash")
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("path"), str)
    }
    hash_drift = []
    for path in articles:
        rel = path.relative_to(root).as_posix()
        expected = indexed_hashes.get(rel)
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if not isinstance(expected, str) or expected != actual:
            hash_drift.append(rel)
    metrics["content_hash_drift"] = hash_drift
    if hash_drift:
        faults.append(f"content-hash drift={len(hash_drift)} ({', '.join(hash_drift[:2])})")

    newest_ns = max((path.stat().st_mtime_ns for path in articles), default=0)
    index_ns = index_path.stat().st_mtime_ns
    metrics["index_mtime_fresh"] = index_ns >= newest_ns

    if faults:
        return _check("retrieval", "FAIL", "; ".join(faults)), metrics
    return _check(
        "retrieval",
        "PASS",
        f"{len(disk_paths)}/{len(disk_paths)} article paths and hashes exact",
    ), metrics


def _resolver_scan(wiki: Path) -> dict[str, Any]:
    spec = importlib.util.spec_from_file_location("command_kb_autolink", RESOLVER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load resolver: {RESOLVER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.scan(wiki)


def _load_json_or_empty(path: Path) -> dict:
    """{} when the file is absent; raises on a file that exists but is not a JSON object."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _graph_check(root: Path, baseline_path: Path) -> tuple[dict[str, str], dict[str, Any]]:
    try:
        current = _resolver_scan(root / "KB" / "wiki")
    except (OSError, RuntimeError, ValueError) as exc:
        return _check("graph", "FAIL", f"resolver scan failed: {exc}"), {}

    metrics = {
        key: current[key]
        for key in (
            "article_count",
            "internal_occurrences",
            "resolved_occurrences",
            "unresolved_occurrences",
            "resolution_rate",
            "unique_strict",
            "unique_loose",
            "unique_blocked",
        )
    }
    if not baseline_path.exists() or "graph" not in _load_json_or_empty(baseline_path):
        # First run: record today's link counts as the baseline the next runs compare against.
        data = _load_json_or_empty(baseline_path)
        data["graph"] = {k: metrics[k] for k in ("internal_occurrences", "resolved_occurrences",
                                                  "unresolved_occurrences", "article_count")}
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return _check("graph", "PASS", f"baseline created at {baseline_path.name} (first run)"), metrics
    try:
        baseline = _load_json(baseline_path)
        base_graph = baseline["graph"]
        base_unresolved = int(base_graph["unresolved_occurrences"])
        base_internal = int(base_graph["internal_occurrences"])
        base_resolved = int(base_graph["resolved_occurrences"])
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        return _check("graph", "FAIL", f"baseline unreadable or malformed: {exc}"), metrics

    current_unresolved = int(current["unresolved_occurrences"])
    metrics["baseline_unresolved_occurrences"] = base_unresolved
    metrics["baseline_internal_occurrences"] = base_internal
    metrics["baseline_resolved_occurrences"] = base_resolved
    delta = current_unresolved - base_unresolved
    metrics["unresolved_delta"] = delta
    if delta > 0:
        return _check(
            "graph",
            "FAIL",
            f"unresolved links regressed by +{delta} ({base_unresolved} -> {current_unresolved})",
        ), metrics
    if current["internal_occurrences"] < base_internal or current["resolved_occurrences"] < base_resolved:
        return _check(
            "graph",
            "FAIL",
            "edge coverage regressed "
            f"(internal {base_internal} -> {current['internal_occurrences']}; "
            f"resolved {base_resolved} -> {current['resolved_occurrences']})",
        ), metrics
    if current_unresolved > 0:
        return _check(
            "graph",
            "WARN",
            f"no regression ({base_unresolved} -> {current_unresolved}), but unresolved links remain",
        ), metrics
    trend = "steady" if delta == 0 else f"improved by {-delta}"
    return _check(
        "graph",
        "PASS",
        f"{current['resolution_rate']}% resolved; unresolved {trend} at 0",
    ), metrics


def _embedding_manifest(meta: dict[str, Any]) -> dict[str, str]:
    """Optional vector rows must carry their source path and content hash."""
    rows = meta.get("articles")
    if not isinstance(rows, list):
        raise ValueError("metadata must contain an articles path/hash list")
    manifest: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("embedding article entry is not an object")
        path = row.get("path")
        digest = row.get("content_hash")
        if not isinstance(path, str) or not path or not isinstance(digest, str) or len(digest) != 64:
            raise ValueError("embedding article entry lacks path or SHA-256 content_hash")
        if path in manifest:
            raise ValueError(f"duplicate embedding path: {path}")
        manifest[path] = digest
    return manifest


def _embedding_check(root: Path, articles: list[Path]) -> tuple[dict[str, str], dict[str, Any]]:
    output = root / "KB" / "output"
    vectors = output / "kb-vectors.npy"
    meta_path = output / "kb-vectors-meta.json"
    present = (vectors.exists(), meta_path.exists())
    metrics: dict[str, Any] = {"vectors_present": present[0], "metadata_present": present[1]}
    if present == (False, False):
        return _check("embeddings", "N/A", "P3 scrapped; no vector artifacts present"), metrics
    if present[0] != present[1]:
        return _check("embeddings", "WARN", "partial vector artifacts: .npy and metadata must coexist"), metrics
    try:
        meta = _load_json(meta_path)
        if not isinstance(meta, dict):
            raise TypeError("metadata root is not an object")
        manifest = _embedding_manifest(meta)
        vectors_hash = meta.get("vectors_sha256")
        if not isinstance(vectors_hash, str) or len(vectors_hash) != 64:
            raise ValueError("metadata lacks vectors_sha256")
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return _check("embeddings", "WARN", f"metadata unreadable or malformed: {exc}"), metrics

    count = len(manifest)
    metrics["vector_count"] = count
    disk_manifest = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in articles
    }
    path_drift = sorted(set(disk_manifest) ^ set(manifest))
    hash_drift = sorted(path for path in set(disk_manifest) & set(manifest) if disk_manifest[path] != manifest[path])
    actual_vectors_hash = hashlib.sha256(vectors.read_bytes()).hexdigest()
    metrics["path_drift"] = path_drift
    metrics["content_hash_drift"] = hash_drift
    metrics["vectors_hash_match"] = actual_vectors_hash == vectors_hash
    newest_ns = max((path.stat().st_mtime_ns for path in articles), default=0)
    metrics["artifact_mtime_fresh"] = min(vectors.stat().st_mtime_ns, meta_path.stat().st_mtime_ns) >= newest_ns
    faults = []
    if count != len(articles):
        faults.append(f"count vectors={count} articles={len(articles)}")
    if meta.get("article_count") != count:
        faults.append(f"metadata article_count={meta.get('article_count')} manifest={count}")
    if path_drift:
        faults.append(f"path drift={len(path_drift)}")
    if hash_drift:
        faults.append(f"content-hash drift={len(hash_drift)}")
    if actual_vectors_hash != vectors_hash:
        faults.append("vectors_sha256 mismatch")
    if faults:
        return _check("embeddings", "WARN", "; ".join(faults)), metrics
    return _check("embeddings", "PASS", f"{count} vectors; path, source hashes, and vector hash exact"), metrics


def diagnose(root: Path, baseline_path: Path) -> dict[str, Any]:
    checks: list[dict[str, str]] = []
    metrics: dict[str, Any] = {}
    try:
        articles = _disk_articles(root)
    except OSError as exc:
        checks.append(_check("retrieval", "FAIL", str(exc)))
        return {"root": str(root), "status": "FAIL", "checks": checks, "metrics": metrics}

    retrieval, metrics["retrieval"] = _retrieval_check(root, articles)
    graph, metrics["graph"] = _graph_check(root, baseline_path)
    embeddings, metrics["embeddings"] = _embedding_check(root, articles)
    checks.extend((retrieval, graph, embeddings))
    if any(item["status"] == "FAIL" for item in checks):
        status = "FAIL"
    elif any(item["status"] == "WARN" for item in checks):
        status = "WARN"
    else:
        status = "PASS"
    return {"root": str(root), "status": status, "checks": checks, "metrics": metrics}


def _print_human(report: dict[str, Any]) -> None:
    print("BRAIN DOCTOR")
    for item in report["checks"]:
        print(f"[{item['status']}] {item['name']}: {item['message']}")
    print(f"RESULT: {report['status']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="instance root (test seam)")
    parser.add_argument("--baseline", type=Path, help="graph baseline JSON")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    baseline = args.baseline.resolve() if args.baseline else kb_config.path(root, "baseline")
    report = diagnose(root, baseline)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_human(report)
    return {"PASS": 0, "FAIL": 1, "WARN": 2}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
