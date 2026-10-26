#!/usr/bin/env python3
"""kb-query.py — ranked KB retrieval seam (the retrieval step under any answer step).

Reads KB/output/kb-index.json (built by kb-index.py) and returns the top-ranked
articles for a query: raw ranked candidates. Synthesizing an answer from them is
the caller's job (a person, or an agent that reads these hits and writes an answer + gap note).

Usage:
    python3 tools/kb-query.py "<query>"            # human-readable ranked list
    python3 tools/kb-query.py "<query>" --json      # machine-readable (for an agent)
    python3 tools/kb-query.py "<query>" --k 12       # top-K (default 8)

Scorer: keyword — field-weighted term matching x coverage, boosted by
link-centrality (in-degree) and recency. P3 semantic retrieval was scrapped;
the `scorer` field in --json reports the active keyword mode.

Stdlib only. Read-only — never writes, never touches the KB.
"""
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "KB" / "output" / "kb-index.json"
WIKI = ROOT / "KB" / "wiki"

# Field weights — how much a term match in each field is worth. Title/slug name the
# concept, so they dominate; links are the weakest signal (a mention, not the subject).
FIELD_WEIGHTS = {"title": 6, "stem": 5, "claim": 3, "sections": 2, "category": 2, "links": 1}
PER_FIELD_CAP = 3          # a single field can't score a term more than this many times
CENTRALITY_BOOST = 0.10    # max multiplier from in-degree (the owner's hub concepts)
RECENCY_BOOST = 0.08       # max multiplier from recency (near-flat today)
RECENCY_HORIZON_DAYS = 730

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for", "with", "at",
    "by", "from", "is", "are", "was", "be", "as", "it", "its", "this", "that", "these",
    "those", "how", "what", "why", "when", "who", "which", "do", "does", "my", "me",
    "about", "vs", "versus", "into", "his", "her", "their", "our",
}


def tokenize(q: str) -> list:
    """Lowercase, split on non-alphanumerics, drop stopwords + 1-char noise."""
    terms = re.split(r"[^a-z0-9]+", q.lower())
    return [t for t in terms if t and t not in STOPWORDS and (len(t) > 1 or t.isdigit())]


def norm_field(s: str) -> str:
    """Hyphens/underscores -> spaces so a slug like 'soil-health' matches 'health'."""
    return re.sub(r"[-_/]+", " ", (s or "").lower())


def basename(link: str) -> str:
    """Normalize a wiki-link target ('cat/stem' or bare 'stem') to a comparable stem."""
    return re.sub(r"\.md$", "", link.split("/")[-1].strip().lower())


def build_indegree(articles: list) -> dict:
    """How many articles link TO each stem — corpus centrality, computed once."""
    deg = {}
    for a in articles:
        for l in a.get("links", []):
            t = basename(l)
            if t:
                deg[t] = deg.get(t, 0) + 1
    return deg


def article_fields(a: dict) -> dict:
    """Pre-normalized searchable text per field for one article."""
    return {
        "title": norm_field(a.get("title", "")),
        "stem": norm_field(a.get("stem", "")),
        "claim": norm_field(a.get("claim", "")),
        "sections": norm_field(" ".join(a.get("sections", []))),
        "category": norm_field(a.get("category", "")),
        "links": norm_field(" ".join(basename(l) for l in a.get("links", []))),
    }


def score_keyword(fields: dict, terms: list):
    """Field-weighted term score + coverage multiplier. Returns (score, evidence).

    evidence maps term -> [fields it hit], so callers can show WHY a page matched
    (gbrain's `evidence` tag). Coverage rewards matching more of the query: a page
    that hits every term beats one that hammers a single term in one field.
    """
    total = 0.0
    evidence = {}
    matched_terms = 0
    for t in terms:
        pat = re.compile(r"\b" + re.escape(t) + r"\b")
        term_score = 0.0
        hit_fields = []
        for fname, weight in FIELD_WEIGHTS.items():
            n = len(pat.findall(fields[fname]))
            if n:
                term_score += weight * min(n, PER_FIELD_CAP)
                hit_fields.append(fname)
        if term_score:
            matched_terms += 1
            evidence[t] = hit_fields
            total += term_score
    if not matched_terms:
        return 0.0, {}
    coverage = matched_terms / len(terms)            # 0..1
    return total * (0.4 + 0.6 * coverage), evidence   # partial match floored at 0.4x


def recency_norm(updated: str, today: date) -> float:
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", updated or "")
    if not m:
        return 0.3
    try:
        age = (today - date(int(m.group(1)), int(m.group(2)), int(m.group(3)))).days
    except ValueError:
        return 0.3
    return max(0.0, min(1.0, 1 - age / RECENCY_HORIZON_DAYS))


def rank(articles, query, indeg, k=8, mode="keyword"):
    """Rank articles with the current field-weighted keyword scorer."""
    terms = tokenize(query)
    if not terms:
        return terms, []
    today = date.today()
    max_deg = max(indeg.values()) if indeg else 1
    results = []
    for a in articles:
        kw, evidence = score_keyword(article_fields(a), terms)
        if kw <= 0:
            continue
        cen = indeg.get(a["stem"].lower(), 0) / max_deg
        rec = recency_norm(a.get("updated", ""), today)
        final = kw * (1 + CENTRALITY_BOOST * cen + RECENCY_BOOST * rec)
        results.append({
            "score": round(final, 2),
            "path": a.get("path", ""),
            "category": a.get("category", ""),
            "stem": a.get("stem", ""),
            "title": a.get("title", ""),
            "claim": a.get("claim", ""),
            "updated": a.get("updated", ""),
            "links_out": len(a.get("links", [])),
            "links_in": indeg.get(a["stem"].lower(), 0),
            "evidence": {t: fs for t, fs in evidence.items()},
            "scorer": mode,
        })
    results.sort(key=lambda r: (-r["score"], -r["links_in"], r["stem"]))
    for i, r in enumerate(results[:k], 1):
        r["rank"] = i
    return terms, results[:k]


def staleness_note(index: dict, root: Path = ROOT, index_path: Path = INDEX) -> str:
    """Warn on exact disk/index content drift; fall back to nanosecond mtimes."""
    wiki = root / "KB" / "wiki"
    if not wiki.is_dir():
        return ""
    rows = index.get("articles", [])
    indexed = {
        row.get("path"): row.get("content_hash")
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("path"), str)
    }
    disk = [path for path in wiki.rglob("*.md") if path.name != "_index.md"]
    if indexed and all(isinstance(value, str) and value for value in indexed.values()):
        drifted = 0
        disk_paths = set()
        for path in disk:
            rel = path.relative_to(root).as_posix()
            disk_paths.add(rel)
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                drifted += 1
                continue
            if indexed.get(rel) != digest:
                drifted += 1
        drifted += len(set(indexed) - disk_paths)
        if drifted:
            return (f"index content drift: {drifted} path(s) added, removed, or changed — "
                    f"run `python3 tools/kb-index.py` to refresh")
        return ""

    try:
        index_ns = index_path.stat().st_mtime_ns
    except OSError:
        return "index file missing — run `python3 tools/kb-index.py` to refresh"
    newer = 0
    for path in disk:
        try:
            if path.stat().st_mtime_ns > index_ns:
                newer += 1
        except OSError:
            newer += 1
    if newer:
        return (f"legacy index has no content hashes; {newer} KB file(s) newer than index — "
                f"run `python3 tools/kb-index.py` to refresh")
    return ""


def main(argv):
    as_json = False
    k = 8
    query_parts = []
    it = iter(argv[1:])
    for a in it:
        if a == "--json":
            as_json = True
        elif a == "--k" or a == "--k=":          # space form: --k 12
            try:
                k = int(next(it))
            except (StopIteration, ValueError):
                print("--k needs an integer (e.g. --k 12)", file=sys.stderr)
                return 1
        elif a.startswith("--k="):                # glued form: --k=12
            try:
                k = int(a.split("=", 1)[1])
            except ValueError:
                print("--k needs an integer (e.g. --k=12)", file=sys.stderr)
                return 1
        elif a.startswith("--"):                  # unknown flag (reserved: --raw, …) — ignore
            continue
        else:
            query_parts.append(a)                 # positional token = part of the query
    if not query_parts:
        print('usage: kb-query.py "<query>" [--json] [--k N]', file=sys.stderr)
        return 1
    if k < 1:
        print("--k must be a positive integer (e.g. --k 8)", file=sys.stderr)
        return 1
    query = " ".join(query_parts)
    if not INDEX.exists():
        print(f"FATAL: {INDEX} missing — run `python3 tools/kb-index.py` first", file=sys.stderr)
        return 2
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    articles = index.get("articles", [])
    indeg = build_indegree(articles)
    terms, hits = rank(articles, query, indeg, k=k)

    note = staleness_note(index)
    if not terms:
        print("no searchable terms in query (all stopwords?)", file=sys.stderr)
        return 1

    if as_json:
        print(json.dumps({
            "query": query, "terms": terms, "scorer": "keyword",
            "retrieval": {"ranker": "keyword", "tool": "kb-query.py", "k": k,
                          "version": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12],
                          "index_inputs_hash": index.get("inputs_hash", "")},
            "total_matched": len(hits), "corpus": index.get("article_count", len(articles)),
            "stale": note, "results": hits,
        }, ensure_ascii=False, indent=1))
        return 0

    if note:
        print(f"  ! {note}", file=sys.stderr)
    print(f'=== KB-QUERY: "{query}" · scorer=keyword k={k} · terms={terms} · '
          f'{len(hits)} of {index.get("article_count", len(articles))} ===')
    if not hits:
        print("  no matches — loosen the query, or the concept may be a gap (propose a gap: bin/kb write put --kind gap).")
    for r in hits:
        ev = ", ".join(f"{t}→{'/'.join(fs)}" for t, fs in r["evidence"].items())
        claim = (r["claim"][:150] + "…") if len(r["claim"]) > 150 else r["claim"]
        print(f'{r["rank"]:>2}. [{r["score"]:>6}] {r["category"]}/{r["stem"]}')
        if claim:
            print(f'        {claim}')
        print(f'        updated {r["updated"]} · in:{r["links_in"]} out:{r["links_out"]} · matched: {ev}')
        print(f'        {r["path"]}')
    print("=== done · read these pages to answer; propose a gap if they fall short ===")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
