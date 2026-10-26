#!/usr/bin/env python3
"""Report unresolved KB wikilinks without mutating the canonical wiki.

Usage:
  python3 tools/kb-autolink.py [--json] [--wiki PATH]
  python3 tools/kb-autolink.py --apply  # intentionally blocked by KB doctrine

The resolver mirrors tools/verify.sh's global-stem semantics so both tools agree.
KB/SYSTEM.md requires source-backed 200-400 word articles and supervised index
updates, so unattended stub creation is deliberately unavailable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WIKI = ROOT / "KB" / "wiki"
LINK_RE = re.compile(r"(!?)\[\[([^\]]+)\]\]")
RAW_RE = re.compile(r"\[\[(RAW/[^\]|]+)")
SOURCES_LINE_RE = re.compile(r"^\*\*Sources:\*\*\s*(.+?)\s*$", re.M)
CATEGORY_PREFIX_RE = re.compile(r"^[a-z-]+/")
KEBAB_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _relative(path: Path, wiki: Path) -> str:
    try:
        return path.relative_to(wiki).as_posix()
    except ValueError:
        return path.as_posix()


def _known_targets(wiki: Path) -> tuple[set[str], set[str], int, int]:
    markdown = sorted(wiki.rglob("*.md"))
    articles = [path for path in markdown if path.name != "_index.md"]
    stems = {path.stem for path in articles}
    categories = {path.name for path in wiki.iterdir() if path.is_dir()}
    known = stems | categories | {"_index"}
    return known, categories, len(articles), len(markdown) - len(articles)


def _wiki_digest(wiki: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(wiki.rglob("*.md")):
        digest.update(path.relative_to(wiki).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _base_target(raw: str) -> str:
    target = raw.split("|", 1)[0].strip()
    if target.endswith(".md"):
        target = target[:-3]
    return target


def _classify(raw: str, embedded: bool, known: set[str]) -> dict[str, str]:
    target = _base_target(raw)
    if not target:
        return {"kind": "excluded", "reason": "empty", "target": target}
    if target.startswith("RAW/"):
        return {"kind": "excluded", "reason": "raw", "target": target}
    if re.match(r"^https?:", target):
        return {"kind": "excluded", "reason": "http", "target": target}

    normalized = CATEGORY_PREFIX_RE.sub("", target, count=1)
    result = {"target": target, "normalized": normalized}
    if normalized in known:
        return {**result, "kind": "resolved"}
    if embedded:
        return {**result, "kind": "blocked", "reason": "embed"}
    if target.startswith("/") or target.startswith("../") or "/../" in target:
        return {**result, "kind": "blocked", "reason": "path-traversal"}
    if "#" in normalized:
        return {**result, "kind": "blocked", "reason": "fragment"}
    if "^" in normalized:
        return {**result, "kind": "blocked", "reason": "block-reference"}
    if re.search(r"\s", normalized):
        return {**result, "kind": "loose", "reason": "prose-target"}
    if normalized != "_index" and not KEBAB_RE.fullmatch(normalized):
        return {**result, "kind": "blocked", "reason": "invalid-stem"}
    return {**result, "kind": "strict", "reason": "missing-stem"}


def scan(wiki: Path) -> dict:
    if not wiki.is_dir():
        raise FileNotFoundError(f"wiki directory not found: {wiki}")

    known, categories, article_count, index_count = _known_targets(wiki)
    grouped: dict[tuple[str, str, str], dict] = {}
    counts = defaultdict(int)
    wikilink_occurrences = 0
    internal_occurrences = 0
    resolved_occurrences = 0

    for path in sorted(wiki.rglob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        source_lines = SOURCES_LINE_RE.findall(text)
        raw_sources = sorted({source for line in source_lines for source in RAW_RE.findall(line)})
        source_category = path.parent.name if path.parent != wiki else ""
        source_rel = _relative(path, wiki)
        for line_number, line in enumerate(text.splitlines(), start=1):
            for match in LINK_RE.finditer(line):
                wikilink_occurrences += 1
                classified = _classify(match.group(2), bool(match.group(1)), known)
                kind = classified["kind"]
                counts[kind] += 1
                if kind == "excluded":
                    counts[f"excluded_{classified['reason']}"] += 1
                    continue
                internal_occurrences += 1
                if kind == "resolved":
                    resolved_occurrences += 1
                    continue

                key = (kind, classified.get("normalized", ""), classified.get("reason", ""))
                item = grouped.setdefault(
                    key,
                    {
                        "target": classified["target"],
                        "normalized": classified.get("normalized", ""),
                        "kind": kind,
                        "reason": classified.get("reason", ""),
                        "locations": [],
                        "categories": set(),
                        "raw_sources": set(),
                    },
                )
                item["locations"].append(
                    {
                        "path": source_rel,
                        "line": line_number,
                        "context": line.strip()[:240],
                    }
                )
                if source_category:
                    item["categories"].add(source_category)
                item["raw_sources"].update(raw_sources)

    findings = []
    for item in grouped.values():
        if item["kind"] == "strict":
            if len(item["categories"]) > 1 and "/" not in item["target"]:
                item["kind"] = "blocked"
                item["reason"] = "ambiguous-category"
            elif all(location["path"].endswith("_index.md") for location in item["locations"]):
                item["kind"] = "blocked"
                item["reason"] = "index-only-provenance"
        item["categories"] = sorted(item["categories"])
        item["raw_provenance_count"] = len(item.pop("raw_sources"))
        item["locations"] = sorted(item["locations"], key=lambda row: (row["path"], row["line"]))
        findings.append(item)

    findings.sort(key=lambda item: (item["kind"], item["normalized"], item["target"]))
    strict = [item for item in findings if item["kind"] == "strict"]
    loose = [item for item in findings if item["kind"] == "loose"]
    blocked = [item for item in findings if item["kind"] == "blocked"]
    unresolved_occurrences = internal_occurrences - resolved_occurrences
    resolution_rate = 100.0 if internal_occurrences == 0 else round(100 * resolved_occurrences / internal_occurrences, 2)

    return {
        "mode": "report-only",
        "wiki": str(wiki),
        "wiki_digest": _wiki_digest(wiki),
        "article_count": article_count,
        "index_count": index_count,
        "category_count": len(categories),
        "wikilink_occurrences": wikilink_occurrences,
        "internal_occurrences": internal_occurrences,
        "resolved_occurrences": resolved_occurrences,
        "unresolved_occurrences": unresolved_occurrences,
        "resolution_rate": resolution_rate,
        "unique_strict": len(strict),
        "unique_loose": len(loose),
        "unique_blocked": len(blocked),
        "excluded": {
            "raw": counts["excluded_raw"],
            "http": counts["excluded_http"],
            "empty": counts["excluded_empty"],
        },
        "strict": strict,
        "loose": loose,
        "blocked": blocked,
    }


def _print_human(report: dict) -> None:
    print(
        "KB AUTOLINK REPORT — "
        f"{report['article_count']} articles · {report['internal_occurrences']} internal links · "
        f"{report['resolution_rate']}% resolved"
    )
    print(
        f"strict={report['unique_strict']} · loose={report['unique_loose']} · "
        f"blocked={report['unique_blocked']} · mode=report-only"
    )
    for kind in ("strict", "loose", "blocked"):
        for item in report[kind]:
            locations = ", ".join(f"{row['path']}:{row['line']}" for row in item["locations"])
            print(f"[{kind.upper()}] {item['target']} ({item['reason']}) <- {locations}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wiki", type=Path, default=DEFAULT_WIKI, help="wiki directory (test seam; default KB/wiki)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--apply", action="store_true", help="blocked: canonical KB mutations require supervised kb-ingest")
    args = parser.parse_args(argv)

    if args.apply:
        print(
            "BLOCKED: --apply would create unsourced placeholder articles. "
            "KB/SYSTEM.md requires supervised, source-backed kb-ingest with atomic index updates.",
            file=sys.stderr,
        )
        return 2
    try:
        report = scan(args.wiki.resolve())
    except (OSError, ValueError) as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_human(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
