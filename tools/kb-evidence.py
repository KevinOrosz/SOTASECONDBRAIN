#!/usr/bin/env python3
"""Read-only evidence review for an initialized knowledge base."""
import argparse
from collections import defaultdict, deque
import difflib
import hashlib
import importlib.util
import json
import re
from pathlib import Path
import sys
import tempfile


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


correct = load("kb-correct.py")
writer = load("kb-write.py")
evaluation = correct.kbe


def source(root, name, must_exist=True):
    base = (root / "KB/RAW").resolve()
    rel = Path(name)
    if not name or rel.is_absolute() or ".." in rel.parts:
        raise ValueError("use a path relative to KB/RAW")
    path = (base / rel).resolve()
    if not path.is_relative_to(base) or path == base:
        raise ValueError("source escapes KB/RAW")
    if must_exist and not path.is_file():
        raise ValueError("source missing: " + name)
    return path


def read_source(root, name):
    data = source(root, name).read_bytes()
    return data.decode("utf-8"), hashlib.sha256(data).hexdigest()


def diff(root, old, new):
    before, a = read_source(root, old)
    after, b = read_source(root, new)
    # Use line endings in the comparison so a final-newline-only change is visible.
    left, right = before.splitlines(True), after.splitlines(True)
    edits = [{"op": op, "old_offset": i, "new_offset": j, "removed": left[i:end_i], "added": right[j:end_j]}
             for op, i, end_i, j, end_j in difflib.SequenceMatcher(None, left, right, autojunk=False).get_opcodes()
             if op != "equal"]
    return {"old": old, "new": new, "old_sha256": a, "new_sha256": b, "edits": edits}


def pin(root, name, first, last):
    text, digest = read_source(root, name)
    lines = text.splitlines()
    if not 1 <= first <= last <= len(lines):
        raise ValueError("line range outside source")
    quoted = lines[first-1:last]
    if not any(line.strip() for line in quoted):
        raise ValueError("quotation is blank")
    return {"schema": 1, "source": name, "source_sha256": digest, "first": first, "last": last, "lines": quoted}


def check(root, receipt, revision=None):
    if not isinstance(receipt, dict) or receipt.get("schema") != 1:
        raise ValueError("unsupported pin schema")
    if not isinstance(receipt.get("source"), str) or not re.fullmatch("[0-9a-f]{64}", str(receipt.get("source_sha256", ""))):
        raise ValueError("malformed source or fingerprint")
    quote = receipt.get("lines")
    first, last = receipt.get("first"), receipt.get("last")
    if (not isinstance(quote, list) or not quote or not all(isinstance(x, str) for x in quote)
            or not any(x.strip() for x in quote) or type(first) != int or type(last) != int
            or first < 1 or last-first+1 != len(quote)):
        raise ValueError("malformed quote or range")
    name = revision or receipt["source"]
    text, digest = read_source(root, name)
    lines = text.splitlines()
    if digest == receipt["source_sha256"]:
        if lines[first-1:last] != quote:
            raise ValueError("pin range disagrees with original source bytes")
        matches, status = [first], "unchanged"
    else:
        matches = [i+1 for i, line in enumerate(lines) if line == quote[0] and lines[i:i+len(quote)] == quote]
        status = "missing" if not matches else "ambiguous" if len(matches) > 1 else "found_in_revision"
    return {"status": status, "source": name, "sha256": digest, "matching_start_lines": matches}


def impact(root, name):
    wanted = source(root, name, must_exist=False)
    pages, reverse, paths = {}, defaultdict(set), {}
    for page in sorted((root / "KB/wiki").rglob("*.md")):
        if page.name == "_index.md":
            continue
        stem = page.stem
        if stem in pages:
            raise ValueError("ambiguous page stem: " + stem)
        text = page.read_text(encoding="utf-8")
        pages[stem] = page.relative_to(root).as_posix()
        for dep in writer.kblint.read_meta(page)["depends_on"]:
            reverse[dep].add(stem)
        for ref in writer.fact_source(root, text)["source_refs"]:
            if ref.startswith("raw:"):
                rel = ref[4:]
                declared = source(root, rel, must_exist=False)
                resolved = writer.prov.raw_path(root, rel)
                if declared == wanted or resolved == wanted or (resolved is None and Path(str(declared) + ".md") == wanted):
                    paths[stem] = [stem]
    queue = deque(sorted(paths))
    while queue:
        parent = queue.popleft()
        for stem in sorted(reverse[parent] - paths.keys()):
            paths[stem] = paths[parent] + [stem]
            queue.append(stem)
    cases = correct.active_cases(root)
    bad = evaluation.validate_cases(cases)
    if bad:
        raise ValueError("invalid regression cases: " + "; ".join(bad))
    linked = []
    for case in cases:
        refs = set(case["pages"] + case["evidence_stems"] + case["named_stems"])
        if case["kind"] == "retrieval":
            refs.update(case["expected"] + case["forbidden"])
        if case["kind"] == "artifact":
            for pattern in case["targets"]:
                refs.update(p.relative_to(root).as_posix() for p in root.glob(pattern) if p.is_file())
        hits = sorted(stem for stem in paths if stem in refs or pages[stem] in refs)
        if hits:
            linked.append({"id": case["id"], "status": case["status"], "via_pages": hits})
    return {"source": name, "present": wanted.is_file(), "pages": [
        {"path": pages[s], "dependency_chain": paths[s]} for s in paths], "linked_cases": linked}


def rehearse(root, proposal, query, k):
    if not query.strip() or not 1 <= k <= 100:
        raise ValueError("provide a query and k between 1 and 100")
    writer.configure(root)
    if list((root / writer.OPS).glob("*.json")):
        raise ValueError("unfinished operation; recover before rehearsal")
    preview = writer.land_one(root, proposal, True)
    with tempfile.TemporaryDirectory(prefix="kb-rehearse-") as tmp:
        def ranked(label, postimages=None):
            ov = correct.overlay(root, Path(tmp) / label, postimages=postimages)
            result = evaluation.ranked(ov, query, "hybrid-graph", k)
            return [r["stem"] for r in result["results"]]
        before = ranked("base")
        after = ranked("candidate", preview["postimages"])
    again = writer.land_one(root, proposal, True)
    if preview["approval_payload"] != again["approval_payload"] or list((root / writer.OPS).glob("*.json")):
        raise ValueError("inputs changed during rehearsal; retry")
    return {"proposal": proposal, "payload_sha256": hashlib.sha256(preview["approval_payload"].encode()).hexdigest(),
            "query": query, "k": k, "before": before, "after": after, "warnings": preview["warnings"],
            "moved": [{"stem": s, "before": before.index(s)+1 if s in before else None,
                       "after": after.index(s)+1 if s in after else None} for s in dict.fromkeys(before+after)
                      if s not in before or s not in after or before.index(s) != after.index(s)]}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    verbs = p.add_subparsers(dest="verb", required=True)
    d = verbs.add_parser("diff")
    d.add_argument("old")
    d.add_argument("new")
    verbs.add_parser("impact").add_argument("source")
    q = verbs.add_parser("pin")
    q.add_argument("source")
    q.add_argument("first", type=int)
    q.add_argument("last", type=int)
    c = verbs.add_parser("check")
    c.add_argument("receipt", type=Path)
    c.add_argument("--revision")
    r = verbs.add_parser("rehearse")
    r.add_argument("proposal")
    r.add_argument("query")
    r.add_argument("--k", type=int, default=8)
    a = p.parse_args()
    root = a.root.resolve()
    try:
        if not (root / "KB/wiki").is_dir():
            raise ValueError("no initialized brain")
        if a.verb == "diff":
            out = diff(root, a.old, a.new)
        elif a.verb == "impact":
            out = impact(root, a.source)
        elif a.verb == "pin":
            out = pin(root, a.source, a.first, a.last)
        elif a.verb == "check":
            out = check(root, json.loads(a.receipt.read_text()), a.revision)
        else:
            out = rehearse(root, a.proposal, a.query, a.k)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return int(out.get("status") in ("missing", "ambiguous"))
    except (ValueError, OSError, KeyError, TypeError, writer.Fail, correct.Fail) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
