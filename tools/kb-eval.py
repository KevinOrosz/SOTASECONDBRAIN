#!/usr/bin/env python3
"""kb-eval.py — hand-labeled retrieval eval. The gate every retrieval change must pass.

Runs KB/output/retrieval-eval.json against both rankers and reports recall@6:
  old  = tools/kb-query.py            (field-weighted keyword over title/claim/section-NAMES)
  new  = tools/kb-graph-query.py      (RRF fusion of the above with BM25 over section BODIES)

Usage:
    python3 tools/kb-eval.py                 # human table
    python3 tools/kb-eval.py --json
    python3 tools/kb-eval.py --check         # 0 PASS / 1 FAIL — new must not regress combined
    python3 tools/kb-eval.py --regressions FILE [--check] [--json]
                                             # regression suite (spec §1.4); skips the hand-labeled run
                                             # unless --check; exit 1 on an invariant violation or a failed case

Why hand-labeled and not LLM-as-judge: one audited method's reported 66.7% win rate fell to
~39% after correcting position bias alone. Gold sets here were written from article titles and
Core Claims BEFORE either ranker was run, then supplemented with body-content questions whose
answers deliberately do NOT appear in any title or claim — because that is the only shape that
fairly tests a body-text index against a title-weighted one.

Read-only. Stdlib only. Python 3.9.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

K = 6

# Regression case shape, spec §1.4. Values are accepted types; keys are required unless in CASE_OPTIONAL.
_S, _L, _I = (str,), (list,), (int,)
CASE_SCHEMA = {
    "id": _S, "kind": _S, "q": _S, "expected": _L, "forbidden": _L, "origin": _S, "landed": _S, "status": _S,
    "gold_source": _S, "gold_locked": _S, "evidence_stems": _L, "named_stems": _L, "retrieval_at": _S,
    "pages": _L, "targets": _L, "ranker": _S, "k": _I, "failing_version": _S, "landed_version": _S,
    "ledger_seq": (int, type(None)),
}
CASE_OPTIONAL = {"retired_reason": _S}
KINDS, STATUSES = ("answer", "retrieval", "artifact"), ("active", "dormant", "retired")
GOLD_SOURCES = ("owner-verbatim", "rules", "evidence-scan")
ID_RE = re.compile(r"^r-(\d{4,})$")

# Evaluation honesty (spec §1.5). A judge verdict is one of VERDICTS with a cited evidence span; anything
# else counts as FAIL. Every stored verdict is bound to BIND (corpus seal, case, tool source) and is stale,
# so never counted, once any of the three moves.
VERDICTS = ("pass", "fail", "unclear")
BIND = ("corpus", "case", "tools")
CASE_BIND_KEYS = ("kind", "q", "expected", "forbidden", "targets", "ranker", "k")
REPLAY_ALL = "KB/inbox/_corrections/_replay-all"


def _sha(data) -> str:
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode("utf-8")).hexdigest()


def corpus_seal(root: Path, skip=()) -> str:
    """sha256 over every KB/wiki/**/*.md (path + bytes). Generated _index.md pages and `skip` stay out."""
    wiki = root / "KB" / "wiki"
    rows = ["%s %s" % (p.relative_to(root).as_posix(), _sha(p.read_bytes())) for p in sorted(wiki.rglob("*.md"))
            if p.name != "_index.md" and p.relative_to(root).as_posix() not in skip]
    return _sha("\n".join(rows))


def case_hash(case: dict) -> str:
    return _sha(json.dumps({k: case.get(k) for k in CASE_BIND_KEYS}, sort_keys=True, ensure_ascii=False))


def tools_hash(root: Path) -> str:
    d = root / "tools" if (root / "tools").is_dir() else Path(__file__).resolve().parent
    return _sha("\n".join("%s %s" % (p.name, _sha(p.read_bytes())) for p in sorted(d.glob("*.py"))))


def binding(root: Path, case: dict, skip=()) -> dict:
    return {"corpus": corpus_seal(root, skip), "case": case_hash(case), "tools": tools_hash(root)}


def stale(bound, now: dict) -> list:
    """The BIND keys whose hash moved; a missing or malformed binding is stale on every key."""
    if not isinstance(bound, dict):
        return list(BIND)
    return [k for k in BIND if bound.get(k) != now[k]]


def forbidden_hit(answer: str, forbidden) -> list:
    low = answer.lower()
    return [f for f in forbidden if f and f.lower() in low]


def judge_pass(res, answer: str, forbidden=()) -> tuple:
    """(passed, reason). Only a schema-valid "pass" citing a span found verbatim in the answer passes."""
    if not isinstance(res, dict) or res.get("verdict") not in VERDICTS:
        return False, "malformed: verdict not one of %s" % "/".join(VERDICTS)
    ev = res.get("evidence")
    if not isinstance(ev, str) or not ev.strip() or ev.strip() not in answer:
        return False, "malformed: evidence span missing or not in the answer"
    pts = res.get("points", [])
    if not (isinstance(pts, list) and all(isinstance(p, dict) and isinstance(p.get("met"), bool) for p in pts)):
        return False, "malformed: points"
    if res["verdict"] != "pass":
        return False, res["verdict"]
    if not all(p["met"] for p in pts):
        return False, "pass with an unmet point"
    hit = forbidden_hit(answer, forbidden)
    return (False, "forbidden literal %s" % hit) if hit else (True, "pass")


def fresh_verdicts(root: Path, cases: list) -> dict:
    """case id -> (passed, reason) for answer cases with a fresh replay-all verdict; stale ones are left out."""
    d = root / REPLAY_ALL
    try:
        man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for c in cases:
        run = man.get("runs", {}).get(c["id"])
        ans, jf = d / "results" / ("replay-%s.md" % c["id"]), d / "results" / ("judge-%s.json" % c["id"])
        if not run or not ans.is_file() or not jf.is_file() or stale(run.get("binding"), binding(root, c)):
            continue
        answer = ans.read_text(encoding="utf-8")
        try:
            res = json.loads(jf.read_text(encoding="utf-8"))
        except ValueError:
            res = None
        out[c["id"]] = judge_pass(res, answer, c["forbidden"])
    return out


def load(name: str):
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(name.replace("-", "_")[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(root: Path):
    ev = json.loads((root / "KB" / "output" / "retrieval-eval.json").read_text(encoding="utf-8"))
    kbq, kbg = load("kb-query.py"), load("kb-graph-query.py")
    index = json.loads((root / "KB" / "output" / "kb-index.json").read_text(encoding="utf-8"))
    arts = index["articles"]
    indeg = kbq.build_indegree(arts)
    graph = kbg.Graph(root)
    stems = {a["stem"] for a in graph.g["nodes"]["article"]}

    rows, missing_gold = [], []
    for q in ev["questions"]:
        gold = set(q["gold"])
        for g in gold:
            if g not in stems:
                missing_gold.append((q["id"], g))
        _, oh = kbq.rank(arts, q["q"], indeg, k=K)
        old = {h["stem"] for h in oh}
        new = {r["stem"] for r in kbg.verb_search(root, graph, q["q"], K)["results"]}
        rows.append({
            "id": q["id"], "shape": q["shape"], "q": q["q"],
            "old": len(gold & old) / len(gold), "new": len(gold & new) / len(gold),
            "missed_new": sorted(gold - new),
        })

    def mean(key, shapes=None):
        sel = [r for r in rows if shapes is None or r["shape"] in shapes]
        return (sum(r[key] for r in sel) / len(sel)) if sel else 0.0

    body = {"body"}
    lookup = {s for s in {r["shape"] for r in rows} if s not in body}
    return {
        "questions": len(rows),
        "recall_at": K,
        "old": {"combined": mean("old"), "lookup": mean("old", lookup), "body": mean("old", body)},
        "new": {"combined": mean("new"), "lookup": mean("new", lookup), "body": mean("new", body)},
        "improved": sum(1 for r in rows if r["new"] > r["old"]),
        "regressed": sum(1 for r in rows if r["new"] < r["old"]),
        "tied": sum(1 for r in rows if r["new"] == r["old"]),
        "missing_gold": missing_gold,
        "rows": rows,
    }


def validate_cases(cases):
    """Schema (I-2) and invariants I-1, I-3, I-4, I-5 over parsed rows. Returns violation strings."""
    bad, last, rule_origins = [], 0, {}
    for n, c in enumerate(cases, 1):
        if not isinstance(c, dict):
            bad.append("row %d: not an object" % n)
            continue
        cid = c.get("id", "row %d" % n)
        for key, types in CASE_SCHEMA.items():
            if key not in c:
                bad.append("%s: I-2 missing key %s" % (cid, key))
            elif not isinstance(c[key], types) or (types == _I and isinstance(c[key], bool)):
                bad.append("%s: I-2 key %s has wrong type" % (cid, key))
        for key in c:
            if key not in CASE_SCHEMA and key not in CASE_OPTIONAL:
                bad.append("%s: I-2 unknown key %s" % (cid, key))
        if bad and bad[-1].startswith("%s: I-2" % cid):
            continue  # shape is broken; the semantic checks below would only add noise
        if c["kind"] not in KINDS or c["status"] not in STATUSES or c["gold_source"] not in GOLD_SOURCES:
            bad.append("%s: I-2 kind/status/gold_source outside its vocabulary" % cid)
        if c["status"] == "retired" and not c.get("retired_reason"):
            bad.append("%s: I-2 retired case needs retired_reason" % cid)
        m = ID_RE.match(c["id"])
        if not m:
            bad.append("%s: I-1 id is not r-NNNN" % cid)
        elif int(m.group(1)) <= last:
            bad.append("%s: I-1 id is not unique and monotonic" % cid)
        else:
            last = int(m.group(1))
        if c["kind"] == "retrieval":
            if not (set(c["expected"]) <= set(c["evidence_stems"]) | set(c["named_stems"])):
                bad.append("%s: I-3 gold not within evidence_stems + named_stems" % cid)
            if c["expected"] and not (c["gold_locked"] and c["retrieval_at"] and c["gold_locked"] < c["retrieval_at"]):
                bad.append("%s: I-3 gold_locked must precede retrieval_at" % cid)
            if not c["expected"] and not c["forbidden"]:
                bad.append("%s: I-2 retrieval case with no expected and no forbidden" % cid)
        if c["kind"] == "artifact":
            if not c["targets"]:
                bad.append("%s: I-2 artifact case without targets" % cid)
            if not c["expected"] and not c["forbidden"]:
                bad.append("%s: I-4 artifact case with empty expected needs forbidden" % cid)
        if c["origin"].startswith("rule:"):
            if c["origin"] in rule_origins:
                bad.append("%s: I-5 origin %s already used by %s" % (cid, c["origin"], rule_origins[c["origin"]]))
            rule_origins[c["origin"]] = c["id"]
    return bad


def _case_retrieval(root, c, ctx):
    if "arts" not in ctx:
        kbq = load("kb-query.py")
        index = json.loads((root / "KB" / "output" / "kb-index.json").read_text(encoding="utf-8"))
        ctx.update(kbq=kbq, arts=index["articles"], indeg=kbq.build_indegree(index["articles"]))
    _, hits = ctx["kbq"].rank(ctx["arts"], c["q"], ctx["indeg"], k=c["k"])
    got = {h["stem"] for h in hits}
    miss, hit = sorted(set(c["expected"]) - got), sorted(set(c["forbidden"]) & got)
    return [("expected stem not in top-%d: %s" % (c["k"], miss) if miss else ""),
            ("forbidden stem in top-%d: %s" % (c["k"], hit) if hit else "")]


def _case_artifact(root, c, ctx):
    files = sorted({p for t in c["targets"] for p in root.glob(t) if p.is_file()})
    if not files:
        return ["no target file matches %s" % c["targets"]]
    texts = [f.read_text(encoding="utf-8", errors="replace") for f in files]
    out = ["expected /%s/ matches no target" % e for e in c["expected"]
           if not any(re.search(e, t, re.M) for t in texts)]
    out += ["forbidden /%s/ matches %s" % (f, files[i].relative_to(root).as_posix())
            for f in c["forbidden"] for i, t in enumerate(texts) if re.search(f, t, re.M)]
    return out


def regressions(root: Path, path: Path):
    """Validate then run every deterministic case. Dormant and retired cases are counted, never run. An active
    answer case counts from its fresh replay-all verdict; with none it is UNCHECKED, never a pass."""
    res = {"cases": 0, "checked": 0, "passed": 0, "failed": 0, "answer_passed": 0, "unchecked": 0,
           "unchecked_ids": [], "dormant": 0, "retired": 0, "invalid": 0, "violations": [], "failures": []}
    cases = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                cases.append(json.loads(line))
            except ValueError:
                res["violations"].append("line %d: not JSON" % n)
    res["cases"] = len(cases)
    res["violations"] += validate_cases(cases)
    res["invalid"] = len(res["violations"])
    if res["invalid"]:
        return res
    ctx = {}
    verdicts = fresh_verdicts(root, [c for c in cases if c["status"] == "active" and c["kind"] == "answer"])
    for c in cases:
        if c["status"] == "dormant":
            res["dormant"] += 1
        elif c["status"] == "retired":
            res["retired"] += 1
        elif c["kind"] == "answer":
            if c["id"] not in verdicts:
                res["unchecked"] += 1
                res["unchecked_ids"].append(c["id"])
                continue
            ok, why = verdicts[c["id"]]
            res["checked"] += 1
            if ok:
                res["answer_passed"] += 1
            else:
                res["failed"] += 1
                res["failures"].append({"id": c["id"], "origin": c["origin"], "problems": ["judge: " + why]})
        else:
            res["checked"] += 1
            try:
                problems = (_case_retrieval if c["kind"] == "retrieval" else _case_artifact)(root, c, ctx)
            except (OSError, ValueError, KeyError, re.error) as e:
                problems = ["could not run: %s" % e]
            problems = [p for p in problems if p]
            if problems:
                res["failed"] += 1
                res["failures"].append({"id": c["id"], "origin": c["origin"], "problems": problems})
            else:
                res["passed"] += 1
    return res


def main(argv):
    ap = argparse.ArgumentParser(description="Hand-labeled retrieval eval (recall@%d)." % K)
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true", help="exit 1 if the new ranker regresses combined recall")
    ap.add_argument("--regressions", metavar="FILE", help="run the regression suite (spec §1.4) from FILE")
    a = ap.parse_args(argv[1:])
    root = Path(a.root).resolve()
    if a.regressions:
        return main_regressions(a, root)
    res = run(root)

    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        print("=== RETRIEVAL EVAL · recall@%d · %d hand-labeled questions ===" % (K, res["questions"]))
        print("%4s %-7s %5s %5s  %s" % ("#", "shape", "old", "new", "query"))
        for r in res["rows"]:
            flag = "  ^" if r["new"] > r["old"] else ("  v" if r["new"] < r["old"] else "")
            print("%4d %-7s %5.2f %5.2f  %s%s" % (r["id"], r["shape"], r["old"], r["new"], r["q"][:48], flag))
        for band in ("lookup", "body", "combined"):
            o, n = res["old"][band], res["new"][band]
            print("  %-9s old %.3f -> new %.3f   %+.1f points" % (band, o, n, 100 * (n - o)))
        print("  improved %d · regressed %d · tied %d"
              % (res["improved"], res["regressed"], res["tied"]))
        if res["missing_gold"]:
            print("  ! gold stems not on disk: %s" % res["missing_gold"])

    if a.check:
        if res["missing_gold"]:
            print("FAIL  eval references gold articles that do not exist")
            return 1
        if res["new"]["combined"] < res["old"]["combined"]:
            print("FAIL  combined recall regressed: %.3f < %.3f"
                  % (res["new"]["combined"], res["old"]["combined"]))
            return 1
        print("PASS  combined recall %.3f (old %.3f)" % (res["new"]["combined"], res["old"]["combined"]))
    return 0


def main_regressions(a, root):
    path = Path(a.regressions)
    if not path.is_file():
        print("FAIL  regressions file not found: %s" % path)
        return 1
    reg = regressions(root, path)
    rc = 1 if reg["invalid"] or reg["failed"] else 0
    retrieval = None
    if a.check:
        retrieval = run(root)
        if retrieval["missing_gold"] or retrieval["new"]["combined"] < retrieval["old"]["combined"]:
            rc = 1
    if a.json:
        print(json.dumps({"retrieval": retrieval, "regressions": reg}, ensure_ascii=False, indent=1))
        return rc
    for v in reg["violations"]:
        print("INVALID  %s" % v)
    for f in reg["failures"]:
        print("FAIL  %s (%s): %s" % (f["id"], f["origin"], "; ".join(f["problems"])))
    for cid in reg["unchecked_ids"]:
        print("UNCHECKED  %s: answer case with no fresh verdict (run kb-correct replay-all)" % cid)
    if retrieval is not None:
        print("retrieval combined %.3f (old %.3f)" % (retrieval["new"]["combined"], retrieval["old"]["combined"]))
    print("%s  %d deterministic green, %d answer fresh pass, %d answer UNCHECKED, %d dormant (%d failed, %d invalid, "
          "%d retired)" % ("PASS" if rc == 0 else "FAIL", reg["passed"], reg["answer_passed"], reg["unchecked"],
                           reg["dormant"], reg["failed"], reg["invalid"], reg["retired"]))
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
