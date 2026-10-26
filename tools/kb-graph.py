#!/usr/bin/env python3
"""kb-graph.py — build the KB knowledge graph from what is already hand-authored.

Reads:  KB/output/kb-index.json   (structure kb-index.py already parsed — never re-derived)
        KB/wiki/**/*.md           (for what the index throws away: section bodies, relation prose)
        KB/RAW/*.md               (RawSource nodes come from disk, NOT from what the wiki cites)
        KB/output/kb-edge-types.json  (optional typed-edge cache; absent = every edge RELATES_TO)
        KB/output/kb-gazetteer.json   (optional entity alias list; absent = no MENTIONS edges)
Writes: KB/output/kb-graph.json   (structure only — section bodies stay on disk)

Design rulings (2026-08-12):
  - No LLM at build time. The graph is hand-authored: 1,674 wikilinks with prose relation
    sentences, 12 curated categories, 6 pillar papers. Re-deriving it with an extractor
    would be strictly worse than what is on disk.
  - Links are scanned GLOBALLY, not scoped to '## Connections'. 113 articles use
    '## Related' instead; a section-scoped parser silently loses 22.5% of the graph.
  - RawSource nodes enumerate KB/RAW in full so the never-compiled sources are a visible
    gap list rather than silence.
  - Edge TYPE is not regexable (606 distinct relation-prose first words). Types come from
    an optional offline cache keyed by content_hash; the graph degrades to an honest
    untyped RELATES_TO with a prose payload when the cache is missing or stale.

Read-only over KB/wiki and KB/RAW. Stdlib only, Python 3.9 compatible.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

BUILDER_VERSION = "1.0"

LINK_RE = re.compile(r"(!?)\[\[([^\]]+)\]\]")
SECTION_RE = re.compile(r"^(#{2,3})\s+(.+?)\s*$", re.M)
H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.M)
META_RE = re.compile(r"^\*\*(Category|Sources|Updated|Tags):\*\*\s*(.+?)\s*$", re.M)
# Link-first bullet carrying a prose relation payload. Payload may be empty (11.3% are bare).
BULLET_RE = re.compile(r"^\s*[-*]\s*\[\[([^\]]+)\]\]\s*(?:[—–:-]\s*)?(.*)$")
CLAIM_RE = re.compile(r"^##\s+Core Claim\s*$(.*?)(?=^##\s|\Z)", re.M | re.S)
OPENQ_RE = re.compile(r"^##\s+Open Questions?\s*$(.*?)(?=^##\s|\Z)", re.M | re.S)

# A relation prose payload shorter than this is treated as a bare link (no semantic content).
MIN_PROSE = 3


# --- temporal layer -------------------------------------------------------------
# Only 34% of KB/RAW carries any date signal (measured 2026-08-13: 13% in filenames,
# 24% in content). So the temporal layer is DECLARED SPARSE rather than inferred: a node
# gets a date only when one is actually written down, and precision is recorded with it.
# Undated sources are 'none' — never guessed from mtime, which reflects the Evernote export,
# not when the owner wrote it.
DATE_PATS = [
    (re.compile(r"(20[0-2]\d)-(\d{2})-(\d{2})"), "day", lambda m: (int(m.group(1)), int(m.group(2)), int(m.group(3)))),
    (re.compile(r"\b(\d{1,2})[-/](\d{1,2})[-/](20\d{2}|\d{2})\b"), "day", lambda m: (
        (2000 + int(m.group(3))) if len(m.group(3)) == 2 else int(m.group(3)), int(m.group(1)), int(m.group(2)))),
    (re.compile(r"\b(20[0-2]\d)\b"), "year", lambda m: (int(m.group(1)), 0, 0)),
]


def extract_date(name: str, text: str):
    """Return (iso_or_year_string, precision, where). Filename wins over content."""
    for src, where in ((name, "filename"), (text[:4000], "content")):
        for pat, prec, conv in DATE_PATS:
            m = pat.search(src)
            if not m:
                continue
            try:
                y, mo, d = conv(m)
            except (ValueError, IndexError):
                continue
            if not (2005 <= y <= 2030):
                continue
            if prec == "day" and 1 <= mo <= 12 and 1 <= d <= 31:
                return ("%04d-%02d-%02d" % (y, mo, d), "day", where)
            return ("%04d" % y, "year", where)
    return ("", "none", "")


# --- duplicate detection ------------------------------------------------------
# Note exports often leave byte-variant COPIES of files the wiki already cites
# ("Chapter II_Notes.md" duplicating "Chapter 2 - Notes.md"). Reporting those as "never compiled"
# overstates the gap, so they are
# detected and labelled rather than counted as missing work. Containment, not Jaccard: a short
# excerpt fully inside a long cited file is still a duplicate.
SHINGLE_K = 8
DUP_THRESHOLD = 0.60


def shingles(text: str):
    words = re.findall(r"[a-z0-9']+", text.lower())
    if len(words) < SHINGLE_K:
        return set()
    return {hash(" ".join(words[i:i + SHINGLE_K])) for i in range(len(words) - SHINGLE_K + 1)}


def mark_duplicates(raw_nodes: dict, raw_text: dict):
    """Label each uncited RAW file that is >=60% contained in a cited one."""
    cited = [n for n, v in raw_nodes.items() if v["cited_by"]]
    uncited = [n for n, v in raw_nodes.items() if not v["cited_by"]]
    sig = {n: shingles(raw_text.get(n, "")) for n in cited + uncited}
    inverted = defaultdict(list)
    for n in cited:
        for s in sig[n]:
            inverted[s].append(n)
    for n in uncited:
        if not sig[n]:
            continue
        overlap = Counter()
        for s in sig[n]:
            for c in inverted.get(s, ()):
                overlap[c] += 1
        best, score = "", 0.0
        for c, ov in overlap.items():
            denom = max(1, min(len(sig[n]), len(sig[c])))
            if ov / denom > score:
                score, best = ov / denom, c
        if score >= DUP_THRESHOLD:
            raw_nodes[n]["duplicate_of"] = best
            raw_nodes[n]["duplicate_score"] = round(score, 3)


def norm_target(link: str) -> str:
    """Normalize a wikilink target to a comparable stem.

    Four shapes occur in the corpus: bare slug, category/slug, category/slug.md, RAW/file.md.
    Mirrors kb-autolink.py's semantics so the two tools agree on what 'resolved' means.
    """
    t = link.split("|", 1)[0].strip()
    t = t.split("#", 1)[0].split("^", 1)[0].strip()
    if t.endswith(".md"):
        t = t[:-3]
    return t.split("/")[-1].strip()


def is_raw_link(link: str) -> bool:
    return link.split("|", 1)[0].strip().startswith("RAW/")


def parse_sources_line(value: str) -> list:
    """Extract source filenames from a **Sources:** line.

    60 articles state sources as backticked or bare filenames rather than [[RAW/...]] links.
    Parsing only the wikilink form drops those articles' provenance entirely.
    """
    out = []
    for m in LINK_RE.finditer(value):
        tgt = m.group(2).split("|", 1)[0].strip()
        if tgt.startswith("RAW/"):
            out.append(tgt[4:])
    if out:
        return out
    for part in re.split(r"[,;]", value):
        part = part.strip().strip("`").strip()
        part = re.sub(r"^RAW/", "", part)
        if part.endswith(".md") and "[[" not in part:
            out.append(part)
    return out


def article_records(root: Path, wiki: Path):
    """Parse every article once. Returns (records, parse_errors)."""
    records, errors = [], []
    for path in sorted(wiki.rglob("*.md")):
        if path.name == "_index.md":
            continue
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8", errors="replace")
        except OSError as exc:
            errors.append("%s: %s" % (path, exc))
            continue
        meta = {k.lower(): v for k, v in META_RE.findall(text)}
        h1 = H1_RE.search(text)
        claim_m = CLAIM_RE.search(text)

        # Sections: heading + body span. Bodies stay on disk; we keep offsets and word counts.
        sections, bounds = [], [(m.start(), m.group(1), m.group(2)) for m in SECTION_RE.finditer(text)]
        for i, (start, hashes, heading) in enumerate(bounds):
            end = bounds[i + 1][0] if i + 1 < len(bounds) else len(text)
            body = text[start:end]
            sections.append({
                "id": "%s#%d" % (path.stem, i),
                "article": path.stem,
                "heading": heading,
                "level": len(hashes),
                "ordinal": i,
                "start": start,
                "end": end,
                "words": len(body.split()),
            })

        # Links, globally. Section attribution by offset so MENTIONS/RELATES_TO can be
        # anchored to the block they actually appear in.
        links = []
        for m in LINK_RE.finditer(text):
            if m.group(1) == "!":  # embed, not a link
                continue
            target = m.group(2)
            if target.startswith("http"):
                continue
            pos = m.start()
            sec = None
            for s in sections:
                if s["start"] <= pos < s["end"]:
                    sec = s["id"]
                    break
            line_start = text.rfind("\n", 0, pos) + 1
            line_end = text.find("\n", pos)
            line = text[line_start: line_end if line_end != -1 else len(text)]
            bm = BULLET_RE.match(line)
            prose = bm.group(2).strip() if bm and norm_target(bm.group(1)) == norm_target(target) else ""
            links.append({
                "target": target,
                "stem": norm_target(target),
                "raw": is_raw_link(target),
                "section": sec,
                "prose": prose if len(prose) >= MIN_PROSE else "",
            })

        questions = []
        qm = OPENQ_RE.search(text)
        if qm:
            for line in qm.group(1).splitlines():
                line = line.strip()
                if line.startswith(("-", "*")):
                    q = line.lstrip("-* ").strip()
                    if q:
                        questions.append(q)

        tags = []
        if meta.get("tags"):
            tags = [t.strip().strip("`#") for t in re.split(r"[,;]", meta["tags"]) if t.strip()]

        records.append({
            "stem": path.stem,
            "path": path.relative_to(root).as_posix(),
            "title": h1.group(1) if h1 else path.stem,
            "category": meta.get("category", path.parent.name).strip(),
            "folder": path.parent.name,
            "updated": meta.get("updated", ""),
            "content_hash": hashlib.sha256(raw).hexdigest(),
            "words": len(text.split()),
            "claim": " ".join(claim_m.group(1).split()) if claim_m else "",
            "sources": parse_sources_line(meta.get("sources", "")),
            "sections": sections,
            "links": links,
            "questions": questions,
            "tags": tags,
        })
    return records, errors


def load_gazetteer(path: Path):
    """alias -> canonical entity. Absent file = no entity layer, which is a valid state."""
    if not path.exists():
        return {}, {}
    data = json.loads(path.read_text(encoding="utf-8"))
    alias_map, entities = {}, {}
    for ent in data.get("entities", []):
        name = ent["name"]
        entities[name] = {"name": name, "type": ent.get("type", "concept"), "aliases": ent.get("aliases", [])}
        for alias in [name] + ent.get("aliases", []):
            alias_map[alias.lower()] = name
    return alias_map, entities


def build(root: Path, out_dir: Path, quiet: bool = False):
    wiki, raw_dir = root / "KB" / "wiki", root / "KB" / "RAW"
    if not wiki.is_dir():
        print("FATAL: %s not found" % wiki, file=sys.stderr)
        return None, ["missing wiki"]

    records, errors = article_records(root, wiki)
    stems = {r["stem"] for r in records}
    folders = {r["folder"] for r in records}

    # ---- RawSource nodes: enumerate disk, not citations. The uncompiled ones are the point.
    raw_files = sorted(p.name for p in raw_dir.glob("*.md")) if raw_dir.is_dir() else []
    raw_nodes, raw_text = {}, {}
    for name in raw_files:
        try:
            body = (raw_dir / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            body = ""
        raw_text[name] = body
        iso, prec, where = extract_date(name, body)
        raw_nodes[name] = {"name": name, "cited_by": [], "date": iso, "precision": prec,
                           "date_from": where, "duplicate_of": "", "duplicate_score": 0.0}
    missing_sources = []

    # ---- Typed-edge cache (optional, offline-produced, content-addressed).
    types_path = out_dir / "kb-edge-types.json"
    edge_types, type_vocab = {}, []
    if types_path.exists():
        tdata = json.loads(types_path.read_text(encoding="utf-8"))
        type_vocab = tdata.get("vocabulary", [])
        for row in tdata.get("edges", []):
            edge_types[(row["s"], row["o"], row.get("hash", ""))] = row["type"]

    alias_map, entities = load_gazetteer(out_dir / "kb-gazetteer.json")

    nodes_article, nodes_section, edges = [], [], []
    open_questions, mention_counter = [], Counter()
    category_mismatch = []

    for r in records:
        # Article time = the span of its SOURCES, not its compile date. **Updated:** records
        # when the wiki article was written; the content is as old as the note it came from.
        sd = sorted(raw_nodes[s]["date"] for s in r["sources"]
                    if s in raw_nodes and raw_nodes[s]["date"])
        art = {k: r[k] for k in ("stem", "path", "title", "category", "folder", "updated",
                                 "content_hash", "words", "claim")}
        art["source_earliest"] = sd[0] if sd else ""
        art["source_latest"] = sd[-1] if sd else ""
        art["dated_sources"] = len(sd)
        nodes_article.append(art)
        for s in r["sections"]:
            nodes_section.append({k: s[k] for k in ("id", "article", "heading", "level", "ordinal", "words")})
        # Folder is canonical, not the metadata field: an article may declare a compound category
        # ("cooking / gardening", "learning | cooking") which would otherwise fragment the
        # taxonomy into phantom buckets in every rollup.
        edges.append({"s": r["stem"], "p": "IN_CATEGORY", "o": r["folder"]})
        if r["category"] != r["folder"]:
            category_mismatch.append({"article": r["stem"], "declared": r["category"], "folder": r["folder"]})

        for src in r["sources"]:
            if src in raw_nodes:
                raw_nodes[src]["cited_by"].append(r["stem"])
                edges.append({"s": r["stem"], "p": "CITES_SOURCE", "o": src})
            else:
                missing_sources.append({"article": r["stem"], "source": src})
        if not r["sources"]:
            edges.append({"s": r["stem"], "p": "CITES_SOURCE", "o": None})

        for q in r["questions"]:
            open_questions.append({"article": r["stem"], "question": q})
        for t in r["tags"]:
            edges.append({"s": r["stem"], "p": "TAGGED_WITH", "o": t})

        seen_pairs = set()
        for link in r["links"]:
            if link["raw"]:
                name = link["stem"] + ".md" if not link["stem"].endswith(".md") else link["stem"]
                if name in raw_nodes and r["stem"] not in raw_nodes[name]["cited_by"]:
                    raw_nodes[name]["cited_by"].append(r["stem"])
                    edges.append({"s": r["stem"], "p": "CITES_SOURCE", "o": name})
                continue
            tgt = link["stem"]
            if tgt in ("_index",) or tgt in folders:
                continue
            if tgt not in stems:
                continue  # unresolved; kb-autolink.py owns that report
            key = (tgt, link["prose"])
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            ph = hashlib.sha256(link["prose"].encode("utf-8")).hexdigest()[:16] if link["prose"] else ""
            edge = {
                "s": r["stem"], "p": "RELATES_TO", "o": tgt,
                "prose": link["prose"], "section": link["section"],
                "type": edge_types.get((r["stem"], tgt, ph), "UNTYPED" if link["prose"] else "BARE"),
            }
            if link["prose"]:
                edge["hash"] = ph
            edges.append(edge)

    # ---- MENTIONS: regex sweep of the curated alias list over section bodies.
    if alias_map:
        patterns = [(re.compile(r"(?<![\w-])" + re.escape(a) + r"(?![\w-])", re.I), c)
                    for a, c in sorted(alias_map.items(), key=lambda kv: -len(kv[0]))]
        for r in records:
            text = (root / r["path"]).read_text(encoding="utf-8", errors="replace")
            for s in r["sections"]:
                body = text[s["start"]:s["end"]]
                hit = set()
                for pat, canon in patterns:
                    if canon not in hit and pat.search(body):
                        hit.add(canon)
                for canon in hit:
                    edges.append({"s": s["id"], "p": "MENTIONS", "o": canon})
                    mention_counter[canon] += 1

    mark_duplicates(raw_nodes, raw_text)

    # SUPERSEDES is derived, not authored: an EVOLVES_INTO edge means s is the earlier form,
    # so o supersedes s. Materialized as its own predicate so temporal queries need no join.
    for e in list(edges):
        if e["p"] == "RELATES_TO" and e.get("type") == "EVOLVES_INTO":
            edges.append({"s": e["o"], "p": "SUPERSEDES", "o": e["s"], "derived_from": "EVOLVES_INTO"})

    indeg = Counter(e["o"] for e in edges if e["p"] == "RELATES_TO")
    outdeg = Counter(e["s"] for e in edges if e["p"] == "RELATES_TO")
    typed = [e for e in edges if e["p"] == "RELATES_TO" and e["type"] not in ("UNTYPED", "BARE")]
    relates = [e for e in edges if e["p"] == "RELATES_TO"]

    graph = {
        "generated": date.today().isoformat(),
        "builder_version": BUILDER_VERSION,
        "counts": {
            "articles": len(nodes_article),
            "sections": len(nodes_section),
            "categories": len(folders),
            "raw_sources": len(raw_files),
            "raw_cited": sum(1 for v in raw_nodes.values() if v["cited_by"]),
            "raw_uncompiled": sum(1 for v in raw_nodes.values() if not v["cited_by"]),
            "entities": len(entities),
            "edges": len(edges),
            "relates_to": len(relates),
            "relates_with_prose": sum(1 for e in relates if e["prose"]),
            "relates_typed": len(typed),
            "mentions": sum(1 for e in edges if e["p"] == "MENTIONS"),
            "open_questions": len(open_questions),
            "orphans": sum(1 for r in records if indeg.get(r["stem"], 0) == 0),
            "dead_ends": sum(1 for r in records if outdeg.get(r["stem"], 0) == 0),
            "sourceless_articles": sum(1 for r in records if not r["sources"]),
            "unresolvable_sources": len(missing_sources),
            "category_mismatch": len(category_mismatch),
            "raw_duplicates": sum(1 for v in raw_nodes.values() if v["duplicate_of"]),
            "raw_truly_uncompiled": sum(1 for v in raw_nodes.values()
                                        if not v["cited_by"] and not v["duplicate_of"]),
            "raw_dated": sum(1 for v in raw_nodes.values() if v["date"]),
            "articles_dated": sum(1 for a in nodes_article if a["source_earliest"]),
            "supersedes": len([e for e in edges if e["p"] == "SUPERSEDES"]),
        },
        "type_vocabulary": type_vocab,
        "manifest": [{"path": r["path"], "content_hash": r["content_hash"]} for r in records],
        "nodes": {
            "article": nodes_article,
            "section": nodes_section,
            "category": sorted(folders),
            "raw": [{"name": k, "cited_by": v["cited_by"], "date": v["date"],
                     "precision": v["precision"], "duplicate_of": v["duplicate_of"]}
                    for k, v in sorted(raw_nodes.items())],
            "entity": [dict(entities[e], mentions=mention_counter.get(e, 0)) for e in sorted(entities)],
        },
        "edges": edges,
        "open_questions": open_questions,
        "unresolvable_sources": missing_sources,
        "category_mismatch": category_mismatch,
    }
    if not quiet:
        c = graph["counts"]
        print("built:    %d articles · %d sections · %d edges" % (c["articles"], c["sections"], c["edges"]))
        print("links:    %d RELATES_TO (%d with prose, %d typed)"
              % (c["relates_to"], c["relates_with_prose"], c["relates_typed"]))
        print("sources:  %d RAW on disk · %d cited · %d duplicate copies · %d truly uncompiled"
              % (c["raw_sources"], c["raw_cited"], c["raw_duplicates"], c["raw_truly_uncompiled"]))
        print("entities: %d in gazetteer · %d MENTIONS edges" % (c["entities"], c["mentions"]))
        print("gaps:     %d orphans · %d dead-ends · %d sourceless · %d open questions"
              % (c["orphans"], c["dead_ends"], c["sourceless_articles"], c["open_questions"]))
        for e in errors:
            print("  ERROR %s" % e)
    return graph, errors


def check(root: Path, out_dir: Path):
    """Freshness gate for verify.sh. 0 PASS / 1 FAIL / 2 WARN, matching brain-doctor.py."""
    path = out_dir / "kb-graph.json"
    if not path.exists():
        print("WARN  kb-graph.json absent — run `python3 tools/kb-graph.py`")
        return 2
    try:
        graph = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        print("FAIL  kb-graph.json unreadable: %s" % exc)
        return 1
    wiki = root / "KB" / "wiki"
    disk = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in wiki.rglob("*.md") if p.name != "_index.md"}
    manifest = {row["path"]: row["content_hash"] for row in graph.get("manifest", [])}
    drift = len(set(disk) ^ set(manifest)) + sum(1 for k in set(disk) & set(manifest) if disk[k] != manifest[k])
    if drift:
        print("WARN  kb-graph drift: %d path(s) added, removed, or changed — rebuild" % drift)
        return 2
    print("PASS  kb-graph fresh: %d articles, %d edges"
          % (graph["counts"]["articles"], graph["counts"]["edges"]))
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description="Build the KB knowledge graph (read-only over KB/).")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--check", action="store_true", help="freshness gate: 0 PASS / 1 FAIL / 2 WARN")
    ap.add_argument("--json", action="store_true", help="print the graph to stdout instead of writing")
    args = ap.parse_args(argv[1:])
    root = Path(args.root).resolve()
    out_dir = root / "KB" / "output"

    if args.check:
        return check(root, out_dir)

    graph, errors = build(root, out_dir, quiet=args.json)
    if graph is None:
        return 1
    if args.json:
        print(json.dumps(graph, ensure_ascii=False, indent=1))
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "kb-graph.json"
    target.write_text(json.dumps(graph, ensure_ascii=False, indent=1), encoding="utf-8")
    print("graph:    %s (%dKB)" % (target, target.stat().st_size // 1024))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
