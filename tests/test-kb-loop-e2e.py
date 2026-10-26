#!/usr/bin/env python3
"""LOOP-E2E: the whole second-brain loop on a throwaway copy (spec §0 E2E acceptance 1-4, session 8).

Runs on kb_testkit.fixture(..., regressions=True, git=True). Every tool is driven as a real CLI
subprocess with --root <tmp>. Fixture JSON stands in for every model step (split, conflict, compile,
review): zero LLM calls. Step 4 is the discrimination proof: unland the fix and the new case must FAIL.
verify.sh runs this suite last.

Run: python3 tests/test-kb-loop-e2e.py
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
ROOT = TOOLS.parent
LIVE_DASH = ROOT / "KB" / "output" / "kb-search.html"
NO_NETWORK_RE = re.compile(r"(import|from) (requests|urllib|http\.client|socket|httpx|aiohttp)\b|subprocess.*(curl|wget|llm)|https?://")

sys.path.insert(0, str(TOOLS))
import kb_testkit  # noqa: E402

OWNER = "owner"
TARGET = "KB/wiki/alpha/first.md"
LONG = " ".join("Zebrafish evidence is recorded in this page body as plain prose sentence %d." % i for i in range(14))
FIRST_FIXED = kb_testkit.WIKI["alpha/first.md"].replace("**Updated:** 2026-01-01", "**Updated:** 2026-01-05") \
    .replace("First claim here.\n\n## Evidence", "First claim here; zebrafish carry it.\n\n## Evidence") \
    .replace("## Connections", LONG + "\n\n## Connections", 1)


def dash_stamp():
    return LIVE_DASH.stat().st_mtime_ns if LIVE_DASH.exists() else None


LIVE_DASH_BEFORE = dash_stamp()


def tearDownModule():
    assert dash_stamp() == LIVE_DASH_BEFORE, "suite touched the live kb-search.html"


class TestLoopE2E(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = kb_testkit.fixture(self.tmp, regressions=True, git=True)
        self.reg = self.root / "evals" / "regressions.jsonl"
        self.n = 0

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_tool(self, tool, *args, json_out=True):
        cmd = [sys.executable, str(TOOLS / tool)] + list(args) + ["--root", str(self.root)] + (["--json"] if json_out else [])
        p = subprocess.run(cmd, capture_output=True, text=True)
        out = p.stdout
        if json_out:
            try:
                out = json.loads(p.stdout or "{}")
            except ValueError:
                self.fail("%s %s: non-JSON stdout:\n%s\n%s" % (tool, args, p.stdout, p.stderr))
        return p.returncode, out

    def correct(self, *args):
        return self.run_tool("kb-correct.py", *args)

    def write(self, verb, *args):
        return self.run_tool("kb-write.py", verb, *args)

    def fx(self, data):
        """One fixture file standing in for a model step's output."""
        self.n += 1
        p = self.tmp / ("model-step-%02d.json" % self.n)
        p.write_text(json.dumps(data), encoding="utf-8")
        return str(p)

    def record(self):
        return json.loads((self.root / "KB/inbox/_corrections/C-0001/record.json").read_text(encoding="utf-8"))

    def cases(self):
        return [json.loads(x) for x in self.reg.read_text(encoding="utf-8").splitlines() if x.strip()]

    def regressions_rc(self):
        return self.run_tool("kb-eval.py", "--regressions", str(self.reg), json_out=False)

    def test_full_loop_closes_and_discriminates(self):
        self.assertEqual(self.write("seal")[0], 0)
        wiki_before = kb_testkit.tree_digest(self.root / "KB" / "wiki")
        raw_before = kb_testkit.tree_digest(self.root / "KB" / "RAW")
        self.assertEqual(self.regressions_rc()[0], 0, "seed regressions must pass before the loop starts")

        # 1. open -> diagnose -> record -> validate reaches validated
        split = {"points": ["zebrafish evidence lives in first"], "terms": ["zebrafish", "body"]}
        rc, out = self.correct("open", "--q", "zebrafish", "--owner-says", "It is in the first page.",
                               "--points-file", self.fx(split))
        self.assertEqual((rc, out.get("cid")), (0, "C-0001"), out)
        rc, out = self.correct("diagnose", "C-0001")
        self.assertEqual(rc, 0, out)
        if self.record()["await"] == "conflict":
            rc, out = self.correct("record", "C-0001", "conflict", "--result",
                                   self.fx({"conflict": False, "primary": [], "reason": ""}))
            self.assertEqual(rc, 0, out)
        rc, out = self.correct("record", "C-0001", "compile", "--result", self.fx({"files": {TARGET: FIRST_FIXED}}))
        self.assertEqual(rc, 0, out)
        rc, out = self.correct("record", "C-0001", "review", "--result", self.fx({"verdict": "APPROVE", "findings": []}))
        self.assertEqual(rc, 0, out)
        rc, out = self.correct("validate", "C-0001")
        self.assertEqual((rc, out.get("stage")), (0, "validated"), out)
        self.assertEqual(kb_testkit.tree_digest(self.root / "KB" / "wiki"), wiki_before, "validate mutated the wiki")
        self.assertEqual(kb_testkit.tree_digest(self.root / "KB" / "RAW"), raw_before, "validate mutated RAW")

        # 2. kb-correct land -> kb-write put -> kb-write land; the hook calls landed; regressions +1 row
        rc, out = self.correct("land", "C-0001")
        self.assertEqual(rc, 0, out)
        pid = out["proposal"]
        self.assertEqual(kb_testkit.tree_digest(self.root / "KB" / "wiki"), wiki_before, "land filed into the wiki")
        n_before = len(self.cases())
        rc, res = self.write("land", pid, "--endorsed-by", OWNER)
        self.assertEqual((rc, res.get("hook")), (0, "ok"), res)
        rows = self.cases()
        self.assertEqual(len(rows), n_before + 1)
        self.assertEqual((rows[-1]["origin"], rows[-1]["ledger_seq"]), ("correction:C-0001", res["ledger_seq"]))
        self.assertEqual(self.record()["stage"], "landed")

        # 3. every check passes
        rc, out = self.regressions_rc()
        self.assertEqual(rc, 0, out)
        rc, rep = self.run_tool("kb-lint.py", "--rule", "all")
        fails = [f for f in rep.get("findings", []) if f.get("severity") == "FAIL"]
        self.assertEqual(fails, [], rep)
        self.assertIn(rc, (0, 2), rep)
        page = (self.root / TARGET).read_bytes()
        ledger = [json.loads(x) for x in (self.root / "KB/inbox/_ledger.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        land_row = [r for r in ledger if r["seq"] == res["ledger_seq"]][0]
        self.assertEqual(land_row["event"], "land")
        self.assertEqual(land_row["files"][TARGET], hashlib.sha256(page).hexdigest(), "ledger hash != disk hash")
        self.assertEqual(rows[-1]["landed_version"], hashlib.sha256(page).hexdigest())
        text = page.decode("utf-8")
        self.assertEqual(len(re.findall(r"^\*\*Type:\*\* \S", text, re.M)), 1, text)
        self.assertEqual(len(re.findall(r"^\*\*Confidence:\*\* \S", text, re.M)), 1, text)
        self.assertEqual(len(re.findall(r"^\*\*Provenance:\*\*", text, re.M)), 1, text)

        # 4. discrimination proof: unland the fix, the new case must FAIL
        rc, out = self.write("unland", pid, "--endorsed-by", OWNER, "--reason", "E2E discrimination proof")
        self.assertEqual(rc, 0, out)
        self.assertEqual(kb_testkit.tree_digest(self.root / "KB" / "wiki"), wiki_before, "unland did not restore the wiki")
        rc, out = self.regressions_rc()
        self.assertEqual(rc, 1, "unland left regressions green: the new case does not discriminate\n" + out)
        self.assertIn(rows[-1]["id"], out)

    def test_no_network_or_model_calls(self):
        for tool in ("kb-correct.py", "kb-write.py", "kb-eval.py", "kb-lint.py"):
            hits = [ln for ln in (TOOLS / tool).read_text(encoding="utf-8").splitlines() if NO_NETWORK_RE.search(ln)]
            self.assertEqual(hits, [], tool)


if __name__ == "__main__":
    unittest.main(verbosity=2)
