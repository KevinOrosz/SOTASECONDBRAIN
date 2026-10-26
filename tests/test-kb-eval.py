#!/usr/bin/env python3
"""Tests for kb-eval.py --regressions (spec §1.4 invariants, P3 seeds) and the land regressions gate.

Every case runs on kb_testkit.fixture(..., regressions=True) with --root <tmp>. The live seed file is
checked read-only. No suite touches the live KB/output/kb-search.html.

Run: python3 tools/test-kb-eval.py
"""
from __future__ import annotations

import contextlib
import io
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
ROOT = TOOLS.parent
LIVE_DASH = ROOT / "KB" / "output" / "kb-search.html"
SEEDS = ROOT / "templates" / "regressions.jsonl"  # the seed set bootstrap copies into an instance
NO_NETWORK_RE = re.compile(r"(import|from) (requests|urllib|http\.client|socket|httpx|aiohttp)\b|subprocess.*(curl|wget|llm)|https?://")

sys.path.insert(0, str(TOOLS))
import kb_testkit  # noqa: E402

kbe = kb_testkit.load("kb-eval.py")
kbw = kb_testkit.load("kb-write.py")


def dash_stamp():
    return LIVE_DASH.stat().st_mtime_ns if LIVE_DASH.exists() else None


LIVE_DASH_BEFORE = dash_stamp()


def tearDownModule():
    assert dash_stamp() == LIVE_DASH_BEFORE, "suite touched the live kb-search.html"


class Base(unittest.TestCase):
    git = False

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = kb_testkit.fixture(self.tmp, regressions=True, git=self.git)
        self.file = self.root / "evals" / "regressions.jsonl"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def rows(self):
        return [json.loads(x) for x in self.file.read_text(encoding="utf-8").splitlines() if x.strip()]

    def write(self, rows):
        self.file.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    def ev(self, *extra):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = kbe.main(["kb-eval.py", "--root", str(self.root), "--regressions", str(self.file), *extra])
        return rc, buf.getvalue()


class Regressions(Base):
    def test_01_fixture_suite_is_green_and_counts_skips(self):
        rc, out = self.ev()
        self.assertEqual(rc, 0, out)
        self.assertIn("3 deterministic green, 0 answer deferred, 1 dormant", out)

    def test_02_retrieval_gold_missing_from_topk_fails(self):
        rows = self.rows()
        rows[1]["q"] = "zebrafish"
        rows[1]["expected"], rows[1]["evidence_stems"] = ["third"], ["third"]
        self.write(rows)
        rc, out = self.ev()
        self.assertEqual(rc, 1)
        self.assertIn("r-0002", out)

    def test_03_forbidden_stem_in_topk_fails(self):
        rows = self.rows()
        rows[0]["forbidden"] = ["first"]
        rows[0]["q"] = "first claim"
        self.write(rows)
        rc, out = self.ev()
        self.assertEqual(rc, 1)
        self.assertIn("forbidden stem", out)

    def test_04_artifact_forbidden_and_missing_expected_fail(self):
        rows = self.rows()
        rows[2]["forbidden"] = ["Articles:"]
        rows[2]["expected"] = ["no such text"]
        self.write(rows)
        rc, res = self.ev("--json")
        self.assertEqual(rc, 1)
        self.assertEqual(json.loads(res)["regressions"]["failed"], 1)

    def test_05_answer_cases_never_run(self):
        rows = self.rows()
        rows[3]["status"] = "active"
        self.write(rows)
        rc, out = self.ev()
        self.assertEqual(rc, 0, out)
        self.assertIn("1 answer deferred, 0 dormant", out)

    def test_06_invariant_violations_exit_1(self):
        mutations = {
            "I-1 duplicate id": lambda r: r[1].update(id="r-0001"),
            "I-2 missing key": lambda r: r[0].pop("origin"),
            "I-2 wrong type": lambda r: r[0].update(k="ten"),
            "I-3 gold outside evidence": lambda r: r[1].update(expected=["third"]),
            "I-3 lock after retrieval": lambda r: r[1].update(gold_locked="2026-02-01T00:00:00Z"),
            "I-4 empty artifact": lambda r: r[2].update(forbidden=[], expected=[]),
            "I-5 duplicate rule origin": lambda r: r[3].update(origin="rule:no-parity-word"),
        }
        original = self.rows()
        for label, mutate in mutations.items():
            rows = json.loads(json.dumps(original))
            mutate(rows)
            self.write(rows)
            rc, out = self.ev()
            self.assertEqual(rc, 1, label)
            self.assertIn(label.split()[0], out, label)

    def test_07_retired_needs_reason_and_is_skipped(self):
        rows = self.rows()
        rows[0]["status"] = "retired"
        self.write(rows)
        self.assertEqual(self.ev()[0], 1)
        rows[0]["retired_reason"] = "superseded"
        self.write(rows)
        rc, out = self.ev()
        self.assertEqual(rc, 0, out)
        self.assertIn("1 retired", out)

    def test_08_live_seed_file_is_valid_and_shaped(self):
        cases = [json.loads(x) for x in SEEDS.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(kbe.validate_cases(cases), [])
        self.assertEqual([(c["kind"], c["status"]) for c in cases],
                         [("artifact", "active"), ("answer", "dormant"), ("answer", "dormant")])
        self.assertTrue(all(c["origin"].startswith("rule:") for c in cases))

    def test_09_no_network_or_model_calls(self):
        for name in ("kb-eval.py", "kb_testkit.py"):
            text = (TOOLS / name).read_text(encoding="utf-8")
            self.assertIsNone(NO_NETWORK_RE.search(text), name)


class LandGate(Base):
    git = True

    def setUp(self):
        super().setUp()
        self.body = self.tmp / "body.md"
        long = " ".join(["Inbox write-back lands through one gate with a ledger row and a seal."] * 12)
        self.body.write_text("# Fourth\n\n## Core Claim\n%s\n" % long, encoding="utf-8")

    def kbw(self, *args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            rc = kbw.main(list(args[:1]) + ["--root", str(self.root), "--json"] + list(args[1:]))
        return rc, json.loads(buf.getvalue())

    def propose(self):
        self.assertEqual(self.kbw("seal")[0], 0)
        rc, out = self.kbw("put", "--agent", "RESEARCHER", "--kind", "article", "--slug", "fourth", "--category",
                           "beta", "--confidence", "moderate", "--source-ref", "raw:source-one.md",
                           "--body-file", str(self.body))
        self.assertEqual(rc, 0, out)
        return out["id"]

    def test_10_resurrected_forbidden_answer_fails_gate_and_leaves_wiki_identical(self):
        pid = self.propose()
        wiki = kb_testkit.tree_digest(self.root / "KB" / "wiki")
        rc, out = self.kbw("land", pid, "--endorsed-by", "owner")
        self.assertEqual(rc, 3, out)
        self.assertEqual(kb_testkit.tree_digest(self.root / "KB" / "wiki"), wiki)

    def test_11_land_passes_when_the_case_is_retired(self):
        rows = self.rows()
        rows[0].update(status="retired", retired_reason="fixture")
        self.write(rows)
        pid = self.propose()
        rc, out = self.kbw("land", pid, "--endorsed-by", "owner")
        self.assertEqual(rc, 0, out)


if __name__ == "__main__":
    unittest.main()
