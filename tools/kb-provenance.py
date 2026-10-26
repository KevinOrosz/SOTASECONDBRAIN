#!/usr/bin/env python3
"""Provenance and derived-output integrity (hardening PR3). Read-only, stdlib only, no model calls.

Usage:  python3 tools/kb-provenance.py --check [--root R] [--json]
Exit:   0 PASS · 2 WARN only · 1 any FAIL (the same contract as kb-graph --check and brain-doctor).

Checks:
  sources   every raw source recorded on a live ledger land event still exists in KB/RAW with the recorded
            sha256 (missing or drifted = FAIL). A landed page whose land event predates hashing = WARN.
  index     KB/output/kb-index.json and kb-graph.json carry inputs_hash (the wiki seal they were built from):
            unreadable or self-inconsistent = FAIL, absent / legacy / built from another wiki = WARN.
  caches    content-seeds.json and the search dashboard carry the same inputs_hash as the wiki now: else WARN.
  raw       a [[RAW/...]] Sources link on a wiki page that names no file in KB/RAW = WARN.
Every WARN and FAIL names the exact fix command.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kb_config  # noqa: E402

REBUILD = "bin/kb index"
RAW_LINK_RE = re.compile(r"\[\[(RAW/[^\]|#]+)")
SOURCES_RE = re.compile(r"^\*\*Sources:\*\*(.*)$", re.M)
DASH_RE = re.compile(r"<!-- inputs_hash: ([0-9a-f]{64}) -->")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def inputs_hash(root: Path) -> str:
    """sha256 over (path, sha256) of every KB/wiki/**/*.md except generated _index.md: what index + graph read."""
    wiki = root / "KB" / "wiki"
    rows = ["%s %s" % (p.relative_to(root).as_posix(), sha(p.read_bytes())) for p in sorted(wiki.rglob("*.md"))
            if p.name != "_index.md"]
    return sha("\n".join(rows).encode("utf-8"))


def raw_refs(text: str, source_refs=()) -> list:
    """Normalised raw source names ('garden-journal.md') from a page's Sources lines plus raw: proposal refs."""
    out = set()
    for line in SOURCES_RE.findall(text):
        out.update(m[len("RAW/"):].strip() for m in RAW_LINK_RE.findall(line))
    out.update(r[len("raw:"):] for r in source_refs if isinstance(r, str) and r.startswith("raw:"))
    return sorted(out)


def raw_path(root: Path, name: str):
    base = (root / "KB" / "RAW").resolve()
    p = (base / name).resolve()
    if not str(p).startswith(str(base) + "/"):
        return None
    if p.is_file():
        return p
    md = p.with_name(p.name + ".md")
    return md if md.is_file() else None


def hash_sources(root: Path, names) -> tuple:
    """({name: sha256}, [missing names]) for raw source names at land time."""
    got, missing = {}, []
    for n in names:
        p = raw_path(root, n)
        if p is None:
            missing.append(n)
        else:
            got[n] = sha(p.read_bytes())
    return got, missing


def _ledger(root: Path) -> list:
    path = root / "KB" / "inbox" / "_ledger.jsonl"
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def check_sources(root: Path, out: list) -> None:
    rows = _ledger(root)
    last = {}
    for r in rows:
        if r.get("event") in ("land", "unland"):
            last[r.get("id")] = r
    bad = legacy = good = 0
    for pid, r in sorted(last.items(), key=lambda kv: str(kv[0])):
        if r.get("event") != "land":
            continue
        if "sources" not in r:
            pages = [p for p in r.get("files", {}) if p.startswith("KB/wiki/") and not p.endswith("_index.md")]
            if any(raw_refs((root / p).read_text(encoding="utf-8", errors="replace"))
                   for p in pages if (root / p).is_file()):
                legacy += 1
            continue
        for name, digest in sorted(r["sources"].items()):
            p = raw_path(root, name)
            if p is None:
                bad += 1
                out.append(("FAIL", "sources: %s (landed by ledger %s) is missing from KB/RAW — restore it from "
                            "backup or git (git checkout -- KB/RAW/%s)" % (name, r.get("seq"), name)))
            elif sha(p.read_bytes()) != digest:
                bad += 1
                out.append(("FAIL", "sources: KB/RAW/%s drifted since ledger %s landed it (want %s) — restore "
                            "the original bytes; RAW is append-only" % (name, r.get("seq"), digest[:12])))
            else:
                good += 1
    if legacy:
        out.append(("WARN", "sources: %d landed page(s) predate source hashing (no hashes on their land event); "
                    "re-land or supersede to record them" % legacy))
    if not bad:
        out.append(("PASS", "sources: %d recorded raw source hash(es) match KB/RAW" % good))


def _load_json(path: Path, name: str, out: list):
    if not path.exists():
        out.append(("WARN", "%s absent — run %s" % (name, REBUILD)))
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as e:
        out.append(("FAIL", "%s unreadable (%s) — delete it and run %s" % (name, e, REBUILD)))
        return None


def check_index(root: Path, now: str, out: list) -> None:
    outd = root / "KB" / "output"
    idx = _load_json(outd / "kb-index.json", "kb-index.json", out)
    if idx is not None:
        arts = idx.get("articles")
        if not isinstance(arts, list) or idx.get("article_count") != len(arts) or any(
                not isinstance(a, dict) or not a.get("path") or not a.get("content_hash") for a in arts):
            out.append(("FAIL", "kb-index.json corrupt (article_count or rows inconsistent) — run %s" % REBUILD))
        elif "inputs_hash" not in idx:
            out.append(("WARN", "kb-index.json is legacy (no inputs_hash) — run %s" % REBUILD))
        elif idx["inputs_hash"] != now:
            out.append(("WARN", "kb-index.json stale: built from another wiki state — run %s" % REBUILD))
        else:
            out.append(("PASS", "kb-index.json built from the current wiki (%d articles)" % len(arts)))
    g = _load_json(outd / "kb-graph.json", "kb-graph.json", out)
    if g is not None:
        if not isinstance(g.get("nodes"), dict) or not isinstance(g.get("manifest"), list):
            out.append(("FAIL", "kb-graph.json corrupt (nodes or manifest missing) — run %s" % REBUILD))
        elif "inputs_hash" not in g:
            out.append(("WARN", "kb-graph.json is legacy (no inputs_hash) — run %s" % REBUILD))
        elif g["inputs_hash"] != now:
            out.append(("WARN", "kb-graph.json stale: built from another wiki state — run %s" % REBUILD))
        else:
            out.append(("PASS", "kb-graph.json built from the current wiki"))


def check_caches(root: Path, now: str, out: list) -> None:
    seeds = root / "KB" / "output" / "content-seeds.json"
    if seeds.is_file():
        try:
            got = json.loads(seeds.read_text(encoding="utf-8")).get("inputs_hash")
        except (ValueError, OSError):
            got = "unreadable"
        if got != now:
            out.append(("WARN", "content-seeds.json stale or legacy — run %s" % REBUILD))
    dash = kb_config.path(root, "dashboard")
    if dash.is_file():
        m = DASH_RE.search(dash.read_text(encoding="utf-8", errors="replace"))
        if not m or m.group(1) != now:
            out.append(("WARN", "search dashboard %s stale or legacy — run %s"
                        % (dash.relative_to(root).as_posix() if dash.is_relative_to(root) else dash, REBUILD)))
    wiki = root / "KB" / "wiki"
    dangling = set()
    for p in sorted(wiki.rglob("*.md")):
        if p.name == "_index.md":
            continue
        for n in raw_refs(p.read_text(encoding="utf-8", errors="replace")):
            if raw_path(root, n) is None:
                dangling.add("%s -> RAW/%s" % (p.relative_to(root).as_posix(), n))
    for d in sorted(dangling):
        out.append(("WARN", "raw: %s names no file in KB/RAW — add the source file or fix the Sources line "
                    "via a supersede (bin/kb write put --supersedes ...)" % d))
    if not any(lvl != "PASS" and msg.startswith(("content-seeds", "search dashboard", "raw:")) for lvl, msg in out):
        out.append(("PASS", "caches: seeds and dashboard match the wiki; every RAW Sources link resolves"))


def check(root: Path) -> list:
    out = []
    if not (root / "KB" / "wiki").is_dir():
        return [("FAIL", "no KB/wiki under %s — run ./bootstrap.sh" % root)]
    now = inputs_hash(root)
    check_sources(root, out)
    check_index(root, now, out)
    check_caches(root, now, out)
    return out


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="Provenance + derived-output integrity gate (0 PASS / 2 WARN / 1 FAIL).")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--check", action="store_true", help="run every check (the default)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv[1:])
    res = check(Path(a.root).resolve())
    levels = {lvl for lvl, _ in res}
    rc = 1 if "FAIL" in levels else 2 if "WARN" in levels else 0
    if a.json:
        print(json.dumps({"rc": rc, "checks": [{"level": l, "detail": d} for l, d in res]}, indent=1))
    else:
        for lvl, d in res:
            print("%-5s %s" % (lvl, d))
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
