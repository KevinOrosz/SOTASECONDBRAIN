#!/usr/bin/env python3
"""Tests for kb-correct.py core (spec P3 §8 tests 1-8 and 13-19, session P3-S2).

Every case runs on kb_testkit.fixture(..., regressions=True) with --root <tmp>. Fixture JSON and markdown
files stand in for every LLM step (split, conflict, compile, review, replay, judge): zero model calls.
No suite touches the live KB/output/kb-search.html.

Run: python3 tests/test-kb-correct.py
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
from unittest import mock
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
ROOT = TOOLS.parent
LIVE_DASH = ROOT / "KB" / "output" / "kb-search.html"
NO_NETWORK_RE = re.compile(r"(import|from) (requests|urllib|http\.client|socket|httpx|aiohttp)\b|subprocess.*(curl|wget|llm)|https?://")

sys.path.insert(0, str(TOOLS))
import kb_testkit  # noqa: E402

kbc = kb_testkit.load("kb-correct.py")
kbe = kb_testkit.load("kb-eval.py")


def dash_stamp():
    return LIVE_DASH.stat().st_mtime_ns if LIVE_DASH.exists() else None


LIVE_DASH_BEFORE = dash_stamp()


def tearDownModule():
    assert dash_stamp() == LIVE_DASH_BEFORE, "suite touched the live kb-search.html"


OWNER_SAYS = "You missed it: the answer left out the shoreline material entirely."
RAW_TIDES = "Tide pools shelter kelp at low water.\n"
SECOND_PATCHED = """# Second

**Category:** alpha
**Sources:** [[RAW/source-two.md]]
**Updated:** 2026-01-05
**Type:** article

## Core Claim
Second claim.

## Evidence
Tide pools shelter kelp at low water, per the raw shoreline notes.

## Connections
- [[first]] — points back
"""
FIRST_PATCHED = kb_testkit.WIKI["alpha/first.md"].replace("**Updated:** 2026-01-01", "**Updated:** 2026-01-05") \
    .replace("First claim here.\n\n## Evidence", "First claim here; zebrafish carry it.\n\n## Evidence")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = kb_testkit.fixture(self.tmp, regressions=True)
        (self.root / "KB" / "RAW" / "tides.md").write_text(RAW_TIDES, encoding="utf-8")
        self.n = 0

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fx(self, data, ext="json"):
        """One fixture file standing in for an LLM step's output."""
        self.n += 1
        p = self.tmp / ("llm-%02d.%s" % (self.n, ext))
        p.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
        return str(p)

    def cli(self, *args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            rc = kbc.main(list(args) + ["--root", str(self.root), "--json"])
        return rc, json.loads(buf.getvalue())

    def rec(self, cid="C-0001"):
        return json.loads((self.root / kbc.CORR / cid / "record.json").read_text(encoding="utf-8"))

    def packet(self, name, cid="C-0001"):
        return json.loads((self.root / kbc.CORR / cid / "packets" / (name + ".json")).read_text(encoding="utf-8"))

    def open_raw(self):  # raw-only answer correction
        split = {"points": ["tide pools shelter kelp"], "forbidden": ["deep trench"], "named_stems": ["second"],
                 "terms": ["tide", "pools", "kelp"]}
        return self.cli("open", "--q", "what does second say about tide pools", "--owner-says", OWNER_SAYS,
                        "--points-file", self.fx(split))

    def open_retrieval(self):  # body-only fact the title-weighted ranker misses
        split = {"points": ["zebrafish evidence lives in first"], "terms": ["zebrafish", "body"]}
        return self.cli("open", "--ranker", "kb-query", "--q", "zebrafish", "--owner-says", "It is in the first page.",
                        "--points-file", self.fx(split))

    def to_reviewed(self, opener, target, after):
        self.assertEqual(opener()[0], 0)
        rc, out = self.cli("diagnose", "C-0001")
        self.assertEqual(rc, 0, out)
        if self.rec()["await"] == "conflict":
            self.assertEqual(self.cli("record", "C-0001", "conflict", "--result",
                                      self.fx({"conflict": False, "primary": [], "reason": ""}))[0], 0)
        rc, out = self.cli("record", "C-0001", "compile", "--result", self.fx({"files": {target: after}}))
        self.assertEqual(rc, 0, out)
        rc, out = self.cli("record", "C-0001", "review", "--result", self.fx({"verdict": "APPROVE", "findings": []}))
        self.assertEqual(rc, 0, out)

    def replay_and_judge(self, base_verdict="FAIL", patched=("PASS", "PASS", "PASS")):
        verdicts = dict({"base": base_verdict}, **{"patched-%d" % i: v for i, v in enumerate(patched, 1)})
        for run, v in verdicts.items():
            self.assertEqual(self.cli("record", "C-0001", "replay", "--run", run, "--result",
                                      self.fx("Answer for %s.\n" % run, "md"))[0], 0)
            judge = self.packet("judge-" + run)
            self.assertEqual(set(judge), kbc.PACKETS["judge"])
            self.assertEqual(self.cli("record", "C-0001", "judge", "--run", run, "--result", self.fx(
                {"points": [{"point": "tide pools shelter kelp", "met": v == "PASS", "quote": ""}],
                 "verdict": v.lower(), "evidence": "Answer for %s." % run}))[0], 0)


LONG = " ".join("Zebrafish evidence is recorded in this page body as plain prose sentence %d." % i for i in range(14))
FIRST_LONG = FIRST_PATCHED.replace("## Connections", LONG + "\n\n## Connections", 1)


class TestLand(Base):
    """Spec P3 §8 tests 9-11 plus the live hook path, on the fixture with a real kb-write."""

    def setUp(self):
        super().setUp()
        shutil.rmtree(self.tmp)
        self.tmp = Path(tempfile.mkdtemp())
        self.root = kb_testkit.fixture(self.tmp, regressions=True)  # no git: undo reads KB/inbox/_objects
        (self.root / "KB" / "RAW" / "tides.md").write_text(RAW_TIDES, encoding="utf-8")
        self.kbw = kb_testkit.load("kb-write.py")
        self.assertEqual(self.kbw_cli("seal")[0], 0)
        self.seeded = len(self.cases())

    def kbw_cli(self, *args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            rc = self.kbw.main(list(args[:1]) + ["--root", str(self.root), "--json"] + list(args[1:]))
        return rc, json.loads(buf.getvalue() or "{}")

    def validated(self):
        self.to_reviewed(self.open_retrieval, "KB/wiki/alpha/first.md", FIRST_LONG)
        rc, out = self.cli("validate", "C-0001")
        self.assertEqual((rc, out["stage"]), (0, "validated"), out)

    def proposed(self):
        self.validated()
        rc, out = self.cli("land", "C-0001")
        self.assertEqual(rc, 0, out)
        return out["proposal"]

    def cases(self):
        p = self.root / "evals" / "regressions.jsonl"
        return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]

    def regressions_rc(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return kbe.main_regressions(mock.Mock(regressions=str(self.root / "evals" / "regressions.jsonl"),
                                                  check=False, json=False), self.root)

    def test_24_land_with_p2_absent_exits_3_and_writes_nothing(self):
        self.validated()
        digest = kb_testkit.tree_digest(self.root / "KB")
        with mock.patch.object(kbc, "KBW", self.tmp / "absent" / "kb-write.py"):
            rc, out = self.cli("land", "C-0001")
        self.assertEqual(rc, 3, out)
        self.assertEqual(kb_testkit.tree_digest(self.root / "KB"), digest)
        self.assertEqual(self.rec()["stage"], "validated")

    def test_25_land_files_one_supersede_proposal_and_stops_for_the_owner(self):
        pid = self.proposed()
        r = self.rec()
        self.assertEqual((r["stage"], r["land"]["proposal"]), ("proposed", pid))
        text = (self.root / "KB" / "inbox" / (pid + ".md")).read_text(encoding="utf-8")
        for want in ("origin: correction:C-0001", "supersedes: wiki:first", "base_hash: " + r["compile"]["before_sha256"]):
            self.assertIn(want, text)
        self.assertEqual(self.cli("land", "C-0001")[0], 2)  # already proposed
        self.assertEqual(len(self.cases()), self.seeded)  # nothing appended before the owner lands it

    def test_26_land_after_the_page_drifted_exits_2(self):
        self.validated()
        page = self.root / "KB/wiki/alpha/first.md"
        page.write_text(page.read_text(encoding="utf-8") + "\nHand edit.\n", encoding="utf-8")
        rc, out = self.cli("land", "C-0001")
        self.assertEqual(rc, 2, out)
        self.assertIn("drift", out["error"])

    def test_27_hook_appends_exactly_one_case_and_unland_breaks_it(self):
        pid = self.proposed()
        before = self.cases()
        rc, res = self.kbw_cli("land", pid, "--endorsed-by", "owner")
        self.assertEqual((rc, res.get("hook")), (0, "ok"), res)
        rows = self.cases()
        self.assertEqual(len(rows), len(before) + 1)
        case = rows[-1]
        self.assertEqual((case["origin"], case["ledger_seq"], case["status"]), ("correction:C-0001", res["ledger_seq"], "active"))
        self.assertEqual(case["landed_version"], kbc.sha256((self.root / "KB/wiki/alpha/first.md").read_bytes()))
        self.assertNotEqual(case["landed_version"], case["failing_version"])
        self.assertEqual(self.rec()["stage"], "landed")
        self.assertEqual(self.regressions_rc(), 0)
        rc, out = self.kbw_cli("unland", pid, "--endorsed-by", "owner", "--reason", "discrimination proof")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.regressions_rc(), 1)  # the case now fails: it discriminates

    def test_28_landed_with_a_ledger_hash_mismatch_exits_2_and_appends_nothing(self):
        pid = self.proposed()
        with mock.patch.object(self.kbw, "HOOK", self.tmp / "absent" / "kb-correct.py"):
            rc, res = self.kbw_cli("land", pid, "--endorsed-by", "owner")
        self.assertEqual(rc, 0, res)
        page = self.root / "KB/wiki/alpha/first.md"
        page.write_text(page.read_text(encoding="utf-8") + "\nHand edit after land.\n", encoding="utf-8")
        before = self.cases()
        rc, out = self.cli("landed", "C-0001", "--ledger-seq", str(res["ledger_seq"]))
        self.assertEqual(rc, 2, out)
        self.assertIn("ledger hash mismatch", out["error"])
        self.assertEqual(self.cases(), before)
        self.assertEqual(self.rec()["stage"], "proposed")

    def test_29_landed_rejects_a_row_that_is_not_this_land(self):
        self.proposed()
        rc, out = self.cli("landed", "C-0001", "--ledger-seq", "1")  # row 1 is the put
        self.assertEqual(rc, 2, out)
        self.assertEqual(self.cli("landed", "C-0001", "--ledger-seq", "99")[0], 2)

    def test_30_landed_is_idempotent(self):
        pid = self.proposed()
        rc, res = self.kbw_cli("land", pid, "--endorsed-by", "owner")
        n = len(self.cases())
        rc, out = self.cli("landed", "C-0001", "--ledger-seq", str(res["ledger_seq"]))
        self.assertEqual((rc, out["appended"]), (0, False), out)
        self.assertEqual(len(self.cases()), n)

    def test_27b_failing_hook_rolls_the_whole_land_back(self):
        pid = self.proposed()
        state, cases, rec = kb_testkit.state_digest(self.root), self.cases(), self.rec()
        hook = self.tmp / "hook.py"
        hook.write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
        with mock.patch.object(self.kbw, "HOOK", hook):
            rc, res = self.kbw_cli("land", pid, "--endorsed-by", "owner")
        self.assertEqual(rc, 3, res)
        self.assertEqual((kb_testkit.state_digest(self.root), self.cases(), self.rec()), (state, cases, rec))
        self.assertEqual(self.kbw_cli("land", pid, "--endorsed-by", "owner")[0], 0)  # rerun converges
        self.assertEqual(len(self.cases()), len(cases) + 1)

    def test_27c_correction_land_fault_at_every_point_recovers_without_duplicate_cases(self):
        import os
        for point in self.kbw.FAULT_POINTS:
            with self.subTest(point=point):
                self.tearDown()
                self.setUp()
                pid = self.proposed()
                state, n = kb_testkit.state_digest(self.root), len(self.cases())
                os.environ[self.kbw.FAULT_ENV] = point
                try:
                    rc, out = self.kbw_cli("land", pid, "--endorsed-by", "owner")
                finally:
                    os.environ.pop(self.kbw.FAULT_ENV, None)
                self.assertEqual(rc, 9, out)
                self.assertEqual(self.cli("status")[0], 0)  # a kb-correct invocation recovers too
                self.assertEqual(list((self.root / "KB/inbox/_ops").iterdir()), [])
                rows = [json.loads(x) for x in (self.root / "KB/inbox/_ledger.jsonl").read_text().splitlines()]
                self.assertEqual(rows[-1]["event"], "recover")
                if point == "after-case":
                    self.assertIn("completed", rows[-1]["reason"])
                else:
                    self.assertIn("rolled back", rows[-1]["reason"])
                    self.assertEqual((kb_testkit.state_digest(self.root), len(self.cases())), (state, n))
                    self.assertEqual(self.rec()["stage"], "proposed")
                    rc, res = self.kbw_cli("land", pid, "--endorsed-by", "owner")
                    self.assertEqual((rc, res.get("hook")), (0, "ok"), res)
                self.assertEqual(self.rec()["stage"], "landed")
                self.assertEqual(len(self.cases()), n + 1)
                self.assertEqual(len([c for c in self.cases() if c["origin"] == "correction:C-0001"
                                      and c["failing_version"] == self.rec()["compile"]["before_sha256"]]), 1)
                self.assertEqual(self.regressions_rc(), 0)

    def test_31_replay_all_waits_then_judges_answer_cases(self):
        rc, out = self.cli("replay-all")
        self.assertEqual(rc, 2, out)  # packets written, no results yet
        d = self.root / kbc.CORR / "_replay-all"
        pk = json.loads((d / "packets" / "replay-r-0004.json").read_text(encoding="utf-8"))
        self.assertEqual(set(pk), kbc.PACKETS["replay"])
        (d / "results").mkdir()
        (d / "results" / "replay-r-0004.md").write_text("An answer.\n", encoding="utf-8")
        self.assertEqual(self.cli("replay-all")[0], 2)  # now waits on the judge
        self.assertEqual(set(json.loads((d / "packets" / "judge-r-0004.json").read_text(encoding="utf-8"))),
                         kbc.PACKETS["judge"])
        (d / "results" / "judge-r-0004.json").write_text(json.dumps({"points": [], "verdict": "fail", "evidence": "An answer."}), encoding="utf-8")
        rc, out = self.cli("replay-all")
        self.assertEqual(rc, 1, out)
        self.assertIn("r-0004", out["error"])
        self.assertEqual(self.cli("replay-all", "--fresh")[0], 2)  # --fresh starts over


    def test_32_land_refuses_a_stale_validation_then_revalidate_lands(self):
        self.validated()
        third = self.root / "KB/wiki/beta/third.md"
        third.write_text(third.read_text(encoding="utf-8") + "\nAnother page moved.\n", encoding="utf-8")
        rc, out = self.cli("land", "C-0001")
        self.assertEqual(rc, 1, out)
        self.assertIn("stale validation: corpus", out["error"])
        self.assertEqual(self.rec()["stage"], "validated")
        rc, out = self.cli("validate", "C-0001")  # stale -> redone on the current corpus
        self.assertEqual((rc, out.get("stage")), (0, "validated"), out)
        self.assertEqual(self.cli("validate", "C-0001")[0], 2)  # fresh: nothing to redo
        with mock.patch.object(kbc.kbe, "tools_hash", lambda root: "changed tool source"):
            rc, out = self.cli("land", "C-0001")
        self.assertEqual(rc, 1, out)
        self.assertIn("tools", out["error"])
        self.assertEqual(self.cli("land", "C-0001")[0], 0)

    def test_33_landed_hook_rejects_a_stale_validation(self):
        pid = self.proposed()
        with mock.patch.object(self.kbw, "HOOK", self.tmp / "absent" / "kb-correct.py"):
            rc, res = self.kbw_cli("land", pid, "--endorsed-by", "owner")
        self.assertEqual(rc, 0, res)
        n = len(self.cases())
        with mock.patch.object(kbc.kbe, "tools_hash", lambda root: "changed tool source"):
            rc, out = self.cli("landed", "C-0001", "--ledger-seq", str(res["ledger_seq"]))
        self.assertEqual(rc, 1, out)
        self.assertIn("stale validation", out["error"])
        self.assertEqual((len(self.cases()), self.rec()["stage"]), (n, "proposed"))

    def test_34_two_corrections_open_and_land_on_the_same_day(self):
        today = kbc.date.today().isoformat()
        first = FIRST_LONG.replace("**Updated:** 2026-01-05", "**Updated:** " + today)
        self.to_reviewed(self.open_retrieval, "KB/wiki/alpha/first.md", first)
        self.assertEqual(self.cli("validate", "C-0001")[0], 0)
        pid1 = self.cli("land", "C-0001")[1]["proposal"]
        rc, res1 = self.kbw_cli("land", pid1, "--endorsed-by", "owner")
        self.assertEqual((rc, res1.get("hook")), (0, "ok"), res1)
        page = self.root / "KB/wiki/alpha/first.md"
        split = {"points": ["plain prose sentence lives in first"], "terms": ["plain", "prose", "sentence"]}
        rc, out = self.cli("open", "--ranker", "kb-query", "--q", "plain prose sentence", "--owner-says", "Also in the first page.",
                           "--points-file", self.fx(split))
        self.assertEqual((rc, out.get("cid")), (0, "C-0002"), out)
        rc, out = self.cli("diagnose", "C-0002")
        self.assertEqual((rc, out.get("label")), (0, "reachable-unretrieved"), out)
        if self.rec("C-0002")["await"] == "conflict":
            self.cli("record", "C-0002", "conflict", "--result", self.fx({"conflict": False, "primary": [], "reason": ""}))
        second = page.read_text(encoding="utf-8").replace("zebrafish carry it.", "zebrafish carry it; plain prose sentence.")
        self.assertIn("**Updated:** " + today, second)  # same day: Updated cannot move forward
        rc, out = self.cli("record", "C-0002", "compile", "--result", self.fx({"files": {"KB/wiki/alpha/first.md": second}}))
        self.assertEqual(rc, 0, out)
        self.cli("record", "C-0002", "review", "--result", self.fx({"verdict": "APPROVE", "findings": []}))
        rc, out = self.cli("validate", "C-0002")
        self.assertEqual((rc, out.get("stage")), (0, "validated"), out)
        rc, out = self.cli("land", "C-0002")
        self.assertEqual(rc, 0, out)
        self.assertNotEqual(out["proposal"], pid1)
        rc, res2 = self.kbw_cli("land", out["proposal"], "--endorsed-by", "owner")
        self.assertEqual((rc, res2.get("hook")), (0, "ok"), res2)
        mine = [c for c in self.cases() if c["origin"] in ("correction:C-0001", "correction:C-0002")
                and c["landed"] == today]
        self.assertEqual([c["origin"] for c in mine], ["correction:C-0001", "correction:C-0002"])
        self.assertEqual(len({c["id"] for c in self.cases()}), len(self.cases()))
        self.assertEqual([self.rec(c)["stage"] for c in ("C-0001", "C-0002")], ["landed", "landed"])
        self.assertEqual(self.regressions_rc(), 0)


class TestCorrect(Base):
    def test_01_gold_locked_before_retrieval(self):
        rc, out = self.open_raw()
        self.assertEqual(rc, 0, out)
        opened = self.rec()["gold_sha256"]
        self.assertEqual(self.cli("diagnose", "C-0001")[0], 0)
        r = self.rec()
        self.assertTrue(r["gold_locked"] < r["retrieval_at"], (r["gold_locked"], r["retrieval_at"]))
        self.assertNotEqual(r["gold_sha256"], opened)
        self.assertEqual(r["diagnosis"]["label"], "raw-only")
        self.assertEqual(r["diagnosis"]["evidence"]["gold"], ["second"])

    def test_02_diagnose_before_open_exits_2(self):
        rc, out = self.cli("diagnose", "C-0001")
        self.assertEqual(rc, 2, out)
        self.open_raw()
        self.assertEqual(self.cli("validate", "C-0001")[0], 2)  # stage error: open is not reviewed

    def test_03_zero_evidence_is_unreachable_with_no_llm_packet(self):
        split = {"points": ["volcanic glass obsidian"], "named_stems": ["third"]}
        self.cli("open", "--q", "obsidian", "--owner-says", "Wrong.", "--points-file", self.fx(split))
        rc, out = self.cli("diagnose", "C-0001")
        self.assertEqual(rc, 0, out)
        self.assertEqual(out["label"], "unreachable")
        packets = sorted(p.name for p in (self.root / kbc.CORR / "C-0001" / "packets").iterdir())
        self.assertEqual(packets, ["compile.json"])  # no conflict check: nothing to conflict with
        self.assertEqual(self.packet("compile")["target"], "KB/wiki/beta/third.md")

    def test_04_gold_taken_from_the_ranker_is_I3_invalid(self):
        self.to_reviewed(self.open_retrieval, "KB/wiki/alpha/first.md", FIRST_PATCHED)
        r = self.rec()
        r["evidence_stems"], r["named_stems"] = [], []
        r["diagnosis"]["evidence"]["gold"] = r["topk"] or ["second"]
        (self.root / kbc.CORR / "C-0001" / "record.json").write_text(json.dumps(r), encoding="utf-8")
        bad = kbe.validate_cases([kbc.draft_case(self.root, r)])
        self.assertTrue(any("I-3" in b for b in bad), bad)
        rc, out = self.cli("validate", "C-0001")
        self.assertEqual(rc, 2, out)
        self.assertIn("I-3", out["error"])

    def test_05_two_file_or_oversize_diff_exits_1(self):
        self.open_raw()
        self.cli("diagnose", "C-0001")
        self.cli("record", "C-0001", "conflict", "--result", self.fx({"conflict": False, "primary": [], "reason": ""}))
        two = {"KB/wiki/alpha/second.md": SECOND_PATCHED, "KB/wiki/alpha/first.md": FIRST_PATCHED}
        rc, out = self.cli("record", "C-0001", "compile", "--result", self.fx({"files": two}))
        self.assertEqual(rc, 1, out)
        self.assertEqual((self.rec()["stage"], self.rec()["compile"]["attempt"]), ("diagnosed", 1))
        self.assertEqual(self.packet("compile")["tier"], "high")
        big = SECOND_PATCHED + "".join("Line %d of padding prose.\n" % i for i in range(45))
        rc, out = self.cli("record", "C-0001", "compile", "--result", self.fx({"files": {"KB/wiki/alpha/second.md": big}}))
        self.assertEqual(rc, 1, out)
        self.assertEqual(self.rec()["stage"], "killed")  # max 2 attempts, then kill
        self.assertIn("KILL", self.rec()["terminal_row"])

    def test_06_review_packet_contains_the_diff_only(self):
        self.to_reviewed(self.open_raw, "KB/wiki/alpha/second.md", SECOND_PATCHED)
        pk = self.packet("review")
        self.assertEqual(set(pk), {"step", "cid", "target", "diff"})
        text = json.dumps(pk)
        self.assertNotIn(OWNER_SAYS, text)
        self.assertNotIn("tide pools shelter kelp\"", text)  # the points are not handed over
        self.assertTrue(pk["diff"].startswith("--- a/KB/wiki/alpha/second.md"))

    def test_07_replay_overlay_is_blind(self):
        self.to_reviewed(self.open_raw, "KB/wiki/alpha/second.md", SECOND_PATCHED)
        (self.root / "KB" / "inbox").mkdir(exist_ok=True)
        rc, out = self.cli("validate", "C-0001")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(out["packets"]), 4)  # base x1, patched x3, no affected answer case
        for run in ("base", "patched-1", "patched-2", "patched-3"):
            pk = self.packet("replay-" + run)
            self.assertEqual(set(pk), kbc.PACKETS["replay"])
            ov = Path(pk["overlay"])
            self.assertFalse((ov / "KB" / "inbox").exists())
            self.assertTrue((ov / "KB" / "RAW").is_symlink())
            for p in ov.rglob("*"):
                if p.is_file() and not p.is_symlink() and "RAW" not in p.parts and p.suffix in (".md", ".json"):
                    self.assertNotIn(OWNER_SAYS, p.read_text(encoding="utf-8", errors="replace"), p)
        base = Path(self.packet("replay-base")["overlay"])
        self.assertNotIn("Tide pools", (base / "KB/wiki/alpha/second.md").read_text(encoding="utf-8"))
        patched = Path(self.packet("replay-patched-1")["overlay"])
        self.assertIn("Tide pools", (patched / "KB/wiki/alpha/second.md").read_text(encoding="utf-8"))

    def test_08_case_that_already_passes_on_base_is_rejected(self):
        self.to_reviewed(self.open_raw, "KB/wiki/alpha/second.md", SECOND_PATCHED)
        self.cli("validate", "C-0001")
        self.replay_and_judge(base_verdict="PASS")
        rc, out = self.cli("validate", "C-0001")
        self.assertEqual(rc, 1, out)
        r = self.rec()
        self.assertEqual(r["stage"], "failed")
        self.assertFalse(r["validate"]["checks"]["base FAIL"])
        self.assertIn("| FAIL |", r["terminal_row"])

    def test_09_forbidden_literal_fails_a_judged_pass(self):
        self.to_reviewed(self.open_raw, "KB/wiki/alpha/second.md", SECOND_PATCHED)
        self.cli("validate", "C-0001")
        self.replay_and_judge()
        for run in ("patched-1", "patched-2"):
            (self.root / kbc.CORR / "C-0001" / "results" / ("replay-%s.md" % run)).write_text(
                "It sits in a Deep Trench.\n", encoding="utf-8")
        rc, out = self.cli("validate", "C-0001")
        self.assertEqual(rc, 1, out)
        self.assertFalse(self.rec()["validate"]["checks"]["patched >=2/3"])

    def test_13_full_answer_flow_validates_and_leaves_wiki_and_raw_unmutated(self):
        wiki, raw = kb_testkit.tree_digest(self.root / "KB/wiki"), kb_testkit.tree_digest(self.root / "KB/RAW")
        self.to_reviewed(self.open_raw, "KB/wiki/alpha/second.md", SECOND_PATCHED)
        rc, out = self.cli("validate", "C-0001")
        self.assertEqual((rc, out["det_rc"]), (0, 0), out)
        overlays = Path(self.rec()["validate"]["base_overlay"]).parent
        self.replay_and_judge(patched=("PASS", "FAIL", "PASS"))
        rc, out = self.cli("validate", "C-0001")
        self.assertEqual((rc, out["stage"]), (0, "validated"), out)
        r = self.rec()
        self.assertIn("| KEEP |", r["terminal_row"])
        self.assertIn("base FAIL->patched 2/3", r["terminal_row"])
        self.assertEqual(r["validate"]["case"]["kind"], "answer")
        self.assertFalse(overlays.exists())  # terminal transitions remove the overlays
        self.assertEqual(kb_testkit.tree_digest(self.root / "KB/wiki"), wiki)
        self.assertEqual(kb_testkit.tree_digest(self.root / "KB/RAW"), raw)

    def test_40_replay_packets_are_blind_bytes(self):
        self.to_reviewed(self.open_raw, "KB/wiki/alpha/second.md", SECOND_PATCHED)
        rows = [json.loads(x) for x in (self.root / "evals/regressions.jsonl").read_text().splitlines()]
        rows[3]["status"] = "active"  # an answer case whose gold must stay out of the overlay
        (self.root / "evals/regressions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        self.assertEqual(self.cli("validate", "C-0001")[0], 0)
        pdir = self.root / kbc.CORR / "C-0001" / "packets"
        replays = sorted(pdir.glob("replay-*.json"))
        self.assertEqual(len(replays), 4)
        for p in replays:
            raw = p.read_bytes().decode("utf-8").lower()
            for secret in (OWNER_SAYS.lower(), "tide pools shelter kelp", "deep trench", "verdict", "approve",
                           "literal and direct"):
                self.assertNotIn(secret, raw, (p.name, secret))
        ov = Path(json.loads(replays[0].read_text())["overlay"])
        self.assertNotIn("literal and direct", (ov / "evals/regressions.jsonl").read_text(encoding="utf-8"))
        self.cli("record", "C-0001", "replay", "--run", "base", "--result", self.fx("Some answer.\n", "md"))
        judge = (pdir / "judge-base.json").read_bytes().decode("utf-8")
        self.assertNotIn(OWNER_SAYS, judge)  # the judge packet is separate: points and answer only
        self.assertNotIn("diff", json.loads(judge))

    def test_41_malformed_unclear_or_uncited_judging_counts_as_fail(self):
        self.to_reviewed(self.open_raw, "KB/wiki/alpha/second.md", SECOND_PATCHED)
        self.cli("validate", "C-0001")
        results = {"base": {"verdict": "fail", "evidence": "Answer for base."},
                   "patched-1": {"verdict": "unclear", "evidence": "Answer for patched-1."},
                   "patched-2": {"verdict": "PASS", "evidence": "Answer for patched-2."},
                   "patched-3": {"verdict": "pass", "evidence": "a span the answer never says"}}
        for run, res in results.items():
            self.cli("record", "C-0001", "replay", "--run", run, "--result", self.fx("Answer for %s.\n" % run, "md"))
            rc, out = self.cli("record", "C-0001", "judge", "--run", run, "--result", self.fx(res))
            self.assertEqual((rc, out["counts_as"]), (0, "FAIL"), out)
        rc, out = self.cli("record", "C-0001", "judge", "--run", "patched-1", "--result", self.fx("not json at all", "md"))
        self.assertEqual((rc, out["counts_as"]), (0, "FAIL"), out)
        rc, out = self.cli("validate", "C-0001")
        self.assertEqual(rc, 1, out)
        r = self.rec()
        self.assertEqual(r["stage"], "failed")
        self.assertFalse(any(r["validate"]["passed"].values()))
        self.assertIn("malformed", r["validate"]["judged"]["patched-1"])

    def test_42_judging_after_the_corpus_moved_is_stale_and_restarts(self):
        self.to_reviewed(self.open_raw, "KB/wiki/alpha/second.md", SECOND_PATCHED)
        self.cli("validate", "C-0001")
        self.replay_and_judge()
        third = self.root / "KB/wiki/beta/third.md"
        third.write_text(third.read_text(encoding="utf-8") + "\nMoved mid-validation.\n", encoding="utf-8")
        rc, out = self.cli("validate", "C-0001")
        self.assertEqual(rc, 1, out)
        self.assertIn("stale", out["error"])
        r = self.rec()
        self.assertEqual((r["stage"], r["await"], r["validate"]), ("reviewed", "validate", {}))
        rc, out = self.cli("validate", "C-0001")
        self.assertEqual((rc, len(out["packets"])), (0, 4), out)
        self.assertEqual(sorted(p.name for p in (self.root / "KB" / "inbox").iterdir()), ["_corrections"])

    def test_13b_retrieval_flow_flips_via_rank_without_replay(self):
        self.to_reviewed(self.open_retrieval, "KB/wiki/alpha/first.md", FIRST_PATCHED)
        self.assertEqual(self.rec()["diagnosis"]["label"], "reachable-unretrieved")
        rc, out = self.cli("validate", "C-0001")
        self.assertEqual((rc, out["stage"]), (0, "validated"), out)
        r = self.rec()
        self.assertNotIn("first", r["validate"]["base"])
        self.assertIn("first", r["validate"]["patched"])
        self.assertEqual(kbe.validate_cases([r["validate"]["case"]]), [])
        self.assertFalse((self.root / kbc.CORR / "C-0001" / "packets" / "replay-base.json").exists())

    def test_14_step11_command_on_a_fixture_overlay_exits_0(self):
        ov = kbc.overlay(self.root, self.tmp / "ov")
        self.assertEqual(kbc.det_check(self.root, ov), 0)

    def test_15_every_retrieval_step_file_is_in_the_overlay(self):
        (self.root / "KB" / "kb.json").write_text('{"owner": "owner"}\n', encoding="utf-8")
        for name in ("kb-edge-types.json", "kb-gazetteer.json"):
            (self.root / "KB" / "output" / name).write_text("{}\n", encoding="utf-8")
        ov = kbc.overlay(self.root, self.tmp / "ov")
        for rel in kbc.RETRIEVAL_FILES:
            if (self.root / rel).is_file():
                self.assertTrue((ov / rel).is_file(), rel)
        for rel in ("KB/CATALOG.md", "skills/REGISTRY.md", "tools/kb-query.py", "KB/output/kb-index.json",
                    "KB/output/kb-graph.json"):
            self.assertTrue((ov / rel).is_file(), rel)

    def test_16_all_active_origins_are_redacted(self):
        ov = kbc.overlay(self.root, self.tmp / "ov")
        rows = [json.loads(x) for x in (ov / "evals/regressions.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual({r["origin"] for r in rows if r["status"] == "active"}, {"redacted"})
        self.assertNotIn("correction:C-0001", (ov / "evals/regressions.jsonl").read_text(encoding="utf-8"))

    def test_17_terminal_rows_and_open_refusal(self):
        self.open_raw()
        rc, out = self.open_raw()
        self.assertEqual(rc, 2, out)  # C-0001 has no terminal row yet
        self.assertEqual(self.cli("kill", "C-0001", "--reason", "owner withdrew")[0], 0)
        self.assertIn("| KILL | owner withdrew", self.rec()["terminal_row"])
        self.assertEqual(self.open_raw()[0], 0)  # C-0002
        self.cli("diagnose", "C-0002")
        rc, out = self.cli("record", "C-0002", "conflict", "--result", self.fx(
            {"conflict": True, "primary": [{"path": "KB/RAW/tides.md", "line": 1}], "reason": "raw disagrees"}))
        self.assertEqual((rc, out["stage"]), (0, "flagged"), out)
        r = self.rec("C-0002")
        self.assertIn("| FLAG |", r["terminal_row"])
        gap = self.root / "KB" / "inbox" / (r["diagnosis"]["gap"] + ".md")
        self.assertIn("gap_kind: contradictory", gap.read_text(encoding="utf-8"))
        self.assertIn("origin: correction:C-0002", gap.read_text(encoding="utf-8"))
        self.assertEqual(self.cli("kill", "C-0002", "--reason", "again")[0], 2)  # terminal stays terminal

    def test_17b_reachable_retrieved_flags_a_skill_gap(self):
        split = {"points": ["first claim here"], "terms": ["first", "claim"]}
        self.cli("open", "--q", "first claim", "--owner-says", "Wrong anyway.", "--points-file", self.fx(split))
        rc, out = self.cli("diagnose", "C-0001")
        self.assertEqual((rc, out["label"], out["stage"]), (0, "reachable-retrieved", "flagged"), out)
        gap = self.root / "KB" / "inbox" / (out["gap"] + ".md")
        self.assertIn("gap_kind: skill", gap.read_text(encoding="utf-8"))

    def test_18_works_when_inbox_is_absent(self):
        self.assertFalse((self.root / "KB" / "inbox").exists())
        rc, out = self.open_raw()
        self.assertEqual((rc, out["cid"]), (0, "C-0001"), out)
        self.assertTrue((self.root / kbc.CORR / "C-0001" / "record.json").is_file())

    def test_19_diagnose_packet_contains_no_topk_stems(self):
        self.open_raw()
        self.cli("diagnose", "C-0001")
        r, pk = self.rec(), self.packet("conflict")
        self.assertTrue(r["topk"])
        self.assertEqual(set(pk), kbc.PACKETS["conflict"])
        text = json.dumps(pk).lower()
        for stem in r["topk"]:
            self.assertNotIn(stem.lower(), text)

    def test_20_review_reject_retries_on_high_tier_then_kills(self):
        self.open_raw()
        self.cli("diagnose", "C-0001")
        self.cli("record", "C-0001", "conflict", "--result", self.fx({"conflict": False, "primary": [], "reason": ""}))
        reject = {"verdict": "REJECT", "findings": [{"severity": "high", "line": 12, "claim": "unsupported"}]}
        for attempt in (1, 2):
            self.assertEqual(self.cli("record", "C-0001", "compile", "--result",
                                      self.fx({"files": {"KB/wiki/alpha/second.md": SECOND_PATCHED}}))[0], 0)
            rc, out = self.cli("record", "C-0001", "review", "--result", self.fx(reject))
            self.assertEqual(rc, 0, out)
            if attempt == 1:
                self.assertEqual(self.packet("compile")["tier"], "high")
                self.assertEqual(self.packet("compile")["findings"], reject["findings"])
        self.assertEqual(self.rec()["stage"], "killed")

    def test_21_drift_after_compile_exits_2(self):
        self.to_reviewed(self.open_raw, "KB/wiki/alpha/second.md", SECOND_PATCHED)
        page = self.root / "KB/wiki/alpha/second.md"
        page.write_text(page.read_text(encoding="utf-8") + "\nHand edit.\n", encoding="utf-8")
        rc, out = self.cli("validate", "C-0001")
        self.assertEqual(rc, 2, out)
        self.assertIn("drift", out["error"])

    def test_22_land_needs_a_validated_correction(self):
        self.open_raw()
        self.assertEqual(self.cli("land", "C-0001")[0], 2)  # stage open
        self.assertEqual(self.cli("landed", "C-0001", "--ledger-seq", "1")[0], 2)
        self.assertEqual(self.cli("landed", "C-0001")[0], 2)  # --ledger-seq is required

    def test_23_no_network_or_model_calls(self):
        src = (TOOLS / "kb-correct.py").read_text(encoding="utf-8")
        self.assertEqual([l for l in src.splitlines() if NO_NETWORK_RE.search(l)], [])


if __name__ == "__main__":
    unittest.main()
