#!/usr/bin/env python3
"""Capture and review answers against exact passages in the approved wiki."""
import argparse
from collections import Counter, defaultdict
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


spec = importlib.util.spec_from_file_location("kb_evidence", Path(__file__).with_name("kb-evidence.py"))
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)
writer = evidence.writer


def fingerprint(value):
    data = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


class Wiki:
    def __init__(self, root):
        self.root = root
        self.rows = writer.read_ledger(root)
        self.seal = writer.load_seal(root)
        self.expected = writer.expected_hashes(root, self.rows)
        if self.expected is None:
            raise ValueError("initialize and seal the wiki before capturing answers")
        self.pages = {}
        self.bases = {}
        self.check_snapshot()

    def check_snapshot(self):
        if (list((self.root / writer.OPS).glob("*.json")) or self.rows != writer.read_ledger(self.root)
                or self.seal != writer.load_seal(self.root)):
            raise ValueError("wiki operation or history changed during review; retry")

        for name, (_, _, digest) in self.pages.items():
            path = self.root / "KB/wiki" / name
            if path.resolve() != path or writer.file_hash(self.root, "KB/wiki/" + name) != digest:
                raise ValueError("cited page changed during review; retry")

    def basis(self, seq):
        if seq not in self.bases:
            self.bases[seq] = {"seq": seq, "seal": fingerprint(self.seal), "ledger_prefix": fingerprint(self.rows[:seq])}
        return self.bases[seq]

    def page(self, name):
        rel = Path(name)
        if rel.is_absolute() or ".." in rel.parts or rel.suffix != ".md" or rel.name == "_index.md":
            raise ValueError("cite an article path relative to KB/wiki")
        base = self.root / "KB/wiki"
        path = base / rel
        if path.resolve() != path or name != rel.as_posix():
            raise ValueError("noncanonical or symlinked wiki path")
        if name not in self.pages:
            data = path.read_bytes() if path.is_file() else None
            digest = hashlib.sha256(data).hexdigest() if data is not None else None
            expected = self.expected.get("KB/wiki/" + name)
            status = "drift" if digest != expected else "removed" if data is None else "approved"
            self.pages[name] = status, data.decode("utf-8") if status == "approved" else "", digest
        return self.pages[name]


def capture(wiki, question, answer, citations):
    if not question.strip() or not answer.strip():
        raise ValueError("provide a non-empty question and answer")
    pins = []
    for name, start, end in citations:
        status, text, digest = wiki.page(name)
        if status != "approved":
            raise ValueError(name + ": " + status)
        pinned = evidence.pin_lines(name, text, digest, int(start), int(end))
        if pinned not in pins:
            pins.append(pinned)
    payload = {"schema": "kb-answer/1", "question": question, "answer": answer, "citations": pins,
               "basis": wiki.basis(len(wiki.rows))}
    return dict(payload, receipt_id=fingerprint(payload))


def inspect(wiki, receipt):
    if not isinstance(receipt, dict):
        raise ValueError("receipt must be an object")
    payload = dict(receipt)
    rid = payload.pop("receipt_id", None)
    if payload.get("schema") != "kb-answer/1" or rid != fingerprint(payload):
        raise ValueError("receipt schema or checksum mismatch")
    if not all(isinstance(payload.get(k), str) and payload[k].strip() for k in ("question", "answer")):
        raise ValueError("invalid question or answer")
    basis = payload.get("basis")
    if not isinstance(basis, dict) or type(basis.get("seq")) != int or basis["seq"] < 0:
        raise ValueError("invalid ledger cursor")
    pins = payload.get("citations")
    if not isinstance(pins, list) or not pins:
        raise ValueError("at least one citation required")
    for pin in pins:
        evidence.validate_pin(pin)
    report = {"receipt_id": rid, "question": payload["question"], "citations": []}
    if basis["seq"] > len(wiki.rows) or basis != wiki.basis(basis["seq"]):
        return dict(report, status="history_changed")
    for pin in pins:
        name = pin["source"]
        status, text, digest = wiki.page(name)
        result = (evidence.locate(pin, name, text, digest) if status == "approved"
                  else {"source": name, "status": status})
        report["citations"].append(result)
    states = {c["status"] for c in report["citations"]}
    if states <= {"unchanged"}:
        status = "current"
    elif states <= {"found_in_revision", "unchanged"}:
        status = "review_context"
    else:
        status = "review_citation"
    return dict(report, status=status)


def audit(wiki, directory):
    if not directory.is_dir():
        raise ValueError("receipt directory missing")
    files = sorted(directory.glob("*.answer.json"))
    if not files:
        raise ValueError("no *.answer.json receipts in directory")
    rows = []
    for file in files:
        try:
            if file.is_symlink() or not file.is_file():
                raise ValueError("expected a regular receipt file")
            row = inspect(wiki, json.loads(file.read_text(encoding="utf-8")))
        except (ValueError, OSError, TypeError, KeyError) as exc:
            row = {"status": "invalid", "detail": str(exc)}
        rows.append(dict(row, file=file.name))
    return {"counts": dict(Counter(r["status"] for r in rows)), "receipts": rows}


def queue(report):
    groups = defaultdict(list)
    for row in report["receipts"]:
        if row["status"] == "current":
            continue
        # Group by page so a reviewer can repair several answers from one source read.
        affected = {c["source"] for c in row.get("citations", []) if c["status"] != "unchanged"}
        for page in sorted(affected) or [None]:
            item = {k: row[k] for k in ("file", "question", "receipt_id", "status", "detail") if k in row}
            item["findings"] = [c for c in row.get("citations", []) if c["source"] == page and c["status"] != "unchanged"]
            groups[page].append(item)
    return {"counts": report["counts"], "review": [
        {"page": page, "answers": rows} for page, rows in sorted(groups.items(), key=lambda pair: (-len(pair[1]), pair[0] or ""))]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("capture")
    p.add_argument("--question", required=True)
    p.add_argument("--answer-file", required=True, type=Path)
    p.add_argument("--cite", nargs=3, action="append", required=True, metavar=("PAGE", "FIRST", "LAST"))
    commands.add_parser("check").add_argument("receipt", type=Path)
    for name in ("audit", "queue"):
        commands.add_parser(name).add_argument("directory", type=Path)
    a = parser.parse_args()
    try:
        wiki = Wiki(a.root.resolve())
        if a.command == "capture":
            out = capture(wiki, a.question, a.answer_file.read_text(encoding="utf-8"), a.cite)
            attention = False
        elif a.command == "check":
            out = inspect(wiki, json.loads(a.receipt.read_text(encoding="utf-8")))
            attention = out["status"] != "current"
        else:
            out = audit(wiki, a.directory)
            attention = any(k != "current" for k in out["counts"])
            if a.command == "queue":
                out = queue(out)
        wiki.check_snapshot()
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return int(attention)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
