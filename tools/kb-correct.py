#!/usr/bin/env python3
"""kb-correct.py — the correction compiler core: one owner correction -> one validated page diff + case.

Usage:  python3 tools/kb-correct.py VERB [CID] [--root R] [--json] ...
  open      --q Q --owner-says TEXT --points-file F [--agent A]     F = the split step's result:
            {"points":[...], "forbidden":[...], "named_stems":[...], "terms":[...]}
  diagnose  CID                         evidence scan, gold lock, rank k=10, deterministic label
  packet    CID STEP [--run R]          (re)write one packet for a harness to fill
  record    CID STEP --result F [--run R]   read one filled result and advance the stage
  validate  CID                         overlays, regressions on the patched overlay, blind replay, verdict
  kill      CID --reason R              any open stage -> killed
  status    [CID]
  land | landed | replay-all            built in P3-S3; exit 2 until then
Exit:   0 ok · 1 gate failed · 2 usage, stage, schema or drift · 3 P2 (tools/kb-write.py) absent.
        kb-write exit codes map in: 3 or 4 -> 1, anything else nonzero -> 2.

Working dir KB/inbox/_corrections/C-NNNN/{record.json, packets/, results/, after.md, diff.patch}. This
            tool writes nothing else, except through kb-write put (contradictory and skill gaps).
Stages      open -> diagnosed -> compiled -> reviewed -> validated (-> proposed -> landed, P3-S3).
            diagnosed -> flagged (conflict, or reachable-retrieved = skill defect); compiled -> diagnosed
            (review REJECT, attempt 2 on the high tier); reviewed -> failed; any open stage -> killed.
            A gate miss or REJECT on attempt 2 kills. killed/flagged/failed/validated store and print
            one run-log row (record.json terminal_row); open refuses while an earlier cid lacks one.
LLM steps   The tool never calls a model. It writes packets/STEP[-RUN].json and reads results/ via
            record. Each packet holds only the keys in PACKETS (enforced in write_packet):
            conflict never sees ranker output; review sees only the diff and target; replay sees only q
            and an overlay path; judge never sees the diff or owner_says.
Labels      0 hits -> unreachable · RAW-only hits -> raw-only · gold ∩ top-k = ∅ -> reachable-unretrieved
            (retrieval case) · gold ⊆ top-k -> reachable-retrieved (skill gap, flagged). A partial overlap
            is reachable-unretrieved with diagnosis.evidence.ambiguous = true.
Gate        compile result {"files": {path: post-image}}: exactly one existing KB/wiki/**.md, <= 40
            changed lines, read_meta parses with Type kept, Updated bumped, Core Claim kept, kb-lint 0 FAIL.
Overlays    base and patched copies in $TMPDIR: KB/wiki, tools/, skills/, RETRIEVAL_FILES, active artifact
            targets; KB/RAW symlinked; KB/inbox excluded; active case origins redacted. Index + graph rebuilt.

Spec: docs/SPEC.md P3 §4-§6 and §1.3-§1.4. Zero LLM calls. Stdlib only, Python 3.9 compatible.
"""
from __future__ import annotations

import argparse
import contextlib
import difflib
import hashlib
import importlib.util
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_")[:-3], TOOLS / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(TOOLS))
import kb_config  # noqa: E402

kblint = _load("kb-lint.py")  # read_meta, lint, exit_code
kbq = _load("kb-query.py")    # rank, tokenize, build_indegree
kbe = _load("kb-eval.py")     # validate_cases, CASE_SCHEMA

CORR = "KB/inbox/_corrections"
KBW = TOOLS / "kb-write.py"
K = 10
MAX_LINES = 40
MAX_ATTEMPTS = 2
MAX_AFFECTED = 25
PATCHED_RUNS = 3
STAGES = ("open", "diagnosed", "compiled", "reviewed", "validated", "proposed", "landed", "killed", "flagged", "failed")
ROW_STAGES = ("killed", "flagged", "failed", "validated")  # each prints and stores one run-log row
OPEN_STAGES = ("open", "diagnosed", "compiled", "reviewed")
LABELS = ("unreachable", "raw-only", "reachable-unretrieved", "reachable-retrieved")
RETRIEVAL_FILES = ("KB/kb.json", "KB/output/retrieval-eval.json", "KB/output/kb-edge-types.json",
                   "KB/output/kb-gazetteer.json", "config/router.json")  # plus kb_config spine/registry/baseline
PACKETS = {  # step -> the only keys its packet may carry
    "conflict": {"step", "cid", "points", "evidence"},
    "compile": {"step", "cid", "q", "points", "forbidden", "target", "before", "evidence", "attempt", "tier",
                "findings"},
    "review": {"step", "cid", "target", "diff"},
    "replay": {"step", "cid", "run", "q", "overlay"},
    "judge": {"step", "cid", "run", "points", "answer"},
}
CID_RE = re.compile(r"^C-(\d{4})$")
CLAIM_RE = re.compile(r"^(## Core Claim\b|\*\*Core Claim:\*\*)", re.M)


class Fail(Exception):
    def __init__(self, code: int, detail: str):
        super().__init__(detail)
        self.code, self.detail = code, detail


def need(cond, detail: str, code: int = 2) -> None:
    if not cond:
        raise Fail(code, detail)


def sha256(data) -> str:
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode("utf-8")).hexdigest()


def stamp() -> str:
    return datetime.now().isoformat(timespec="microseconds")


def later(than: str) -> str:
    t = stamp()
    while t <= than:
        t = stamp()
    return t


# ---------- working dir ----------

def cdir(root: Path, cid: str) -> Path:
    return root / CORR / cid


def _write(root: Path, cid: str, rel: str, data: str) -> Path:
    """Every byte this tool writes goes under its own correction folder."""
    p = cdir(root, cid) / rel
    need(p.resolve().is_relative_to(cdir(root, cid).resolve()), "write outside %s: %s" % (cid, rel))
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    tmp.replace(p)
    return p


def load_record(root: Path, cid: str) -> dict:
    need(CID_RE.match(cid or ""), "cid %r is not C-NNNN" % cid)
    p = cdir(root, cid) / "record.json"
    need(p.is_file(), "%s: no record (run open first)" % cid)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError as e:
        raise Fail(2, "%s: record.json unreadable: %s" % (cid, e))


def save(root: Path, rec: dict) -> None:
    _write(root, rec["cid"], "record.json", json.dumps(rec, ensure_ascii=False, indent=1) + "\n")


def cids(root: Path) -> list:
    d = root / CORR
    return sorted(p.name for p in d.iterdir() if p.is_dir() and CID_RE.match(p.name)) if d.is_dir() else []


def expect(rec: dict, stages, waiting=None) -> None:
    need(rec["stage"] in stages, "%s is %s; this step needs %s" % (rec["cid"], rec["stage"], "/".join(stages)))
    if waiting is not None:
        need(rec.get("await") == waiting, "%s awaits %s, not %s" % (rec["cid"], rec.get("await"), waiting))


def run_row(rec: dict, result: str, notes: str) -> str:
    score = 1 if result == "KEEP" else 0
    return "%s | %s | skill:kb-correct | %s %s | correction | %d | %d | %s | %s" % (
        date.today().isoformat(), rec["agent"], rec["cid"], rec["q"][:48], score,
        max(1, rec["compile"].get("attempt", 0)), result, notes)


def finish(root: Path, rec: dict, stage: str, result: str, notes: str) -> None:
    """Terminal transition: stage, run-log row (stored + printed), overlays removed."""
    rec["stage"], rec["await"] = stage, None
    rec["terminal_row"] = run_row(rec, result, notes)
    for key in ("base_overlay", "patched_overlay"):
        ov = rec["validate"].pop(key, None)
        if ov:
            shutil.rmtree(Path(ov).parent if Path(ov).name in ("base", "patched") else ov, ignore_errors=True)
    save(root, rec)
    print("RUN-LOG  " + rec["terminal_row"], file=sys.stderr)


# ---------- packets ----------

def write_packet(root: Path, rec: dict, step: str, payload: dict, run: str = "") -> Path:
    payload = dict(payload, step=step, cid=rec["cid"])
    if run:
        payload["run"] = run
    extra = set(payload) - PACKETS[step]
    need(not extra, "packet %s carries keys outside its whitelist: %s" % (step, sorted(extra)))
    name = "packets/%s%s.json" % (step, "-" + run if run else "")
    return _write(root, rec["cid"], name, json.dumps(payload, ensure_ascii=False, indent=1) + "\n")


def target_text(root: Path, rel: str) -> str:
    p = root / rel
    return p.read_text(encoding="utf-8") if rel and p.is_file() else ""


def stem_path(root: Path, stem: str) -> str:
    for p in sorted((root / "KB" / "wiki").rglob("*.md")):
        if p.stem == stem and p.name != "_index.md":
            return p.relative_to(root).as_posix()
    return ""


def packet_payload(root: Path, rec: dict, step: str, run: str = "") -> dict:
    if step == "conflict":
        return {"points": rec["points"], "evidence": rec["paragraphs"]}
    if step == "compile":
        attempt = rec["compile"].get("attempt", 0) + 1
        target = rec["compile"].get("target") or next(
            (stem_path(root, s) for s in rec["named_stems"] + rec["evidence_stems"] if stem_path(root, s)), "")
        return {"q": rec["q"], "points": rec["points"], "forbidden": rec["forbidden"], "target": target,
                "before": target_text(root, target), "evidence": rec["paragraphs"], "attempt": attempt,
                "tier": "high" if attempt > 1 else "mid", "findings": rec["review"].get("findings", [])}
    if step == "review":
        return {"target": rec["compile"]["target"],
                "diff": (cdir(root, rec["cid"]) / "diff.patch").read_text(encoding="utf-8")}
    if step == "replay":
        runs = rec["validate"].get("runs", {})
        need(run in runs, "%s: no replay run %r (have %s)" % (rec["cid"], run, sorted(runs)))
        return {"q": runs[run]["q"], "overlay": rec["validate"][runs[run]["overlay"] + "_overlay"]}
    if step == "judge":
        runs = rec["validate"].get("runs", {})
        need(run in runs, "%s: no replay run %r" % (rec["cid"], run))
        answer = cdir(root, rec["cid"]) / "results" / ("replay-%s.md" % run)
        need(answer.is_file(), "%s: replay %s has no result yet" % (rec["cid"], run))
        return {"points": runs[run]["points"], "answer": answer.read_text(encoding="utf-8")}
    raise Fail(2, "unknown packet step %r (want %s)" % (step, sorted(PACKETS)))


def emit(root: Path, rec: dict, step: str, run: str = "") -> Path:
    return write_packet(root, rec, step, packet_payload(root, rec, step, run), run)


# ---------- P2 (kb-write) ----------

def kbw_put_gap(root: Path, rec: dict, gap_kind: str, target: str, why: str) -> str:
    need(KBW.is_file(), "P2 absent: tools/kb-write.py not found", 3)
    body = "# Correction %s: %s\n\n%s\n\nOwner says (verbatim, kept in record.json): see %s.\n" % (
        rec["cid"], rec["q"], why, rec["cid"])
    bf = _write(root, rec["cid"], "gap-%s.md" % gap_kind, body)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        rc = _load("kb-write.py").main(["put", "--root", str(root), "--json", "--agent", rec["agent"],
                                        "--kind", "gap", "--slug", "correction-%s-%s" % (rec["cid"].lower(), gap_kind),
                                        "--confidence", "moderate", "--source-ref", "owner:" + rec["opened"][:10],
                                        "--gap-kind", gap_kind, "--target", target, "--origin",
                                        "correction:" + rec["cid"], "--body-file", str(bf)])
    try:
        out = json.loads(buf.getvalue() or "{}")
    except ValueError:
        out = {}
    need(rc == 0, "kb-write put %s gap: rc %d %s" % (gap_kind, rc, out.get("detail", "")), 1 if rc in (3, 4) else 2)
    return out.get("id", "")


# ---------- open / diagnose ----------

def cmd_open(root: Path, a) -> dict:
    need(a.q and a.q.strip() and a.owner_says and a.owner_says.strip(), "open needs --q and --owner-says")
    try:
        split = json.loads(Path(a.points_file).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as e:
        raise Fail(2, "--points-file: %s" % e)
    need(isinstance(split, dict) and isinstance(split.get("points"), list) and split["points"]
         and all(isinstance(x, str) and x.strip() for x in split["points"]), "--points-file needs a non-empty points list")
    for key in ("forbidden", "named_stems", "terms"):
        need(isinstance(split.get(key, []), list) and all(isinstance(x, str) for x in split.get(key, [])),
             "--points-file %s must be a list of strings" % key)
    for c in cids(root):
        r = load_record(root, c)
        need(r.get("terminal_row"), "%s is %s with no terminal run-log row; kill or finish it first" % (c, r["stage"]))
    n = max([int(CID_RE.match(c).group(1)) for c in cids(root)] or [0]) + 1
    cid = "C-%04d" % n
    agent = a.agent or kb_config.load(root)["owner"]
    rec = {"cid": cid, "stage": "open", "await": "diagnose", "agent": agent, "opened": stamp(),
           "q": a.q.strip(), "owner_says": a.owner_says, "points": split["points"],
           "forbidden": split.get("forbidden", []), "named_stems": split.get("named_stems", []),
           "terms": [t.lower() for t in split.get("terms", [])]}
    rec["gold_sha256"] = sha256(json.dumps({k: rec[k] for k in ("owner_says", "points", "forbidden", "named_stems")},
                                           sort_keys=True, ensure_ascii=False))
    rec["gold_locked"] = stamp()
    rec.update({"evidence_stems": [], "retrieval_at": "", "topk": [], "paragraphs": [], "diagnosis": {},
                "compile": {}, "review": {}, "validate": {}, "land": {}, "terminal_row": ""})
    (root / CORR).mkdir(parents=True, exist_ok=True)
    save(root, rec)
    return {"cid": cid, "stage": "open", "gold_sha256": rec["gold_sha256"]}


def paragraphs(text: str):
    """(first line number, paragraph text) per blank-line separated block."""
    block, start = [], 0
    for i, line in enumerate(text.split("\n") + [""], 1):
        if line.strip():
            if not block:
                start = i
            block.append(line)
        elif block:
            yield start, "\n".join(block)
            block = []


def evidence_scan(root: Path, terms: list) -> list:
    """Paragraphs in KB/wiki (articles) and KB/RAW holding >= 2 distinct terms (>= 1 when only one term)."""
    want, hits = set(terms), []
    floor = min(2, len(want))
    for base in ("KB/wiki", "KB/RAW"):
        d = root / base
        if not d.is_dir():
            continue
        for p in sorted(x for x in d.rglob("*") if x.is_file() and x.name != "_index.md"):
            try:
                text = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for line, para in paragraphs(text):
                if floor and len(want & set(kbq.tokenize(para))) >= floor:
                    hits.append({"path": p.relative_to(root).as_posix(), "line": line, "text": para[:600]})
    return hits


def rank(root: Path, q: str) -> list:
    idx = root / "KB" / "output" / "kb-index.json"
    need(idx.is_file(), "KB/output/kb-index.json missing: run kb-index first")
    arts = json.loads(idx.read_text(encoding="utf-8"))["articles"]
    return [h["stem"] for h in kbq.rank(arts, q, kbq.build_indegree(arts), k=K)[1]]


def cmd_diagnose(root: Path, a) -> dict:
    rec = load_record(root, a.cid)
    expect(rec, ("open",))
    terms = rec["terms"] or sorted(set(kbq.tokenize(" ".join(rec["points"]))))
    hits = evidence_scan(root, terms)
    wiki = sorted({Path(h["path"]).stem for h in hits if h["path"].startswith("KB/wiki/")})
    raw = sorted({h["path"] for h in hits if h["path"].startswith("KB/RAW/")})
    gold = sorted(set(wiki) | set(rec["named_stems"]))
    # gold is locked before any ranking runs (I-3): hash it, stamp it, then rank
    rec["evidence_stems"], rec["paragraphs"] = wiki, hits
    rec["gold_sha256"] = sha256(json.dumps({"gold": gold, "prior": rec["gold_sha256"]}, sort_keys=True))
    rec["gold_locked"] = stamp()
    save(root, rec)
    topk = rank(root, rec["q"])
    rec["topk"], rec["retrieval_at"] = topk, later(rec["gold_locked"])
    found = set(gold) & set(topk)
    if not hits:
        label = "unreachable"
    elif not wiki:
        label = "raw-only"
    elif gold and set(gold) <= set(topk):
        label = "reachable-retrieved"
    else:
        label = "reachable-unretrieved"
    rec["diagnosis"] = {"label": label, "evidence": {
        "terms": terms, "hits": len(hits), "wiki_stems": wiki, "raw_paths": raw, "gold": gold,
        "missing": sorted(set(gold) - set(topk)), "ambiguous": bool(found) and label == "reachable-unretrieved"}}
    rec["stage"] = "diagnosed"
    out = {"cid": rec["cid"], "label": label, "gold": gold, "packets": []}
    if label == "reachable-retrieved":
        save(root, rec)
        gid = kbw_put_gap(root, rec, "skill", "skill:brain-think",
                          "Diagnosis reachable-retrieved: the evidence was retrieved and the answer still missed it.")
        rec["diagnosis"]["gap"] = gid
        finish(root, rec, "flagged", "FLAG", "diag:reachable-retrieved; skill gap %s" % gid)
        out.update(stage="flagged", gap=gid)
        return out
    if label == "unreachable":  # nothing to conflict with: no LLM check, straight to compile
        rec["await"] = "compile"
        save(root, rec)
        out["packets"].append(str(emit(root, rec, "compile")))
    else:
        rec["await"] = "conflict"
        save(root, rec)
        out["packets"].append(str(emit(root, rec, "conflict")))
    out["stage"] = "diagnosed"
    return out


# ---------- record ----------

def read_result(path, markdown=False):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, TypeError) as e:
        raise Fail(2, "--result: %s" % e)
    if markdown:
        need(text.strip(), "--result is empty")
        return text
    try:
        return json.loads(text)
    except ValueError as e:
        raise Fail(2, "--result is not JSON: %s" % e)


def shape(cond, step: str) -> None:
    need(cond, "%s result does not match its shape (spec P3 §4)" % step)


def changed_lines(before: str, after: str, rel: str):
    diff = list(difflib.unified_diff(before.splitlines(True), after.splitlines(True), "a/" + rel, "b/" + rel))
    plus = sum(1 for x in diff if x.startswith("+") and not x.startswith("+++"))
    minus = sum(1 for x in diff if x.startswith("-") and not x.startswith("---"))
    return "".join(diff), plus, minus


def minimality(root: Path, files: dict) -> tuple:
    """Spec P3 §6 step 8. Returns (problems, rel, diff, plus, minus)."""
    rels = list(files)
    if len(rels) != 1:
        return ["exactly one target file, got %d" % len(rels)], "", "", 0, 0
    rel, after = rels[0], files[rels[0]]
    probs = []
    if not (rel.startswith("KB/wiki/") and rel.endswith(".md") and ".." not in rel and (root / rel).is_file()):
        return ["target %s is not an existing KB/wiki/**.md" % rel], rel, "", 0, 0
    before = (root / rel).read_text(encoding="utf-8")
    diff, plus, minus = changed_lines(before, after, rel)
    if not diff:
        probs.append("post-image equals the page")
    if plus + minus > MAX_LINES:
        probs.append("%d changed lines > %d" % (plus + minus, MAX_LINES))
    with tempfile.TemporaryDirectory(prefix="kb-correct-gate-") as tmp:
        ov = Path(tmp)
        shutil.copytree(root / "KB" / "wiki", ov / "KB" / "wiki")
        for key in ("registry", "router", "baseline"):
            src = kb_config.path(root, key)
            if src.is_file():
                (ov / kb_config.rel(root, key)).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, ov / kb_config.rel(root, key))
        if (root / "KB" / "kb.json").is_file():
            shutil.copy2(root / "KB" / "kb.json", ov / "KB" / "kb.json")
        (ov / rel).write_text(after, encoding="utf-8")
        mb, ma = kblint.read_meta(root / rel), kblint.read_meta(ov / rel)
        if ma["header_end"] is None:
            probs.append("post-image header does not parse (no H1)")
        if ma["type"] != mb["type"]:
            probs.append("Type changed %s -> %s" % (mb["type"], ma["type"]))
        if not (ma["updated"] and (not mb["updated"] or ma["updated"] > mb["updated"])):
            probs.append("Updated not bumped (%s -> %s)" % (mb["updated"], ma["updated"]))
        if CLAIM_RE.search(before) and not CLAIM_RE.search(after):
            probs.append("Core Claim dropped")
        rep = kblint.lint(ov)
        probs += ["kb-lint FAIL %s %s" % (f["check"], f["detail"]) for f in rep["findings"] if f["severity"] == "FAIL"]
    return probs, rel, diff, plus, minus


def record_conflict(root: Path, rec: dict, res) -> dict:
    expect(rec, ("diagnosed",), "conflict")
    shape(isinstance(res, dict) and isinstance(res.get("conflict"), bool) and isinstance(res.get("primary", []), list)
          and isinstance(res.get("reason", ""), str), "conflict")
    rec["diagnosis"]["conflict"] = res
    if res["conflict"]:
        save(root, rec)
        prim = res.get("primary") or [{}]
        target = Path(prim[0].get("path", "")).stem or rec["cid"]
        gid = kbw_put_gap(root, rec, "contradictory", target, "Conflict check: %s" % res.get("reason", ""))
        rec["diagnosis"]["gap"] = gid
        finish(root, rec, "flagged", "FLAG", "diag:%s; conflict; gap %s" % (rec["diagnosis"]["label"], gid))
        return {"stage": "flagged", "gap": gid}
    rec["await"] = "compile"
    save(root, rec)
    return {"stage": "diagnosed", "packets": [str(emit(root, rec, "compile"))]}


def record_compile(root: Path, rec: dict, res) -> dict:
    expect(rec, ("diagnosed",), "compile")
    shape(isinstance(res, dict) and isinstance(res.get("files"), dict)
          and all(isinstance(k, str) and isinstance(v, str) for k, v in res["files"].items()), "compile")
    attempt = rec["compile"].get("attempt", 0) + 1
    probs, rel, diff, plus, minus = minimality(root, res["files"])
    rec["compile"]["attempt"] = attempt
    if probs:
        rec["compile"]["gate"] = probs
        if attempt >= MAX_ATTEMPTS:
            finish(root, rec, "killed", "KILL", "gate: %s" % "; ".join(probs)[:200])
        else:
            save(root, rec)
            emit(root, rec, "compile")
        raise Fail(1, "minimality gate: %s" % "; ".join(probs))
    before = (root / rel).read_bytes()
    after = res["files"][rel]
    _write(root, rec["cid"], "after.md", after)
    _write(root, rec["cid"], "diff.patch", diff)
    rec["compile"] = {"target": rel, "before_sha256": sha256(before), "after_sha256": sha256(after),
                      "changed_lines": {"plus": plus, "minus": minus}, "attempt": attempt}
    rec["stage"], rec["await"] = "compiled", "review"
    save(root, rec)
    return {"stage": "compiled", "target": rel, "changed": [plus, minus], "packets": [str(emit(root, rec, "review"))]}


def record_review(root: Path, rec: dict, res) -> dict:
    expect(rec, ("compiled",), "review")
    shape(isinstance(res, dict) and res.get("verdict") in ("APPROVE", "REJECT")
          and isinstance(res.get("findings", []), list), "review")
    rec["review"] = {"verdict": res["verdict"], "findings": res.get("findings", [])}
    if res["verdict"] == "APPROVE":
        rec["stage"], rec["await"] = "reviewed", "validate"
        save(root, rec)
        return {"stage": "reviewed"}
    if rec["compile"]["attempt"] >= MAX_ATTEMPTS:
        finish(root, rec, "killed", "KILL", "review REJECT on attempt %d" % rec["compile"]["attempt"])
        return {"stage": "killed"}
    rec["stage"], rec["await"] = "diagnosed", "compile"
    rec["compile"] = {"target": rec["compile"]["target"], "attempt": rec["compile"]["attempt"]}
    save(root, rec)
    return {"stage": "diagnosed", "packets": [str(emit(root, rec, "compile"))]}


def record_run(root: Path, rec: dict, step: str, run: str, res) -> dict:
    expect(rec, ("reviewed",), "replay")
    runs = rec["validate"].get("runs", {})
    need(run in runs, "%s: no replay run %r (have %s)" % (rec["cid"], run, sorted(runs)))
    if step == "replay":
        _write(root, rec["cid"], "results/replay-%s.md" % run, res)
        return {"stage": "reviewed", "packets": [str(emit(root, rec, "judge", run))]}
    shape(isinstance(res, dict) and res.get("verdict") in ("PASS", "FAIL") and isinstance(res.get("points"), list)
          and all(isinstance(p, dict) and isinstance(p.get("met"), bool) for p in res["points"]), "judge")
    need((cdir(root, rec["cid"]) / "results" / ("replay-%s.md" % run)).is_file(), "judge %s before its replay" % run)
    _write(root, rec["cid"], "results/judge-%s.json" % run, json.dumps(res, ensure_ascii=False, indent=1) + "\n")
    return {"stage": "reviewed", "judged": run}


def cmd_record(root: Path, a) -> dict:
    rec = load_record(root, a.cid)
    need(a.step in ("conflict", "compile", "review", "replay", "judge"), "record step %r unknown" % a.step)
    res = read_result(a.result, markdown=a.step == "replay")
    if a.step not in ("replay", "judge"):
        _write(root, rec["cid"], "results/%s.json" % a.step, json.dumps(res, ensure_ascii=False, indent=1) + "\n")
    out = {"conflict": record_conflict, "compile": record_compile, "review": record_review}.get(a.step)
    out = out(root, rec, res) if out else record_run(root, rec, a.step, a.run or "", res)
    return dict(out, cid=rec["cid"])


# ---------- validate ----------

def active_cases(root: Path) -> list:
    p = kb_config.path(root, "regressions")
    if not p.is_file():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def overlay(root: Path, dest: Path, patch=None) -> Path:
    """Spec P3 §6 step 10: one rebuilt copy of the instance with no inbox and redacted origins."""
    shutil.copytree(root / "KB" / "wiki", dest / "KB" / "wiki")
    src_tools = root / "tools" if (root / "tools").is_dir() else TOOLS
    shutil.copytree(src_tools, dest / "tools", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if (root / "skills").is_dir():
        shutil.copytree(root / "skills", dest / "skills")
    if (root / "KB" / "RAW").is_dir():
        (dest / "KB" / "RAW").symlink_to((root / "KB" / "RAW").resolve(), target_is_directory=True)
    cases = active_cases(root)
    rels = set(RETRIEVAL_FILES) | {kb_config.rel(root, k) for k in ("spine", "registry", "baseline", "catalog")}
    rels |= {p.relative_to(root).as_posix() for c in cases if c.get("status") == "active" and c.get("kind") == "artifact"
             for t in c.get("targets", []) for p in root.glob(t) if p.is_file()}
    for rel in sorted(rels):
        src, dst = root / rel, dest / rel
        if src.is_file() and not dst.exists() and not rel.startswith("KB/inbox"):
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    if cases:
        red = [dict(c, origin="redacted") if c.get("status") == "active" else c for c in cases]
        p = dest / kb_config.rel(root, "regressions")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in red), encoding="utf-8")
    if patch:
        (dest / patch[0]).write_text(patch[1], encoding="utf-8")
    (dest / "KB" / "output").mkdir(parents=True, exist_ok=True)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        need(_load("kb-index.py").build(dest) == 0, "overlay kb-index build failed")
        graph, errors = _load("kb-graph.py").build(dest, dest / "KB" / "output", quiet=True)
    need(graph is not None and not errors, "overlay kb-graph build failed: %s" % errors)
    (dest / "KB" / "output" / "kb-graph.json").write_text(json.dumps(graph, ensure_ascii=False, indent=1),
                                                         encoding="utf-8")
    return dest


def det_check(root: Path, ov: Path) -> int:
    """Spec P3 §6 step 11: kb-eval --root OV --regressions <repo jsonl> --check."""
    reg = kb_config.path(root, "regressions")
    if not reg.is_file():
        return 0
    return subprocess.run([sys.executable, str(ov / "tools" / "kb-eval.py"), "--root", str(ov), "--regressions",
                           str(reg), "--check"], capture_output=True).returncode


def draft_case(root: Path, rec: dict) -> dict:
    """The case validate proves; P3-S3 landed appends it with landed_version and ledger_seq."""
    nums = [int(kbe.ID_RE.match(c["id"]).group(1)) for c in active_cases(root) if kbe.ID_RE.match(c.get("id", ""))]
    retrieval = rec["diagnosis"]["label"] == "reachable-unretrieved"
    stem = Path(rec["compile"]["target"]).stem
    return {"id": "r-%04d" % (max(nums or [0]) + 1), "kind": "retrieval" if retrieval else "answer", "q": rec["q"],
            "expected": rec["diagnosis"]["evidence"]["gold"] if retrieval else rec["points"],
            "forbidden": [] if retrieval else rec["forbidden"], "origin": "correction:" + rec["cid"], "landed": "",
            "status": "active", "gold_source": "evidence-scan" if retrieval else "owner-verbatim",
            "gold_locked": rec["gold_locked"], "evidence_stems": rec["evidence_stems"],
            "named_stems": rec["named_stems"], "retrieval_at": rec["retrieval_at"], "pages": [stem], "targets": [],
            "ranker": "kb-query", "k": K, "failing_version": rec["compile"]["before_sha256"], "landed_version": "",
            "ledger_seq": None}


def forbidden_hit(answer: str, forbidden: list) -> list:
    low = answer.lower()
    return [f for f in forbidden if f and f.lower() in low]


def cmd_validate(root: Path, a) -> dict:
    rec = load_record(root, a.cid)
    expect(rec, ("reviewed",))
    rel = rec["compile"]["target"]
    need((root / rel).is_file() and sha256((root / rel).read_bytes()) == rec["compile"]["before_sha256"],
         "drift: %s changed since compile (before_sha256)" % rel)
    after = (cdir(root, rec["cid"]) / "after.md").read_text(encoding="utf-8")
    need(sha256(after) == rec["compile"]["after_sha256"], "drift: after.md changed since compile")
    case = draft_case(root, rec)
    bad = kbe.validate_cases([case])
    need(not bad, "draft case invalid: %s" % "; ".join(bad))
    v = rec["validate"]
    if not v.get("base_overlay"):
        tmp = Path(tempfile.mkdtemp(prefix="kb-correct-%s-" % rec["cid"]))
        base, patched = overlay(root, tmp / "base"), overlay(root, tmp / "patched", (rel, after))
        v.update(base_overlay=str(base), patched_overlay=str(patched), det_rc=det_check(root, patched),
                 affected=[], case=case)
        if case["kind"] == "retrieval":
            gold = set(case["expected"])
            base_top, patched_top = rank(base, rec["q"]), rank(patched, rec["q"])
            v.update(base=base_top, patched=patched_top)
            checks = {"base FAIL": not gold <= set(base_top), "patched flip": gold <= set(patched_top),
                      "det green": v["det_rc"] == 0, "review APPROVE": rec["review"]["verdict"] == "APPROVE"}
            return verdict(root, rec, checks, "base miss -> patched flip")
        stem = Path(rel).stem
        affected = [c for c in active_cases(root) if c.get("status") == "active" and c.get("kind") == "answer"
                    and (stem in c.get("pages", []) or rel in c.get("pages", []))]
        v["affected"] = [c["id"] for c in affected]
        if len(affected) > MAX_AFFECTED:
            save(root, rec)
            raise Fail(1, "%d affected answer cases > %d: stop and report" % (len(affected), MAX_AFFECTED))
        runs = {"base": {"overlay": "base", "q": rec["q"], "points": rec["points"], "forbidden": rec["forbidden"]}}
        for i in range(1, PATCHED_RUNS + 1):
            runs["patched-%d" % i] = {"overlay": "patched", "q": rec["q"], "points": rec["points"],
                                      "forbidden": rec["forbidden"]}
        for c in affected:
            runs["case-" + c["id"]] = {"overlay": "patched", "q": c["q"], "points": c["expected"],
                                       "forbidden": c["forbidden"]}
        v["runs"] = runs
        rec["await"] = "replay"
        save(root, rec)
        return {"cid": rec["cid"], "stage": "reviewed", "det_rc": v["det_rc"],
                "packets": [str(emit(root, rec, "replay", r)) for r in runs]}
    res_dir = cdir(root, rec["cid"]) / "results"
    missing = [r for r in v["runs"] if not (res_dir / ("judge-%s.json" % r)).is_file()]
    need(not missing, "%s: waiting on judge results for %s" % (rec["cid"], missing))
    passed = {}
    for r, spec in v["runs"].items():
        judged = json.loads((res_dir / ("judge-%s.json" % r)).read_text(encoding="utf-8"))
        answer = (res_dir / ("replay-%s.md" % r)).read_text(encoding="utf-8")
        passed[r] = judged["verdict"] == "PASS" and not forbidden_hit(answer, spec["forbidden"])
    v["passed"] = passed
    n_patched = sum(passed["patched-%d" % i] for i in range(1, PATCHED_RUNS + 1))
    checks = {"base FAIL": not passed["base"], "patched >=2/3": n_patched >= 2,
              "affected pass": all(passed["case-" + c] for c in v["affected"]),
              "det green": v["det_rc"] == 0, "review APPROVE": rec["review"]["verdict"] == "APPROVE"}
    return verdict(root, rec, checks, "base FAIL->patched %d/%d" % (n_patched, PATCHED_RUNS))


def verdict(root: Path, rec: dict, checks: dict, flip: str) -> dict:
    v = rec["validate"]
    v["verdict"] = "validated" if all(checks.values()) else "failed"
    v["checks"] = checks
    cl = rec["compile"]["changed_lines"]
    notes = "diag:%s; %s +%d/-%d; review %s; %s; det %s" % (
        rec["diagnosis"]["label"], rec["compile"]["target"], cl["plus"], cl["minus"], rec["review"]["verdict"],
        flip, "green" if v["det_rc"] == 0 else "rc %d" % v["det_rc"])
    if v["verdict"] == "validated":
        finish(root, rec, "validated", "KEEP", notes)
        return {"cid": rec["cid"], "stage": "validated", "checks": checks}
    notes += "; missed: %s" % ", ".join(k for k, ok in checks.items() if not ok)
    finish(root, rec, "failed", "FAIL", notes)
    raise Fail(1, "%s failed: %s" % (rec["cid"], ", ".join(k for k, ok in checks.items() if not ok)))


# ---------- kill / status / packet / later ----------

def cmd_kill(root: Path, a) -> dict:
    rec = load_record(root, a.cid)
    expect(rec, OPEN_STAGES)
    need(a.reason and a.reason.strip(), "kill needs --reason")
    finish(root, rec, "killed", "KILL", a.reason.strip())
    return {"cid": rec["cid"], "stage": "killed"}


def cmd_status(root: Path, a) -> dict:
    if a.cid:
        rec = load_record(root, a.cid)
        return {"items": [{k: rec[k] for k in ("cid", "stage", "await", "q", "diagnosis", "terminal_row")}]}
    return {"items": [{k: r[k] for k in ("cid", "stage", "await", "q")} for r in map(lambda c: load_record(root, c),
                                                                                      cids(root))]}


def cmd_packet(root: Path, a) -> dict:
    rec = load_record(root, a.cid)
    need(a.step in PACKETS, "packet step %r unknown (want %s)" % (a.step, sorted(PACKETS)))
    return {"cid": rec["cid"], "packet": str(emit(root, rec, a.step, a.run or ""))}


def cmd_later(root: Path, a) -> dict:
    raise Fail(2, "%s is built in P3-S3 (spec P3 §12); this core stops at validated" % a.verb)


VERB_FN = {"open": cmd_open, "diagnose": cmd_diagnose, "packet": cmd_packet, "record": cmd_record,
           "validate": cmd_validate, "kill": cmd_kill, "status": cmd_status,
           "land": cmd_later, "landed": cmd_later, "replay-all": cmd_later}


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="kb-correct.py", description="Correction compiler core (zero LLM calls).")
    ap.add_argument("verb", choices=sorted(VERB_FN))
    ap.add_argument("cid", nargs="?")
    ap.add_argument("step", nargs="?")
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--q")
    ap.add_argument("--owner-says")
    ap.add_argument("--points-file")
    ap.add_argument("--agent")
    ap.add_argument("--result")
    ap.add_argument("--run")
    ap.add_argument("--reason")
    ap.add_argument("--ledger-seq", type=int)
    return ap


def main(argv=None) -> int:
    a = parser().parse_args(argv)
    root = Path(a.root).resolve()
    try:
        need((root / "KB" / "wiki").is_dir(), "%s/KB/wiki not found" % root)
        if a.verb in ("diagnose", "packet", "record", "validate", "kill"):
            need(a.cid, "%s needs a CID" % a.verb)
        if a.verb in ("packet", "record"):
            need(a.step, "%s needs a STEP" % a.verb)
        if a.verb == "record":
            need(a.result, "record needs --result")
        out = VERB_FN[a.verb](root, a)
    except Fail as e:
        if a.json:
            print(json.dumps({"error": e.detail, "exit": e.code}, ensure_ascii=False))
        else:
            print("kb-correct %s: exit %d — %s" % (a.verb, e.code, e.detail), file=sys.stderr)
        return e.code
    print(json.dumps(dict(out, ok=True), ensure_ascii=False, indent=None if a.json else 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
