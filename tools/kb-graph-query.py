#!/usr/bin/env python3
"""kb-graph-query.py — the graph read side. Six verbs, one per proven retrieval failure.

    search  <query>     hybrid: BM25 over sections + field-weighted keyword, fused by RRF
    connect <a> <b>     shortest paths between two concepts, carrying the hand-written prose
    neighbors <stem>    1-2 hop neighbourhood, in and out
    provenance <x>      article -> RAW sources -> co-sourced articles (or RAW file -> articles)
    themes  [query]     route thematic questions to the hand-authored pillar layer
    timeline [query]    articles ordered by SOURCE date, with supersession chains
    gaps                orphans, dead-ends, sourceless articles, never-compiled sources

Why these six and nothing else: the measured evidence says graph machinery only beats plain
search on three query shapes — multi-hop bridging, provenance chains, and global/thematic
rollup. `search` exists because BM25 at section granularity was the largest measured win in
the closest analogue (+14pts); `gaps` exists because 128 orphans and 630 uncompiled sources
are retrieval-recall defects, not tidiness debt.

Reads KB/output/kb-graph.json, KB/output/kb-index.json, KB/wiki/**. WRITES NOTHING.
Stdlib only (sqlite3 FTS5 provides BM25 — no pip, no network). Python 3.9.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sqlite3
import sys
from collections import defaultdict, deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kb_config  # noqa: E402

RRF_K = 60          # Reciprocal Rank Fusion constant; 60 is the standard from the TREC work.
MAX_DEPTH = 5       # connect() hop ceiling. Measured on the live graph (589 articles, 2,166
                    # links): random-pair shortest path is mean 3.78 / median 4 / max 7, so a
                    # 3-hop ceiling answered only 36.7% of pairs and reported "no path" for
                    # genuinely connected concepts. 5 covers 97.7%.

# BM25's vote is deliberately minority. Measured on KB/output/retrieval-eval.json (32 questions,
# hand-labeled gold, recall@6) — equal-weight fusion REGRESSED the title/claim lookups the old
# scorer was already good at, because an OR-expanded section list outvoted a tuned ranker:
#     weight   lookup(20)   body(12)   combined
#     0.0 old    0.892       0.431      0.719
#     0.3        0.883       0.597      0.776   <- shipped
#     1.0        0.842       0.618      0.758
# 0.3 buys +16.6 points on body-content questions (which the old scorer literally cannot see —
# it indexes titles, claims and section NAMES, never section text) for -0.9 on lookups.
BM25_WEIGHT = 0.3

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for", "with", "at", "by",
    "from", "is", "are", "was", "be", "as", "it", "its", "this", "that", "these", "those",
    "how", "what", "why", "when", "who", "which", "do", "does", "my", "me", "about", "vs",
    "versus", "into", "his", "her", "their", "our", "i", "have", "has", "all", "any",
}


def load_sibling(name: str):
    """Import a sibling tool as a module — the pattern brain-doctor.py already uses."""
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(name.replace("-", "_")[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def tokenize(q: str) -> list:
    return [t for t in re.split(r"[^a-z0-9]+", q.lower())
            if t and t not in STOPWORDS and (len(t) > 1 or t.isdigit())]


# ---------------------------------------------------------------- graph helpers

class Graph:
    def __init__(self, root: Path):
        self.root = root
        gp = root / "KB" / "output" / "kb-graph.json"
        if not gp.exists():
            sys.exit("FATAL: %s missing — run `python3 tools/kb-graph.py` first" % gp)
        self.g = json.loads(gp.read_text(encoding="utf-8"))
        self.articles = {a["stem"]: a for a in self.g["nodes"]["article"]}
        self.raw = {r["name"]: r for r in self.g["nodes"]["raw"]}
        self.out, self.inn, self.prose = defaultdict(list), defaultdict(list), {}
        self.sources, self.cited_by = defaultdict(list), defaultdict(list)
        self.supersedes, self.superseded_by = defaultdict(list), defaultdict(list)
        for e in self.g["edges"]:
            if e["p"] == "RELATES_TO":
                self.out[e["s"]].append(e["o"])
                self.inn[e["o"]].append(e["s"])
                self.prose[(e["s"], e["o"])] = (e.get("prose", ""), e.get("type", "UNTYPED"))
            elif e["p"] == "CITES_SOURCE" and e["o"]:
                self.sources[e["s"]].append(e["o"])
                self.cited_by[e["o"]].append(e["s"])
            elif e["p"] == "SUPERSEDES":
                self.supersedes[e["s"]].append(e["o"])
                self.superseded_by[e["o"]].append(e["s"])

    def resolve(self, name: str):
        """Fuzzy-resolve a user-typed concept to an article stem."""
        n = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        if n in self.articles:
            return n
        exact = [s for s in self.articles if s == n]
        if exact:
            return exact[0]
        subs = [s for s in self.articles if n in s]
        if len(subs) == 1:
            return subs[0]
        # Weighted, because an unweighted bag-of-tokens match lets a long claim outrank the
        # article actually named by the query (measured: "shadow work" resolved to
        # mastery-codes-brojo-program before this fix).
        toks = [t for t in n.split("-") if t]
        if not toks:
            return None
        scored = []
        for s, a in self.articles.items():
            stem_h = s.lower().replace("-", " ")
            title_h = a["title"].lower()
            claim_h = a["claim"].lower()
            score = 0.0
            for t in toks:
                if t in stem_h:
                    score += 6
                elif t in title_h:
                    score += 3
                elif t in claim_h:
                    score += 1
            if score:
                coverage = sum(1 for t in toks if t in stem_h + " " + title_h + " " + claim_h) / len(toks)
                scored.append((score * coverage, -len(s), s))
        if not scored:
            return None
        scored.sort(reverse=True)
        return scored[0][2]

    def neighbours(self, stem: str):
        return set(self.out.get(stem, [])) | set(self.inn.get(stem, []))

    def hop_label(self, a: str, b: str) -> str:
        prose, typ = self.prose.get((a, b), self.prose.get((b, a), ("", "")))
        arrow = "->" if (a, b) in self.prose else "<-"
        tag = "" if typ in ("UNTYPED", "BARE", "") else "[%s] " % typ
        return "%s %s%s%s" % (arrow, tag, b, (" :: " + prose) if prose else "")


# ---------------------------------------------------------------- verbs

def build_fts(root: Path, graph: Graph):
    """One in-memory FTS5 table over section bodies. ~0.2s for 3.3k sections."""
    db = sqlite3.connect(":memory:")
    try:
        db.execute("CREATE VIRTUAL TABLE s USING fts5(sid UNINDEXED, stem UNINDEXED, "
                   "heading UNINDEXED, body, tokenize='porter unicode61')")
    except sqlite3.OperationalError:
        return None
    secs = defaultdict(list)
    for s in graph.g["nodes"]["section"]:
        secs[s["article"]].append(s)
    rows = []
    for stem, art in graph.articles.items():
        try:
            text = (root / art["path"]).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        bounds = [(m.start(), m.group(2)) for m in
                  re.finditer(r"^(#{2,3})\s+(.+?)\s*$", text, re.M)]
        for i, (start, heading) in enumerate(bounds):
            end = bounds[i + 1][0] if i + 1 < len(bounds) else len(text)
            rows.append(("%s#%d" % (stem, i), stem, heading, heading + "\n" + text[start:end]))
        rows.append(("%s#title" % stem, stem, art["title"], art["title"] + "\n" + art["claim"]))
    db.executemany("INSERT INTO s VALUES(?,?,?,?)", rows)
    db.commit()
    return db


def verb_search(root: Path, graph: Graph, query: str, k: int):
    terms = tokenize(query)
    if not terms:
        return {"error": "no searchable terms"}

    # list 1 — BM25 over sections (FTS5). OR-expanded: bare multi-term MATCH is AND and
    # silently returns almost nothing on a 4-word question.
    bm25_rank, best_section = [], {}
    fallback = ""
    db = build_fts(root, graph)
    if db is not None:
        expr = " OR ".join('"%s"' % t for t in terms)
        try:
            for sid, stem, heading, score in db.execute(
                    "SELECT sid, stem, heading, bm25(s) FROM s WHERE s MATCH ? "
                    "ORDER BY bm25(s) LIMIT 400", (expr,)):
                if stem not in best_section:
                    best_section[stem] = (heading, round(score, 2))
                    bm25_rank.append(stem)
        except sqlite3.OperationalError as exc:
            fallback = "FTS query failed; keyword fallback: %s" % exc
        finally:
            db.close()
    else:
        fallback = "SQLite FTS5 unavailable; keyword fallback (no stemming)"

    # list 2 — the existing field-weighted scorer, reused verbatim so the two agree.
    # Degrades to BM25-only rather than crashing: kb-index.json is a separate artifact with its
    # own build step, and a missing index must not take the whole graph query surface down.
    kw_rank, degraded = [], fallback
    index_path = root / "KB" / "output" / "kb-index.json"
    if index_path.exists():
        kwq = load_sibling("kb-query.py")
        arts = json.loads(index_path.read_text(encoding="utf-8")).get("articles", [])
        _, kw_hits = kwq.rank(arts, query, kwq.build_indegree(arts), k=200)
        kw_rank = [h["stem"] for h in kw_hits]
    else:
        degraded = "; ".join(x for x in (fallback, "kb-index.json missing; run bin/kb index") if x)

    # fusion — RRF beats tuned weighted sums and needs no calibration.
    fused = defaultdict(float)
    contrib = defaultdict(list)
    for name, lst, weight in (("bm25", bm25_rank, BM25_WEIGHT), ("keyword", kw_rank, 1.0)):
        for i, stem in enumerate(lst):
            fused[stem] += weight / (RRF_K + i + 1)
            contrib[stem].append("%s#%d" % (name, i + 1))

    ranked = sorted(fused.items(), key=lambda kv: (-kv[1], kv[0]))[:k]
    results = []
    for stem, score in ranked:
        a = graph.articles.get(stem)
        if not a:
            continue
        heading, bscore = best_section.get(stem, ("", None))
        results.append({
            "stem": stem, "path": a["path"], "category": a["category"], "title": a["title"],
            "claim": a["claim"][:220], "rrf": round(score, 5), "signals": contrib[stem],
            "best_section": heading, "bm25": bscore,
            "links_in": len(graph.inn.get(stem, [])), "links_out": len(graph.out.get(stem, [])),
            "sources": graph.sources.get(stem, []),
        })
    return {"query": query, "terms": terms, "verb": "search",
            "fusion": "RRF(bm25_sections*%.1f, field_keyword*1.0)" % BM25_WEIGHT,
            "degraded": degraded, "retrieval": {"ranker": "keyword" if fallback else "hybrid-graph",
            "k": k, "tool": "kb-graph-query.py", "stemming": not bool(fallback),
            "version": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12],
            "sqlite": sqlite3.sqlite_version}, "results": results}


def verb_connect(graph: Graph, a_in: str, b_in: str, limit: int):
    a, b = graph.resolve(a_in), graph.resolve(b_in)
    if not a:
        return {"error": "could not resolve %r to an article" % a_in}
    if not b:
        return {"error": "could not resolve %r to an article" % b_in}
    if a == b:
        return {"error": "both terms resolve to %s" % a}

    # BFS over the undirected link graph, collecting every shortest path up to MAX_DEPTH.
    paths, frontier = [], deque([[a]])
    seen_depth = {a: 0}
    found_depth = None
    while frontier:
        path = frontier.popleft()
        node = path[-1]
        d = len(path) - 1
        if found_depth is not None and d >= found_depth:
            continue
        if d >= MAX_DEPTH:
            continue
        for nb in sorted(graph.neighbours(node)):
            if nb in path:
                continue
            if nb == b:
                found_depth = d + 1
                paths.append(path + [nb])
                continue
            if seen_depth.get(nb, 99) < d + 1:
                continue
            seen_depth[nb] = d + 1
            frontier.append(path + [nb])
    paths = paths[:limit]
    return {
        "verb": "connect", "from": a, "to": b,
        "resolved_from": a_in, "resolved_to": b_in,
        "hops": (len(paths[0]) - 1) if paths else None,
        "path_count": len(paths),
        "paths": [{"nodes": p,
                   "steps": [graph.hop_label(p[i], p[i + 1]) for i in range(len(p) - 1)]}
                  for p in paths],
        "note": ("no path within %d hops — the two concepts are not linked in the wiki"
                 % MAX_DEPTH) if not paths else "",
    }


def verb_neighbors(graph: Graph, name: str, depth: int):
    stem = graph.resolve(name)
    if not stem:
        return {"error": "could not resolve %r" % name}
    out = [{"target": t, "prose": graph.prose.get((stem, t), ("", ""))[0],
            "type": graph.prose.get((stem, t), ("", "UNTYPED"))[1]} for t in sorted(set(graph.out.get(stem, [])))]
    inn = [{"source": s, "prose": graph.prose.get((s, stem), ("", ""))[0],
            "type": graph.prose.get((s, stem), ("", "UNTYPED"))[1]} for s in sorted(set(graph.inn.get(stem, [])))]
    two = []
    if depth > 1:
        first = graph.neighbours(stem)
        for n1 in sorted(first):
            for n2 in sorted(graph.neighbours(n1)):
                if n2 != stem and n2 not in first:
                    two.append({"via": n1, "node": n2})
    art = graph.articles.get(stem, {})
    return {"verb": "neighbors", "stem": stem, "title": art.get("title", ""),
            "claim": art.get("claim", "")[:220], "category": art.get("category", ""),
            "out": out, "in": inn, "two_hop": two[:60],
            "sources": graph.sources.get(stem, [])}


def verb_provenance(graph: Graph, name: str):
    # A RAW filename was given directly.
    cand = name if name.endswith(".md") else name + ".md"
    if cand in graph.raw:
        arts = graph.raw[cand]["cited_by"]
        return {"verb": "provenance", "direction": "raw->articles", "raw": cand,
                "compiled_into": [{"stem": s, "path": graph.articles[s]["path"],
                                   "claim": graph.articles[s]["claim"][:180]}
                                  for s in arts if s in graph.articles],
                "note": "NEVER COMPILED — no wiki article cites this source" if not arts else ""}
    stem = graph.resolve(name)
    if not stem:
        return {"error": "could not resolve %r as an article or a KB/RAW filename" % name}
    srcs = graph.sources.get(stem, [])
    siblings = defaultdict(list)
    for s in srcs:
        for other in graph.cited_by.get(s, []):
            if other != stem:
                siblings[other].append(s)
    art = graph.articles[stem]
    return {
        "verb": "provenance", "direction": "article->raw", "stem": stem,
        "title": art["title"], "claim": art["claim"], "path": art["path"],
        "sources": [{"name": s, "path": "KB/RAW/" + s,
                     "also_cited_by": [o for o in graph.cited_by.get(s, []) if o != stem]}
                    for s in srcs],
        "co_sourced_articles": [{"stem": k, "via": v} for k, v in sorted(siblings.items())],
        "note": "NO SOURCE RECORDED — this article's provenance is unverifiable" if not srcs else "",
    }


def verb_themes(root: Path, graph: Graph, query: str):
    """Thematic questions route to the hand-authored community layer, not to articles.

    GraphRAG's community reports are the one component with replicated evidence. The owner
    may have better ones, written by hand from a 394-article deep read: the spine page and
    the pillar papers. Generating machine communities over 502 nodes would be worse.
    """
    spine = kb_config.path(root, "spine")
    pillars = sorted((root / "KB" / "output" / "pillars").glob("*.md")) \
        if (root / "KB" / "output" / "pillars").is_dir() else []
    terms = set(tokenize(query)) if query else set()
    scored = []
    for p in pillars:
        txt = p.read_text(encoding="utf-8", errors="replace").lower()
        hits = sum(txt.count(t) for t in terms) if terms else 0
        scored.append((hits, p))
    scored.sort(key=lambda kv: -kv[0])

    by_cat = defaultdict(list)
    for stem, a in graph.articles.items():
        by_cat[a.get("folder", a["category"])].append((len(graph.inn.get(stem, [])), stem, a["title"]))
    rollup = []
    for cat in sorted(by_cat):
        top = sorted(by_cat[cat], reverse=True)[:5]
        rollup.append({"category": cat, "articles": len(by_cat[cat]),
                       "hubs": [{"stem": s, "title": t, "links_in": d} for d, s, t in top]})
    return {
        "verb": "themes", "query": query,
        "read_first": [str(spine.relative_to(root))] if spine.exists() else [],
        "pillars": [{"path": str(p.relative_to(root)), "term_hits": h} for h, p in scored],
        "category_rollup": rollup,
        "note": "Thematic answers come from the pillar layer + rollup hubs. Read those files, "
                "then pull specific articles with `search`.",
    }


def verb_timeline(graph: Graph, query: str, k: int):
    """Order matching articles by the date of their SOURCES, and surface supersession chains.

    Article time is source time, not compile time: `**Updated:**` says when the wiki entry was
    written, which for a 2013 journal note is 2026. Coverage is partial by construction — only
    21% of KB/RAW carries a written date — so undated articles are reported, never guessed.
    """
    terms = tokenize(query) if query else []
    rows = []
    undated = 0
    for stem, a in graph.articles.items():
        if terms:
            hay = (stem + " " + a.get("title", "") + " " + a.get("claim", "")).lower()
            if not any(t in hay for t in terms):
                continue
        if not a.get("source_earliest"):
            undated += 1
            continue
        rows.append({
            "stem": stem, "title": a.get("title", ""), "category": a.get("category", ""),
            "earliest": a["source_earliest"], "latest": a.get("source_latest", ""),
            "dated_sources": a.get("dated_sources", 0),
            "supersedes": graph.supersedes.get(stem, []),
            "superseded_by": graph.superseded_by.get(stem, []),
            "claim": a.get("claim", "")[:150],
        })
    rows.sort(key=lambda r: (r["earliest"], r["stem"]))
    chains = [r for r in rows if r["supersedes"] or r["superseded_by"]]
    return {
        "verb": "timeline", "query": query,
        "dated": len(rows), "undated_matches": undated,
        "span": (rows[0]["earliest"], rows[-1]["earliest"]) if rows else ("", ""),
        "articles": rows[:k] if k else rows,
        "supersession_chains": chains[:40],
        "note": "Only articles whose SOURCES carry a written date appear. %d matching article(s) "
                "have no dated source and are omitted rather than guessed." % undated,
    }


def verb_gaps(graph: Graph, root: Path, k: int):
    c = graph.counts = graph.g["counts"]
    orphans = [s for s in graph.articles if not graph.inn.get(s)]
    dead = [s for s in graph.articles if not graph.out.get(s)]
    sourceless = [s for s in graph.articles if not graph.sources.get(s)]
    uncompiled, duplicates = [], []
    for name, r in graph.raw.items():
        if r["cited_by"]:
            continue
        p = root / "KB" / "RAW" / name
        try:
            kb = p.stat().st_size // 1024
        except OSError:
            kb = 0
        row = {"name": name, "kb": kb}
        if r.get("duplicate_of"):
            row["duplicate_of"] = r["duplicate_of"]
            duplicates.append(row)
        else:
            uncompiled.append(row)
    uncompiled.sort(key=lambda r: -r["kb"])
    duplicates.sort(key=lambda r: -r["kb"])
    return {
        "verb": "gaps", "counts": c,
        "uncompiled_raw": {"count": len(uncompiled),
                           "total_kb": sum(u["kb"] for u in uncompiled),
                           "largest": uncompiled[:k]},
        "duplicate_raw": {"count": len(duplicates),
                          "total_kb": sum(d["kb"] for d in duplicates),
                          "note": "byte-variant copies of files the wiki already cites — not missing work",
                          "largest": duplicates[:k]},
        "orphan_articles": {"count": len(orphans), "sample": sorted(orphans)[:k]},
        "dead_end_articles": {"count": len(dead), "sample": sorted(dead)[:k]},
        "sourceless_articles": {"count": len(sourceless), "sample": sorted(sourceless)[:k]},
        "category_mismatch": {"count": len(graph.g.get("category_mismatch", [])),
                              "sample": graph.g.get("category_mismatch", [])[:k]},
        "open_questions": {"count": len(graph.g["open_questions"]),
                           "sample": graph.g["open_questions"][:k]},
        "note": "Uncompiled RAW is the largest recall defect: those words are unreachable by "
                "every retrieval path in this repo.",
    }


# ---------------------------------------------------------------- human rendering

def render(res: dict) -> None:
    if "error" in res:
        print("  ! %s" % res["error"])
        return
    v = res["verb"]
    if v == "search":
        print('=== SEARCH "%s" · %s · terms=%s ===' % (res["query"], res["fusion"], res["terms"]))
        if res.get("degraded"):
            print("  ! %s" % res["degraded"])
        for i, r in enumerate(res["results"], 1):
            print("%2d. [%.4f] %s/%s" % (i, r["rrf"], r["category"], r["stem"]))
            if r["claim"]:
                print("        %s" % r["claim"])
            print("        best section: %s · signals: %s · in:%d out:%d"
                  % (r["best_section"] or "-", ",".join(r["signals"]), r["links_in"], r["links_out"]))
            print("        %s" % r["path"])
    elif v == "connect":
        print("=== CONNECT %s -> %s ===" % (res["from"], res["to"]))
        if res["note"]:
            print("  %s" % res["note"])
        for i, p in enumerate(res["paths"], 1):
            print("\n  path %d (%d hops): %s" % (i, len(p["nodes"]) - 1, p["nodes"][0]))
            for s in p["steps"]:
                print("      %s" % s)
    elif v == "neighbors":
        print("=== NEIGHBORS %s — %s ===" % (res["stem"], res["title"]))
        print("  %s" % res["claim"])
        print("\n  OUT (%d):" % len(res["out"]))
        for o in res["out"]:
            print("    -> %s%s" % (o["target"], (" :: " + o["prose"]) if o["prose"] else ""))
        print("\n  IN (%d):" % len(res["in"]))
        for o in res["in"]:
            print("    <- %s%s" % (o["source"], (" :: " + o["prose"]) if o["prose"] else ""))
        if res["two_hop"]:
            print("\n  TWO-HOP (%d): %s" % (len(res["two_hop"]),
                                            ", ".join(sorted({t["node"] for t in res["two_hop"]}))[:600]))
    elif v == "provenance":
        if res["direction"] == "raw->articles":
            print("=== PROVENANCE (source) KB/RAW/%s ===" % res["raw"])
            if res["note"]:
                print("  ! %s" % res["note"])
            for a in res["compiled_into"]:
                print("  -> %s\n       %s" % (a["path"], a["claim"]))
        else:
            print("=== PROVENANCE (article) %s ===" % res["stem"])
            print("  claim: %s" % res["claim"])
            if res["note"]:
                print("  ! %s" % res["note"])
            for s in res["sources"]:
                extra = (" (also cited by %s)" % ", ".join(s["also_cited_by"])) if s["also_cited_by"] else ""
                print("  <- %s%s" % (s["path"], extra))
            if res["co_sourced_articles"]:
                print("\n  co-sourced articles:")
                for c in res["co_sourced_articles"]:
                    print("    %s (via %s)" % (c["stem"], ", ".join(c["via"])))
    elif v == "themes":
        print("=== THEMES%s ===" % ((' "' + res["query"] + '"') if res["query"] else ""))
        for f in res["read_first"]:
            print("  READ FIRST: %s" % f)
        for p in res["pillars"]:
            print("  pillar: %s (term hits: %d)" % (p["path"], p["term_hits"]))
        print("\n  category rollup:")
        for c in res["category_rollup"]:
            hubs = ", ".join("%s(%d)" % (h["stem"], h["links_in"]) for h in c["hubs"])
            print("    %-26s %3d articles · hubs: %s" % (c["category"], c["articles"], hubs))
        print("\n  %s" % res["note"])
    elif v == "timeline":
        print('=== TIMELINE%s ===' % ((' "' + res["query"] + '"') if res["query"] else ""))
        if res["dated"]:
            print("  %d dated article(s), %s -> %s" % (res["dated"], res["span"][0], res["span"][1]))
        for r in res["articles"]:
            sup = ""
            if r["superseded_by"]:
                sup = "  [superseded by %s]" % ", ".join(r["superseded_by"])
            elif r["supersedes"]:
                sup = "  [supersedes %s]" % ", ".join(r["supersedes"])
            print("  %-10s %-34s %s%s" % (r["earliest"], r["stem"][:34], r["category"], sup))
        if res["supersession_chains"]:
            print("\n  supersession chains: %d" % len(res["supersession_chains"]))
        print("\n  %s" % res["note"])
    elif v == "gaps":
        c = res["counts"]
        print("=== GAPS ===")
        print("  corpus:      %d articles · %d sections · %d edges" % (c["articles"], c["sections"], c["edges"]))
        u, d = res["uncompiled_raw"], res["duplicate_raw"]
        print("  UNCOMPILED:  %d of %d RAW files (%dKB) never reached the wiki" %
              (u["count"], c["raw_sources"], u["total_kb"]))
        for r in u["largest"][:6]:
            print("      %5dKB  %s" % (r["kb"], r["name"]))
        print("  DUPLICATES:  %d file(s) (%dKB) are copies of already-cited sources — not missing work"
              % (d["count"], d["total_kb"]))
        for r in d["largest"][:4]:
            print("      %5dKB  %s  ==  %s" % (r["kb"], r["name"], r.get("duplicate_of", "")))
        print("  orphans:     %d articles with zero inbound links" % res["orphan_articles"]["count"])
        print("  dead-ends:   %d articles with zero outbound links" % res["dead_end_articles"]["count"])
        print("  sourceless:  %d articles with no provenance" % res["sourceless_articles"]["count"])
        print("  open qs:     %d unanswered questions already flagged in the corpus"
              % res["open_questions"]["count"])
        print("  bad category:%d articles whose **Category:** disagrees with their folder"
              % res["category_mismatch"]["count"])
        print("\n  %s" % res["note"])


def main(argv):
    ap = argparse.ArgumentParser(description="Query the KB knowledge graph. Read-only.")
    ap.add_argument("verb", choices=["search", "connect", "neighbors", "provenance", "themes",
                                     "timeline", "gaps"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--depth", type=int, default=1)
    a = ap.parse_args(argv[1:])
    if a.k < 1:
        ap.error("--k must be positive")
    root = Path(a.root).resolve()
    graph = Graph(root)

    if a.verb == "search":
        if not a.args:
            return ap.error("search needs a query")
        res = verb_search(root, graph, " ".join(a.args), a.k)
    elif a.verb == "connect":
        if len(a.args) < 2:
            return ap.error("connect needs two concepts")
        mid = len(a.args) // 2 if len(a.args) > 2 else 1
        res = verb_connect(graph, a.args[0] if len(a.args) == 2 else " ".join(a.args[:mid]),
                           a.args[1] if len(a.args) == 2 else " ".join(a.args[mid:]), a.k)
    elif a.verb == "neighbors":
        res = verb_neighbors(graph, " ".join(a.args), a.depth)
    elif a.verb == "provenance":
        res = verb_provenance(graph, " ".join(a.args))
    elif a.verb == "themes":
        res = verb_themes(root, graph, " ".join(a.args))
    elif a.verb == "timeline":
        res = verb_timeline(graph, " ".join(a.args), a.k if a.args else 0)
    else:
        res = verb_gaps(graph, root, a.k)

    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        render(res)
    return 1 if "error" in res else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
