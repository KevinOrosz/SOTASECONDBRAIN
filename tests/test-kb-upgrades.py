#!/usr/bin/env python3
"""Correction-first integration tests, all on disposable instances."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import kb_testkit

writer = kb_testkit.load("kb-write.py")
evalmod = kb_testkit.load("kb-eval.py")
correct = kb_testkit.load("kb-correct.py")
mcp = kb_testkit.load("kb-mcp.py")
bench = kb_testkit.load("kb-benchmark.py")


class Upgrades(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = kb_testkit.fixture(self.tmp, regressions=True)
        self.reg = self.root / "evals/regressions.jsonl"
        self.assertEqual(self.cli(writer, ["seal"])[0], 0)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def cli(self, mod, args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = mod.main(args + ["--root", str(self.root), "--json"])
        return rc, out.getvalue()

    def proposal(self, **extra):
        return mcp.call(self.root, "kb_propose", dict(agent="RESEARCHER", slug="short-fact", category="alpha",
            body="# Short fact\n\n## Core Claim\nThe preferred meeting day is Tuesday.\n", source_ref="owner:2026-01-01",
            confidence="high", type="fact", **extra))["id"]

    def strict(self):
        p = self.root / "KB/kb.json"
        cfg = json.loads(p.read_text()) if p.exists() else {}
        cfg["answer_policy"] = "require-fresh"
        p.write_text(json.dumps(cfg))
        rows = [json.loads(x) for x in self.reg.read_text().splitlines()]
        case = next(c for c in rows if c["kind"] == "answer")
        case["status"] = "active"
        self.reg.write_text("".join(json.dumps(c)+"\n" for c in rows))
        return case

    def test_strict_gate_rolls_back_then_accepts_exact_proposal_replay(self):
        case = self.strict()
        pid = self.proposal()
        before = kb_testkit.tree_digest(self.root / "KB/wiki")
        rc, text = self.cli(writer, ["land", pid, "--endorsed-by", "owner"])
        self.assertEqual(rc, 3, text)
        self.assertEqual(before, kb_testkit.tree_digest(self.root / "KB/wiki"))
        rc, text = self.cli(correct, ["replay-all", "--proposal", pid, "--fresh"])
        self.assertEqual(rc, 2, text)
        d = self.root / evalmod.REPLAY_ALL / "results"
        d.mkdir()
        (d / ("replay-%s.md" % case["id"])).write_text("Verified answer.")
        (d / ("judge-%s.json" % case["id"])).write_text(json.dumps({"verdict": "pass", "evidence": "Verified answer."}))
        self.assertEqual(self.cli(correct, ["replay-all", "--proposal", pid])[0], 0)
        rc, text = self.cli(writer, ["land", pid, "--endorsed-by", "owner"])
        self.assertEqual(rc, 0, text)
        self.assertEqual(evalmod.regressions(self.root, self.reg)["answer_passed"], 1)
        path = self.root / "KB/wiki/alpha/short-fact.md"
        self.assertTrue(path.is_file())
        self.assertEqual(self.cli(writer, ["unland", pid, "--endorsed-by", "owner", "--reason", "test"])[0], 0)
        self.assertFalse(path.exists())

    def test_new_corrections_use_hybrid_and_legacy_cases_still_use_keyword(self):
        points = self.tmp / "points.json"
        points.write_text(json.dumps({"points": ["zebrafish lives in first"], "terms": ["zebrafish"]}))
        rc, text = self.cli(correct, ["open", "--q", "zebrafish", "--owner-says", "Found in body",
                                    "--points-file", str(points)])
        self.assertEqual(rc, 0, text)
        rec = correct.load_record(self.root, "C-0001")
        self.assertEqual(rec["ranker"], "hybrid-graph")
        self.assertTrue(rec["retrieval_version"])
        self.assertIn("first", correct.rank(self.root, "zebrafish", "hybrid-graph"))
        self.assertNotIn("first", correct.rank(self.root, "zebrafish", "kb-query"))
        self.assertEqual(self.cli(correct, ["diagnose", "C-0001"])[0], 0)
        self.assertEqual(correct.load_record(self.root, "C-0001")["diagnosis"]["label"], "reachable-retrieved")

    def test_fact_supersession_keeps_undo_and_rejects_stale_proposals(self):
        pid = self.proposal()
        self.assertEqual(self.cli(writer, ["land", pid, "--endorsed-by", "owner"])[0], 0)
        path = self.root / "KB/wiki/alpha/short-fact.md"
        original = path.read_bytes()
        args = dict(agent="RESEARCHER", slug="updated-fact", category="alpha", supersedes="wiki:short-fact",
                    body="# Short fact\n\n## Core Claim\nThe preferred meeting day is Wednesday.\n",
                    source_ref="owner:2026-01-01", confidence="high", type="fact")
        newer = mcp.call(self.root, "kb_propose", args)["id"]
        args["slug"] = "stale-fact"
        args["body"] = args["body"].replace("Short fact", "Alternative fact").replace("Wednesday", "Thursday")
        stale = mcp.call(self.root, "kb_propose", args)["id"]
        self.assertEqual(self.cli(writer, ["land", newer, "--endorsed-by", "owner"])[0], 0)
        self.assertEqual(self.cli(writer, ["land", stale, "--endorsed-by", "owner"])[0], 4)
        self.assertEqual(self.cli(writer, ["unland", newer, "--endorsed-by", "owner", "--reason", "test"])[0], 0)
        self.assertEqual(path.read_bytes(), original)

    def test_strict_replay_rejects_drift_and_missing_regressions(self):
        self.strict()
        pid = self.proposal()
        self.assertEqual(self.cli(correct, ["replay-all", "--proposal", pid, "--fresh"])[0], 2)
        manifest = json.loads((self.root / evalmod.REPLAY_ALL / "manifest.json").read_text())
        overlay = Path(manifest["overlay"])
        page = overlay / "KB/wiki/alpha/first.md"
        page.write_text(page.read_text()+"\nchanged\n")
        rc, text = self.cli(correct, ["replay-all", "--proposal", pid])
        self.assertEqual(rc, 2, text)
        self.assertIn("overlay changed", text)
        self.reg.unlink()
        rc, text = self.cli(writer, ["land", pid, "--endorsed-by", "owner"])
        self.assertEqual(rc, 3, text)
        self.assertIn("requires the regressions file", text)
        shutil.rmtree(overlay.parent)

    def test_withdraw_reimport_reinstate_and_handoff(self):
        workflow = kb_testkit.load("kb-workflow.py")
        original = self.proposal()
        def land(pid, *flags):
            return self.cli(writer, ["land", pid, "--endorsed-by", "owner", *flags])
        self.assertEqual(land(original)[0], 0)
        body = "# Short fact\n\n## Core Claim\nThe preferred meeting day is %s.\n"
        def replacement(day):
            return mcp.call(self.root, "kb_propose", dict(agent="RESEARCHER", slug="change-day",
                category="alpha", supersedes="wiki:short-fact", type="fact", body=body % day,
                confidence="high", source_ref="raw:source-one.md"))["id"]
        new, pending = replacement("Wednesday"), replacement("Thursday")
        review = json.loads(self.cli(writer, ["list", "--diff"])[1])["fact_reviews"][0]
        self.assertEqual({p["id"] for p in review["pending"]}, {new, pending})
        self.assertTrue(review["pending"][0]["source_excerpts"])
        self.assertEqual(review["last_decision"]["actor"], "owner")
        self.assertEqual(land(new)[0], 0)
        source = self.tmp / "incoming"
        source.mkdir()
        (source / "short-fact.md").write_text(body % "Tuesday")
        rc, text = self.cli(workflow, ["adopt-folder", str(source), "--agent", "RESEARCHER",
                            "--category", "alpha", "--confidence", "high", "--apply"])
        self.assertEqual(rc, 0, text)
        self.assertEqual(json.loads(text)["items"][0]["state"], "withdrawn")
        old = replacement("Tuesday")
        self.assertIn("--reinstate", land(old)[1])
        before = kb_testkit.tree_digest(self.root / "KB")
        rc, text = self.cli(workflow, ["brief", "--since", "0"])
        self.assertEqual(rc, 0, text)
        brief = json.loads(text)
        self.assertIn("Wednesday", brief["current_facts"][0]["claim"])
        self.assertIn("Tuesday", brief["withdrawn"][0]["claim"])
        self.assertIn(old, {p["id"] for p in brief["pending"]})
        self.assertEqual(kb_testkit.tree_digest(self.root / "KB"), before)
        self.assertEqual(land(old, "--reinstate", "New owner decision")[0], 0)
        self.assertEqual(writer.read_ledger(self.root)[-1]["reinstates"]["reason"], "New owner decision")
        self.assertEqual(self.cli(writer, ["unland", old, "--endorsed-by", "owner", "--reason", "rollback"])[0], 0)
        self.assertIn("--reinstate", land(old)[1])
        self.assertEqual(self.cli(workflow, ["brief", "--since", "99999"])[0], 1)

    def test_explicit_withdrawal_leaves_identical_unrelated_fact_eligible(self):
        pid = self.proposal()
        self.assertEqual(self.cli(writer, ["land", pid, "--endorsed-by", "owner"])[0], 0)
        self.assertEqual(self.cli(writer, ["unland", pid, "--withdraw-fact", "--reason", "obsolete",
                                          "--endorsed-by", "owner"])[0], 0)
        self.assertIn("--reinstate", self.cli(writer, ["land", pid, "--endorsed-by", "owner"])[1])
        other = mcp.call(self.root, "kb_propose", dict(agent="RESEARCHER", slug="other-meeting",
            category="alpha", body="# Other\n\n## Core Claim\nThe preferred meeting day is Tuesday.\n",
            type="fact", confidence="high", source_ref="owner:2026-01-01"))["id"]
        self.assertEqual(self.cli(writer, ["land", other, "--endorsed-by", "owner"])[0], 0)

    def test_action_pairs_are_blind_and_bound(self):
        case = self.strict()
        case["expected_action"] = "ask"
        other = dict(case, id="r-9998", origin="rule:clear-question", expected_action="answer", q="When is Project Alpha due?")
        third = dict(case, id="r-9999", origin="rule:missing-evidence", expected_action="abstain", q="What is the unrecorded date?")
        self.reg.write_text("".join(json.dumps(c)+"\n" for c in (case, other, third)))
        rc, _ = self.cli(correct, ["replay-all", "--fresh"])
        self.assertEqual(rc, 2)
        d = self.root / evalmod.REPLAY_ALL
        overlay = Path(json.loads((d / "manifest.json").read_text())["overlay"])
        self.assertNotIn("expected_action", (overlay / "evals/regressions.jsonl").read_text())
        (d / "results").mkdir()
        for c in (case, other, third):
            (d / "results" / ("replay-%s.md" % c["id"])).write_text("Which project?")
            (d / "results" / ("judge-%s.json" % c["id"])).write_text(json.dumps(
                {"verdict": "pass", "observed_action": "ask", "evidence": "Which project?"}))
        report = evalmod.regressions(self.root, self.reg)
        self.assertEqual((report["answer_passed"], report["failed"]), (1, 2), report)
        self.assertNotEqual(evalmod.case_hash(case), evalmod.case_hash(dict(case, expected_action="answer")))
        shutil.rmtree(overlay.parent)

    def test_mcp_scope_validation_and_stdio(self):
        server = mcp.Server(self.root)
        self.assertIn("error", server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}))
        messages = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}},
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                    {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "kb_search", "arguments": {"query": "zebrafish"}}}]
        proc = subprocess.run([sys.executable, str(mcp.TOOLS / "kb-mcp.py"), "--root", str(self.root)],
                              input="\n".join(json.dumps(x) for x in messages)+"\n", text=True, capture_output=True)
        responses = [json.loads(line) for line in proc.stdout.splitlines()]
        self.assertEqual(len(responses), 3, proc.stderr)
        self.assertFalse(responses[-1]["result"]["isError"], responses[-1])
        self.assertNotIn("kb_land", [t["name"] for t in responses[1]["result"]["tools"]])
        for name, args in [("kb_read", {"path": "../../etc/passwd"}), ("kb_search", {"query": "x", "k": True}),
                           ("kb_land", {}), ("kb_status", {"root": "/"})]:
            with self.assertRaises(ValueError):
                mcp.call(self.root, name, args)
        outside = self.tmp / "secret.md"
        outside.write_text("secret")
        (self.root / "KB/wiki/escape.md").symlink_to(outside)
        with self.assertRaises(ValueError):
            mcp.call(self.root, "kb_read", {"path": "KB/wiki/escape.md"})

    def test_benchmark_rejects_mismatched_corpus_and_missing_results(self):
        result = bench.run(self.root, self.root / "KB/output/retrieval-eval.json", "hybrid-graph", 6)
        self.assertEqual(bench.compare(result, result)["left"]["mean_recall"], 1)
        other = dict(result, corpus_hash="0"*64)
        with self.assertRaises(ValueError):
            bench.compare(result, other)
        with self.assertRaises(ValueError):
            bench.metrics(dict(result, results=[]))


if __name__ == "__main__":
    unittest.main()
