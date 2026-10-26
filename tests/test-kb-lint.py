#!/usr/bin/env python3
"""Tests for kb-lint.py (header contract v2) and kb-index.py --root.

Cases follow spec P1 §8 (docs/second-brain-loop/SPEC.md), numbered in
test names. Every case runs on kb_testkit.fixture(); the load-bearing guards are that lint never
mutates and that no suite touches the live KB/output/kb-search.html.

Run: python3 tools/test-kb-lint.py
"""
from __future__ import annotations

import contextlib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
ROOT = TOOLS.parent
LIVE_DASH = ROOT / "KB" / "output" / "kb-search.html"
NO_NETWORK_RE = re.compile(r"(import|from) (requests|urllib|http\.client|socket|httpx|aiohttp)\b|subprocess.*(curl|wget|llm)|https?://")

sys.path.insert(0, str(TOOLS))
import kb_testkit  # noqa: E402

kblint = kb_testkit.load("kb-lint.py")


def dash_stamp():
    return LIVE_DASH.stat().st_mtime_ns if LIVE_DASH.exists() else None


LIVE_DASH_BEFORE = dash_stamp()


def tearDownModule():
    assert dash_stamp() == LIVE_DASH_BEFORE, "suite touched the live kb-search.html"


class LintCase(unittest.TestCase):
    indexes = False  # kb-lint reads no index; Fixture16 builds them

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = kb_testkit.fixture(self.tmp, indexes=self.indexes)
        self.wiki = self.root / "KB" / "wiki"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def put(self, rel, text):
        p = self.wiki / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def edit(self, rel, old, new):
        p = self.wiki / rel
        text = p.read_text(encoding="utf-8")
        self.assertEqual(text.count(old), 1, old)
        p.write_text(text.replace(old, new), encoding="utf-8")

    def strip_types(self):
        for p in self.wiki.rglob("*.md"):
            lines = p.read_text(encoding="utf-8").split("\n")
            p.write_text("\n".join(l for l in lines if not l.startswith("**Type:** ")), encoding="utf-8")

    def run_cli(self, *args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = kblint.main(["--root", str(self.root)] + list(args))
        return rc, buf.getvalue()

    def lint(self, **kw):
        return kblint.lint(self.root, **kw)

    def checks(self, rep, check):
        return [f for f in rep["findings"] if f["check"] == check]

    def article(self, rel, words):
        self.put(rel, "# Filler\n\n**Category:** alpha\n**Sources:** [[RAW/source-one.md]]\n"
                      "**Updated:** 2026-01-01\n**Type:** article\n\n## Core Claim\n" + "word " * words + "\n")


class Contract(LintCase):
    def test_01_clean_fixture_passes(self):
        rep = self.lint()
        self.assertEqual(rep["findings"], [])
        self.assertEqual((rep["file_count"], rep["typed_explicit"]), (6, 6))
        self.assertEqual(self.run_cli()[0], 0)

    def test_02_path_defaults(self):
        self.strip_types()
        self.put("clients/testimonials.md", "# Testimonials\n\n**Category:** clients\n**Updated:** 2026-01-01\n")
        rep = self.lint()
        self.assertEqual(rep["by_type"], {"article": 3, "routing": 1, "source": 1, "taxonomy": 2})
        self.assertEqual(rep["typed_explicit"], 0)
        missing = self.checks(rep, "type-missing")
        self.assertEqual(len(missing), 7)
        self.assertEqual({f["severity"] for f in missing}, {"WARN"})  # TYPE_REQUIRED=False until P1-S3

    def test_03_dangling_depends_on_fails(self):
        self.edit("alpha/first.md", "**Depends-On:** second", "**Depends-On:** second, ghost")
        self.edit("alpha/second.md", "**Type:** article", "**Type:** article\n**Depends-On:** second")
        rep = self.lint()
        self.assertEqual([f["detail"].split()[0] for f in self.checks(rep, "dangling-depends-on")], ["ghost"])
        self.assertEqual([f["id"] for f in self.checks(rep, "self-dependency")], ["second"])
        self.assertEqual(kblint.exit_code(rep), 1)

    def test_04_orphan_consumer_fails(self):
        self.edit("alpha/first.md", "**Consumers:** skill:brain-think, agent:RESEARCHER",
                  "**Consumers:** skill:brain-think, agent:RESEARCHER, skill:nope, skill:content-repurpose, agent:REPURPOSER")
        orphans = self.checks(self.lint(), "orphan-consumer")
        details = " | ".join(f["detail"] for f in orphans)
        self.assertEqual(len(orphans), 3)
        self.assertIn("skill:nope is not in", details)
        self.assertIn("skill:content-repurpose is RETIRED", details)
        self.assertIn("agent:REPURPOSER is not a router registered NAME", details)

    def test_05_cycle_reported_once(self):
        self.edit("alpha/second.md", "**Type:** article", "**Type:** article\n**Depends-On:** first")
        self.edit("beta/third.md", "**Type:** article", "**Type:** article\n**Depends-On:** first")
        rep = self.lint()
        self.assertEqual([f["detail"] for f in self.checks(rep, "cycle")], ["first -> second -> first"])
        self.assertEqual(rep["counts"]["cycles"], 1)

    def test_06_duplicate_id_fails_case_insensitive(self):
        self.put("beta/FIRST.md", "# Shout\n\n**Category:** beta\n**Updated:** 2026-01-01\n**Type:** article\n")
        self.put("alpha/beta.md", "# Beta page\n\n**Category:** alpha\n**Updated:** 2026-01-01\n**Type:** article\n")
        dups = self.checks(self.lint(), "duplicate-id")
        self.assertEqual(sorted(f["path"] for f in dups),
                         ["KB/wiki/alpha/beta.md", "KB/wiki/alpha/first.md", "KB/wiki/beta/FIRST.md"])
        self.assertTrue(any("category folder beta" in f["detail"] for f in dups))

    def test_07_hard_budget_fails_soft_budget_ratchets(self):
        self.assertEqual(self.run_cli("--capture-baseline")[0], 0)  # lint.over_soft_budget = 0
        self.article("alpha/medium.md", 400)  # 403 body words: '## Core Claim' counts
        rep = self.lint()
        self.assertEqual(rep["counts"]["over_soft_budget"], 1)
        self.assertEqual(len(self.checks(rep, "budget-soft")), 1)
        self.assertEqual(kblint.exit_code(rep), 2)
        self.run_cli("--capture-baseline")
        self.assertEqual(self.checks(self.lint(), "budget-soft"), [])
        self.article("alpha/long.md", 2000)
        hard = self.checks(self.lint(), "budget-hard")
        self.assertEqual([f["id"] for f in hard], ["long"])
        self.assertEqual(hard[0]["severity"], "FAIL")

    def test_08_bad_enum_bad_date_future_date_fail(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        self.edit("beta/third.md", "**Confidence:** moderate", "**Confidence:** certain")
        self.edit("alpha/first.md", "**Last-Verified:** 2026-01-02", "**Last-Verified:** 2026-13-01")
        self.edit("alpha/second.md", "**Type:** article", "**Type:** routing\n**Last-Verified:** " + tomorrow)
        self.edit("alpha/_index.md", "**Type:** taxonomy", "**Type:** essay")
        rep = self.lint()
        got = {(f["id"], f["check"]) for f in rep["findings"]}
        self.assertTrue({("third", "confidence-invalid"), ("first", "date-invalid"), ("second", "date-invalid"),
                         ("second", "type-path-conflict"), ("alpha/_index", "type-invalid")} <= got, got)
        self.assertIn("after today", [f for f in rep["findings"] if f["id"] == "second"
                                      and f["check"] == "date-invalid"][0]["detail"])
        self.assertEqual(kblint.exit_code(rep), 1)

    def test_12_both_leading_blank_line_shapes(self):
        body = "**Category:** alpha\n**Updated:** 2026-01-01\n**Type:** article\n\n## Core Claim\nX.\n"
        self.put("alpha/blank-one.md", "\n# Blank One\n\n" + body)
        self.put("alpha/blank-two.md", " \n\t\n# Blank Two\n\n" + body)
        self.put("alpha/no-h1.md", "Loose text first.\n\n# Late Title\n")
        rep = self.lint()
        self.assertEqual([f["id"] for f in self.checks(rep, "header-missing-h1")], ["no-h1"])
        meta = kblint.read_meta(self.wiki / "alpha" / "blank-two.md")
        self.assertEqual((meta["type"], meta["updated"], meta["header_end"]), ("article", "2026-01-01", 8))
        self.assertIsNone(kblint.read_meta(self.wiki / "alpha" / "no-h1.md")["header_end"])

    def test_13_duplicate_keys_and_order(self):
        self.put("alpha/kjo.md", "# KJO\n\n**Category:** alpha\n**Sources:** a.md\n**Tags:** t\n"
                                 "**Updated:** 2026-01-01\n**Type:** article\n**Sources:** [[RAW/source-one.md]]\n")
        self.edit("beta/third.md", "**Confidence:** moderate", "**Confidence:** moderate\n**Confidence:** low")
        self.edit("alpha/second.md", "**Type:** article", "**Confidence:** high\n**Type:** article")
        rep = self.lint()
        legacy = self.checks(rep, "header-legacy-duplicate")
        self.assertEqual([(f["id"], f["severity"], f["detail"]) for f in legacy], [("kjo", "WARN", "Sources x2")])
        dup = self.checks(rep, "header-duplicate-key")
        self.assertEqual([(f["id"], f["severity"]) for f in dup], [("third", "FAIL")])
        self.assertEqual([(f["id"], f["severity"]) for f in self.checks(rep, "header-order")], [("second", "WARN")])

    def test_14_core_claim_line_counts_as_body(self):
        text = ("# T\n\n**Category:** a\n**Sources:** x y z\n**Updated:** 2026-01-01\n**Type:** article\n"
                "**Core Claim:** one two three\n\nfour five\n")
        h = kblint.parse_header(text)
        self.assertEqual(kblint.body_words(h), 7)  # '**Core', 'Claim:**', one two three, four five
        self.assertEqual(h["header_end"], 8)


class CliAndMigrate(LintCase):
    def test_09_migrate_inserts_one_line_and_revert_round_trips(self):
        body = "**Category:** gamma\n**Sources:** [[RAW/source-one.md]]\n**Updated:** 2026-01-01\n\n## Core Claim\nG.\n"
        self.put("gamma/_index.md", "# Gamma\n\n**Articles:** 2\n**Updated:** 2026-01-01\n\n- [[one]]\n")
        self.put("gamma/one.md", "# One\n\n" + body)
        self.put("gamma/two.md", "\n# Two\n\n" + body.rstrip("\n"))  # leading blank, no final newline
        gamma = self.wiki / "gamma"
        before = {p.name: p.read_bytes() for p in gamma.iterdir()}
        digest = kb_testkit.tree_digest(gamma)
        self.assertEqual(self.run_cli("--migrate", "dry-run", "--category", "gamma")[0], 0)
        self.assertEqual(kb_testkit.tree_digest(gamma), digest)
        self.assertEqual(self.run_cli("--migrate", "write", "--category", "gamma")[0], 0)
        for p in gamma.iterdir():
            after = p.read_text(encoding="utf-8").split("\n")
            old = before[p.name].decode("utf-8").split("\n")
            self.assertEqual(len(after), len(old) + 1)
            typed = [l for l in after if l.startswith("**Type:** ")]
            self.assertEqual(typed, ["**Type:** " + ("taxonomy" if p.name == "_index.md" else "article")])
            self.assertEqual("\n".join(l for l in after if l not in typed).encode("utf-8"), before[p.name])
        self.assertEqual(self.lint(category="gamma")["findings"], [])
        self.assertEqual(self.run_cli("--migrate", "revert", "--category", "gamma")[0], 0)
        self.assertEqual(kb_testkit.tree_digest(gamma), digest)
        # revert refuses a page that carries any other v2 key
        self.run_cli("--migrate", "write", "--category", "gamma")
        self.edit("gamma/one.md", "**Type:** article", "**Type:** article\n**Confidence:** low")
        rc, out = self.run_cli("--migrate", "revert", "--category", "gamma")
        self.assertEqual(rc, 1)
        self.assertIn("REFUSED KB/wiki/gamma/one.md", out)
        self.assertIn("**Type:** article", (gamma / "one.md").read_text(encoding="utf-8"))

    def test_10_lint_never_mutates(self):
        self.strip_types()
        before = kb_testkit.tree_digest(self.root)
        for args in ([], ["--json"], ["--rule", "all"], ["--category", "alpha"], ["--category", "_root"],
                     ["--contract"], ["--migrate", "dry-run", "--category", "alpha"]):
            self.run_cli(*args)
        self.assertEqual(kb_testkit.tree_digest(self.root), before)

    def test_11_exit_codes_0_1_2(self):
        self.assertEqual(self.run_cli()[0], 0)
        self.edit("alpha/second.md", "**Type:** article\n", "")
        self.assertEqual(self.run_cli()[0], 2)
        self.edit("alpha/first.md", "**Depends-On:** second", "**Depends-On:** ghost")
        self.assertEqual(self.run_cli()[0], 1)
        self.assertEqual(self.run_cli("--category", "nope")[0], 1)
        self.assertEqual(self.run_cli("--migrate", "write")[0], 1)  # --migrate requires --category
        with self.assertRaises(SystemExit) as bad:
            self.run_cli("--rule", "WP9")
        self.assertEqual(bad.exception.code, 1)  # usage errors are FATAL, never the WARN code

    def test_15_capture_baseline_preserves_other_keys(self):
        path = self.root / "evals" / "kb-health-baseline.json"
        before = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(self.run_cli("--capture-baseline")[0], 0)
        after = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(after["lint"], {"captured": date.today().isoformat(), "over_soft_budget": 0})
        self.assertEqual({k: v for k, v in after.items() if k != "lint"}, before)
        self.assertEqual(list(after)[:len(before)], list(before))

    def test_contract_prints_canonical_order_meta_and_budgets(self):
        rc, out = self.run_cli("--contract")
        c = json.loads(out)
        self.assertEqual(rc, 0)
        self.assertEqual(c["header"]["v2_keys_canonical_order"],
                         ["Type", "Depends-On", "Consumers", "Confidence", "Last-Verified", "Provenance"])
        self.assertIn("Provenance", c["meta"])
        self.assertEqual(c["types"]["article"], {"path_default": "<cat>/<stem>.md", "soft_words": 400,
                                                 "hard_words": 2000})
        self.assertFalse(c["type_required"])


class Fixture16(LintCase):
    indexes = True  # default kb_testkit path: builds kb-index + kb-graph under the fixture root

    def test_16_kb_index_root_leaves_live_dashboard_untouched(self):
        stamp = dash_stamp()
        self.assertTrue((self.root / "KB" / "output" / "kb-search.html").exists())
        res = subprocess.run([sys.executable, str(TOOLS / "kb-index.py"), "--root", str(self.root)],
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        index = json.loads((self.root / "KB" / "output" / "kb-index.json").read_text(encoding="utf-8"))
        self.assertEqual(index["article_count"], 3)
        self.assertEqual(dash_stamp(), stamp)

    def test_tools_make_no_network_or_llm_calls(self):
        for name in ("kb-lint.py", "kb_testkit.py", "kb-index.py"):
            hits = [l for l in (TOOLS / name).read_text(encoding="utf-8").splitlines() if NO_NETWORK_RE.search(l)]
            self.assertEqual(hits, [], name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
