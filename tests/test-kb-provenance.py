#!/usr/bin/env python3
"""Tests for hardening PR3: provenance and verification.

Source preservation (raw hashes on land events, FAIL on missing/drifted RAW, WARN on legacy lands), index and
graph inputs_hash (stale = WARN, corrupt = FAIL), cache freshness, and retrieval-method recording in kb-query
and kb-eval. Every case runs on kb_testkit.fixture(git=False) under a temp root.

Run: python3 tests/test-kb-provenance.py
"""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))
import kb_testkit  # noqa: E402

kbw = kb_testkit.load("kb-write.py")
prov = kb_testkit.load("kb-provenance.py")
kbe = kb_testkit.load("kb-eval.py")
kbi = kb_testkit.load("kb-index.py")
LONG = " ".join(["Inbox write-back lands through one gate with a ledger row and a seal."] * 12)


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = kb_testkit.fixture(self.tmp, indexes=True, git=False)
        self.body = self.tmp / "body.md"
        self.body.write_text("# Fourth\n\n**Sources:** [[RAW/source-two.md]]\n\n## Core Claim\n%s\n" % LONG,
                             encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def cli(self, *args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            rc = kbw.main(list(args[:1]) + ["--root", str(self.root), "--json"] + list(args[1:]))
        return rc, json.loads(buf.getvalue())

    def put(self, ref="raw:source-one.md"):
        rc, out = self.cli("put", "--agent", "RESEARCHER", "--kind", "article", "--slug", "fourth", "--category",
                           "beta", "--confidence", "moderate", "--source-ref", ref, "--body-file", str(self.body))
        self.assertEqual(rc, 0, out)
        return out["id"]

    def land(self, pid):
        self.assertEqual(self.cli("seal")[0], 0)
        return self.cli("land", pid, "--endorsed-by", "owner")

    def checks(self):
        res = prov.check(self.root)
        levels = {lvl for lvl, _ in res}
        return (1 if "FAIL" in levels else 2 if "WARN" in levels else 0), res

    def rebuild(self):
        with contextlib.redirect_stdout(io.StringIO()):
            kbi.build(self.root)
        out = self.root / "KB" / "output"
        graph, _ = kb_testkit.load("kb-graph.py").build(self.root, out, quiet=True)
        (out / "kb-graph.json").write_text(json.dumps(graph), encoding="utf-8")


class Sources(Case):
    def test_land_records_raw_hashes_from_page_and_refs(self):
        rc, out = self.land(self.put())
        self.assertEqual(rc, 0, out)
        row = kbw.read_ledger(self.root)[-1]
        want = {n: kbw.sha256((self.root / "KB/RAW" / n).read_bytes()) for n in ("source-one.md", "source-two.md")}
        self.assertEqual((row["event"], row["sources"]), ("land", want))
        self.rebuild()
        self.assertEqual(self.checks()[0], 0, self.checks()[1])

    def test_land_refuses_missing_raw_source(self):
        self.body.write_text(self.body.read_text(encoding="utf-8").replace("source-two", "absent"), encoding="utf-8")
        rc, out = self.land(self.put())
        self.assertEqual(rc, 2, out)
        self.assertIn("absent.md", out["detail"])
        self.assertFalse((self.root / "KB/wiki/beta/fourth.md").exists())

    def test_verify_fails_on_drift_and_missing(self):
        self.assertEqual(self.land(self.put())[0], 0)
        (self.root / "KB/RAW/source-two.md").write_text("tampered\n", encoding="utf-8")
        rc, res = self.checks()
        self.assertEqual(rc, 1)
        self.assertTrue(any(l == "FAIL" and "drifted" in d for l, d in res), res)
        (self.root / "KB/RAW/source-two.md").unlink()
        self.assertTrue(any(l == "FAIL" and "missing" in d for l, d in self.checks()[1]))

    def test_unland_retires_the_source_obligation(self):
        pid = self.put()
        self.assertEqual(self.land(pid)[0], 0)
        self.assertEqual(self.cli("unland", pid, "--endorsed-by", "owner", "--reason", "t")[0], 0)
        (self.root / "KB/RAW/source-two.md").write_text("tampered\n", encoding="utf-8")
        self.assertFalse(any(l == "FAIL" for l, _ in self.checks()[1]))

    def test_legacy_land_without_hashes_warns(self):
        self.assertEqual(self.land(self.put())[0], 0)
        led = self.root / "KB/inbox/_ledger.jsonl"
        rows = [json.loads(l) for l in led.read_text(encoding="utf-8").splitlines()]
        for r in rows:
            r.pop("sources", None)
        led.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        self.rebuild()
        rc, res = self.checks()
        self.assertEqual(rc, 2, res)
        self.assertTrue(any(l == "WARN" and "predate source hashing" in d for l, d in res))


class Index(Case):
    def test_fresh_fixture_passes(self):
        self.assertEqual(self.checks()[0], 0, self.checks()[1])
        idx = json.loads((self.root / "KB/output/kb-index.json").read_text(encoding="utf-8"))
        self.assertEqual(idx["inputs_hash"], prov.inputs_hash(self.root))

    def test_stale_index_warns_with_rebuild_command(self):
        page = self.root / "KB/wiki/alpha/first.md"
        page.write_text(page.read_text(encoding="utf-8") + "\nmore\n", encoding="utf-8")
        rc, res = self.checks()
        self.assertEqual(rc, 2)
        stale = [d for l, d in res if l == "WARN" and "stale" in d]
        self.assertTrue(stale and all("bin/kb index" in d for d in stale), res)
        self.rebuild()
        self.assertEqual(self.checks()[0], 0)

    def test_corrupt_index_and_graph_fail(self):
        (self.root / "KB/output/kb-index.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(self.checks()[0], 1)
        self.rebuild()
        g = self.root / "KB/output/kb-graph.json"
        g.write_text(json.dumps({"inputs_hash": "x"}), encoding="utf-8")
        self.assertTrue(any(l == "FAIL" and "kb-graph.json corrupt" in d for l, d in self.checks()[1]))

    def test_index_count_mismatch_fails(self):
        p = self.root / "KB/output/kb-index.json"
        idx = json.loads(p.read_text(encoding="utf-8"))
        idx["article_count"] += 1
        p.write_text(json.dumps(idx), encoding="utf-8")
        self.assertEqual(self.checks()[0], 1)

    def test_dangling_raw_link_and_stale_seeds_warn(self):
        page = self.root / "KB/wiki/alpha/first.md"
        page.write_text(page.read_text(encoding="utf-8").replace("source-one", "gone"), encoding="utf-8")
        res = self.checks()[1]
        self.assertTrue(any(l == "WARN" and "RAW/gone.md" in d for l, d in res), res)
        self.assertTrue(any(l == "WARN" and d.startswith("content-seeds") for l, d in res), res)


class Retrieval(Case):
    def test_eval_records_method(self):
        res = kbe.run(self.root)
        self.assertEqual(res["retrieval"]["new"]["ranker"], "hybrid-graph")
        self.assertEqual(res["retrieval"]["old"]["k"], kbe.K)
        self.assertRegex(res["retrieval"]["new"]["version"], r"^[0-9a-f]{12}$")

    def test_query_json_records_method(self):
        kbq = kb_testkit.load("kb-query.py")
        kbq.INDEX = self.root / "KB/output/kb-index.json"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(kbq.main(["kb-query.py", "first", "--json", "--k", "3"]), 0)
        m = json.loads(buf.getvalue())["retrieval"]
        self.assertEqual((m["ranker"], m["k"]), ("keyword", 3))
        self.assertEqual(m["index_inputs_hash"], prov.inputs_hash(self.root))

    def test_regressions_report_method(self):
        root = kb_testkit.fixture(self.tmp / "r", indexes=True, git=False, regressions=True)
        reg = kbe.regressions(root, root / "evals/regressions.jsonl")
        self.assertEqual(reg["retrieval_method"]["k"], "per-case")


if __name__ == "__main__":
    unittest.main()
