#!/usr/bin/env python3
"""Tests for kb-write.py (inbox put/link/withdraw/list, seal, adopt, reseal) and kb-lint WP1/WP2.

P2-S1 scope: spec P2 §8 cases 1-4, 10-12 and 14 (numbered in test names), plus the unknown-key
failure, link, list and seal cases. Every case runs on kb_testkit.fixture() with --root <tmp>; the
load-bearing guards are that put never touches KB/wiki and that no suite touches the live
KB/output/kb-search.html.

Run: python3 tools/test-kb-write.py
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
from datetime import date, timedelta
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
ROOT = TOOLS.parent
LIVE_DASH = ROOT / "KB" / "output" / "kb-search.html"
NO_NETWORK_RE = re.compile(r"(import|from) (requests|urllib|http\.client|socket|httpx|aiohttp)\b|subprocess.*(curl|wget|llm)|https?://")
TODAY = date.today().isoformat()

sys.path.insert(0, str(TOOLS))
import kb_testkit  # noqa: E402

kbw = kb_testkit.load("kb-write.py")
kblint = kb_testkit.load("kb-lint.py")


def dash_stamp():
    return LIVE_DASH.stat().st_mtime_ns if LIVE_DASH.exists() else None


LIVE_DASH_BEFORE = dash_stamp()


def tearDownModule():
    assert dash_stamp() == LIVE_DASH_BEFORE, "suite touched the live kb-search.html"


class WriteCase(unittest.TestCase):
    indexes = False  # kb-write reads kb-graph.json only for link types; Links builds it
    git = False  # unland reads prior bytes from KB/inbox/_objects; git is only the legacy fallback

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = kb_testkit.fixture(self.tmp, indexes=self.indexes, git=self.git)
        self.inbox = self.root / "KB" / "inbox"
        self.body = self.tmp / "body.md"
        self.body.write_text("# Missing: inbox write-back\n\nNo page covers the inbox.\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def cli(self, *args):
        """(rc, parsed JSON stdout) for one in-process kb-write call."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            rc = kbw.main(list(args[:1]) + ["--root", str(self.root), "--json"] + list(args[1:]))
        return rc, json.loads(buf.getvalue())

    def gap(self, slug="inbox-gap", agent="RESEARCHER", target="inbox", *extra):
        return self.cli("put", "--agent", agent, "--kind", "gap", "--slug", slug, "--confidence", "low",
                        "--source-ref", "owner:" + TODAY, "--gap-kind", "missing", "--target", target,
                        "--body-file", str(self.body), *extra)

    def article(self, *extra):
        return self.cli("put", "--agent", "RESEARCHER", "--kind", "article", "--slug", "fourth", "--category", "beta",
                        "--confidence", "moderate", "--source-ref", "raw:source-one.md",
                        "--body-file", str(self.body), *extra)

    def ledger(self):
        return kbw.read_ledger(self.root)

    def wp(self, rule):
        rep = kblint.lint(self.root, rule=rule)
        return kblint.exit_code(rep), rep["findings"]

    def wiki_digest(self):
        return kb_testkit.tree_digest(self.root / "KB" / "wiki")


class Inbox(WriteCase):
    def test_01_put_writes_the_inbox_only(self):
        wiki, outside = self.wiki_digest(), kb_testkit.tree_digest(self.root / "KB" / "RAW")
        rc, out = self.article()
        self.assertEqual(rc, 0, out)
        pid = "RESEARCHER/%s-fourth" % TODAY
        self.assertEqual(out, {"ok": True, "verb": "put", "id": pid, "path": "KB/inbox/%s.md" % pid, "ledger_seq": 1})
        meta, body = kbw.parse((self.root / out["path"]).read_text(encoding="utf-8"))
        self.assertEqual((meta["id"], meta["kind"], meta["state"], meta["type"], meta["category"], meta["stem"]),
                         (pid, "article", "open", "article", "beta", "fourth"))
        self.assertEqual(meta["source_refs"], ["raw:source-one.md"])
        self.assertEqual(body, self.body.read_text(encoding="utf-8"))
        self.assertEqual((self.wiki_digest(), kb_testkit.tree_digest(self.root / "KB" / "RAW")), (wiki, outside))
        self.assertEqual(sorted(p.name for p in self.inbox.iterdir()), ["RESEARCHER", "_ledger.jsonl"])
        row = self.ledger()[0]
        self.assertEqual((row["seq"], row["event"], row["id"], row["actor"]), (1, "put", pid, "RESEARCHER"))
        self.assertEqual(row["files"], {out["path"]: kbw.sha256((self.root / out["path"]).read_bytes())})
        self.assertEqual(row["prior"], {out["path"]: None})
        self.assertEqual(self.wp("WP2"), (0, []))

    def test_02_unresolved_ref_exits_2_and_writes_nothing(self):
        before = kb_testkit.tree_digest(self.root)
        bad = (["--source-ref", "raw:ghost.md"], ["--source-ref", "raw:../wiki/alpha/first.md"],
               ["--source-ref", "wiki:ghost"], ["--source-ref", "output:none.json"],
               ["--source-ref", "owner:2026-13-01"], ["--source-ref", "owner:" + (date.today() + timedelta(days=1)).isoformat()],
               ["--source-ref", "web:example"])
        for refs in bad:
            rc, out = self.cli("put", "--agent", "RESEARCHER", "--kind", "gap", "--slug", "x", "--confidence", "low",
                               "--gap-kind", "thin", "--target", "first", "--body-file", str(self.body), *refs)
            self.assertEqual(rc, 2, (refs, out))
        rc, out = self.cli("put", "--agent", "RESEARCHER", "--kind", "article", "--slug", "fourth", "--category", "beta",
                           "--confidence", "low", "--source-ref", "wiki:first", "--body-file", str(self.body))
        self.assertEqual(rc, 2)
        self.assertIn("at least one raw: or owner:", out["detail"])
        self.assertEqual(kb_testkit.tree_digest(self.root), before)
        self.assertFalse(self.inbox.exists())

    def test_03_duplicate_gap_exits_4_until_withdrawn(self):
        rc, first = self.gap()
        self.assertEqual(rc, 0)
        rc, dup = self.gap("same-gap-new-slug")  # same kind|gap_kind|target|title -> same dedupe_key
        self.assertEqual(rc, 4)
        self.assertIn(first["id"], dup["detail"])
        self.assertEqual(len(self.ledger()), 1)
        self.assertEqual(self.gap("other-gap", target="other")[0], 0)  # another target is another gap
        self.cli("withdraw", first["id"], "--reason", "superseded", "--by", "RESEARCHER")
        rc, again = self.gap()  # dedupe only checks open proposals; the taken name gets -2
        self.assertEqual(rc, 0)
        self.assertEqual(again["id"], first["id"] + "-2")
        self.assertEqual(self.wp("WP2"), (0, []))

    def test_04_withdraw_keeps_the_file_and_needs_a_reason(self):
        _, put = self.gap()
        path = self.root / put["path"]
        self.assertEqual(self.cli("withdraw", put["id"], "--by", "RESEARCHER")[0], 2)
        self.assertEqual(self.cli("withdraw", put["id"], "--reason", "  ", "--by", "RESEARCHER")[0], 2)
        self.assertEqual(self.cli("withdraw", put["id"], "--reason", "mine now", "--by", "BUILDER")[0], 2)
        self.assertEqual(self.cli("withdraw", "RESEARCHER/%s-ghost" % TODAY, "--reason", "r", "--by", "RESEARCHER")[0], 1)
        self.assertEqual(len(self.ledger()), 1)
        rc, out = self.cli("withdraw", put["id"], "--reason", "covered elsewhere", "--by", "RESEARCHER")
        self.assertEqual((rc, out["ledger_seq"]), (0, 2))
        meta, _ = kbw.parse(path.read_text(encoding="utf-8"))
        self.assertEqual((meta["state"], meta["reason"]), ("withdrawn", "covered elsewhere"))
        row = self.ledger()[1]
        self.assertEqual((row["event"], row["actor"], row["reason"]), ("withdraw", "RESEARCHER", "covered elsewhere"))
        self.assertEqual(row["files"][put["path"]], kbw.sha256(path.read_bytes()))
        self.assertEqual(self.cli("withdraw", put["id"], "--reason", "again", "--by", "RESEARCHER")[0], 2)  # not open
        self.assertEqual(self.wp("WP2"), (0, []))

    def test_11_lock_held_exits_5(self):
        self.inbox.mkdir(parents=True)
        (self.inbox / ".lock").write_text("123", encoding="utf-8")
        rc, out = self.gap()
        self.assertEqual((rc, out["error"]), (5, "lock held"))
        self.assertEqual(sorted(p.name for p in self.inbox.iterdir()), [".lock"])
        self.assertEqual(self.wp("WP2"), (0, []))  # .lock is reserved, never a stray
        (self.inbox / ".lock").unlink()
        self.assertEqual(self.gap()[0], 0)
        self.assertFalse((self.inbox / ".lock").exists())

    def test_12_crafted_slug_category_agent_or_id_cannot_escape(self):
        before = kb_testkit.tree_digest(self.root)
        for flags in (("--slug", "../../wiki/alpha/first"), ("--slug", "Upper"), ("--slug", "a" * 61),
                      ("--category", "../RAW"), ("--category", "alpha/../../RAW"), ("--agent", "../KB"),
                      ("--agent", "REPURPOSER"), ("--agent", "the owner")):
            args = {"--slug": "fourth", "--category": "beta", "--agent": "RESEARCHER"}
            args[flags[0]] = flags[1]
            rc, _ = self.cli("put", "--agent", args["--agent"], "--kind", "article", "--slug", args["--slug"],
                             "--category", args["--category"], "--confidence", "low", "--source-ref", "raw:source-one.md",
                             "--body-file", str(self.body))
            self.assertEqual(rc, 2, flags)
        self.assertEqual(self.cli("withdraw", "../wiki/alpha/first", "--reason", "r", "--by", "RESEARCHER")[0], 2)
        with self.assertRaises(kbw.Fail) as refused:
            kbw._write(self.root, "KB/wiki/alpha/first.md", b"x", "put")
        self.assertEqual(refused.exception.code, 2)
        with self.assertRaises(kbw.Fail):
            kbw._write(self.root, "KB/inbox/../wiki/alpha/first.md", b"x", "put")
        with self.assertRaises(kbw.Fail):
            kbw._write(self.root, "KB/inbox/RESEARCHER/x.md", b"x", "adopt")  # adopt may append the ledger only
        self.assertEqual(kb_testkit.tree_digest(self.root), before)

    def test_14_missing_gap_accepts_a_query_ref_only_there(self):
        query = ["--source-ref", "query:0123456789ab"]
        rc, out = self.cli("put", "--agent", "owner", "--kind", "gap", "--slug", "asked-not-found", "--confidence",
                           "low", "--gap-kind", "missing", "--target", "inbox", "--query", "what is the inbox",
                           "--body-file", str(self.body), *query)
        self.assertEqual(rc, 0, out)
        self.assertTrue(out["id"].startswith("owner/"))
        rc, _ = self.cli("put", "--agent", "owner", "--kind", "gap", "--slug", "thin-one", "--confidence", "low",
                         "--gap-kind", "thin", "--target", "first", "--body-file", str(self.body), *query)
        self.assertEqual(rc, 2)
        self.assertEqual(self.wp("WP2"), (0, []))

    def test_unknown_frontmatter_key_exits_2_and_fails_wp2(self):
        _, put = self.gap()
        path = self.root / put["path"]
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("state: open\n", "state: open\ncolor: red\n"), encoding="utf-8")
        rc, out = self.cli("withdraw", put["id"], "--reason", "r", "--by", "RESEARCHER")
        self.assertEqual(rc, 2)
        self.assertIn("color", out["detail"])
        rc, findings = self.wp("WP2")
        self.assertEqual(rc, 1)
        self.assertEqual([(f["check"], f["severity"]) for f in findings], [("wp2-unknown-key", "FAIL")])
        self.body.write_text("---\ncolor: red\n---\n# Smuggled\n", encoding="utf-8")
        self.assertEqual(self.gap("smuggled", target="elsewhere")[0], 2)  # frontmatter is tool-set only

    def test_wp2_flags_strays_state_drift_and_ledger_gaps(self):
        _, put = self.gap()
        path = self.root / put["path"]
        (self.inbox / "notes.txt").write_text("x", encoding="utf-8")
        (self.inbox / "RESEARCHER" / "scratch.md").write_text("x", encoding="utf-8")
        (self.inbox / "REPURPOSER").mkdir()
        (self.inbox / "_corrections").mkdir()  # reserved: exempt
        path.write_text(path.read_text(encoding="utf-8").replace("state: open", "state: landed"), encoding="utf-8")
        rc, findings = self.wp("WP2")
        self.assertEqual(rc, 1)
        got = sorted((f["path"], f["check"]) for f in findings)
        self.assertEqual(got, sorted([("KB/inbox/RESEARCHER/%s.md" % put["id"].split("/")[1], "wp2-state"),
                                      ("KB/inbox/RESEARCHER/scratch.md", "wp2-stray"),
                                      ("KB/inbox/REPURPOSER", "wp2-stray"), ("KB/inbox/notes.txt", "wp2-stray")]))
        ledger = self.inbox / "_ledger.jsonl"
        ledger.write_text(ledger.read_text(encoding="utf-8").replace('"seq":1', '"seq":3'), encoding="utf-8")
        self.assertIn("wp2-ledger", [f["check"] for f in self.wp("WP2")[1]])
        self.assertEqual(self.gap("after-corruption", target="t2")[0], 2)  # a broken ledger blocks writes


class Links(WriteCase):
    indexes = True  # link types come from KB/output/kb-graph.json type_vocabulary

    def test_link_put_validates_ends_type_and_prose(self):
        base = ["--agent", "RESEARCHER", "--from", "third", "--to", "first", "--confidence", "moderate",
                "--source-ref", "wiki:first"]
        graph = self.root / "KB" / "output" / "kb-graph.json"
        g = json.loads(graph.read_text(encoding="utf-8"))
        self.assertEqual(g["type_vocabulary"], [])  # empty vocabulary -> {RELATES_TO} only
        self.assertEqual(self.cli("link", *base, "--type", "GROUNDS", "--prose", "xyz")[0], 2)
        g["type_vocabulary"] = ["GROUNDS", "APPLIES", "RELATES_TO"]
        graph.write_text(json.dumps(g), encoding="utf-8")
        rc, out = self.cli("link", *base, "--type", "GROUNDS", "--prose", " grounds the first claim ")
        self.assertEqual(rc, 0, out)
        meta, body = kbw.parse((self.root / out["path"]).read_text(encoding="utf-8"))
        self.assertEqual((meta["kind"], meta["link_from"], meta["link_to"], meta["link_type"], meta["prose"]),
                         ("link", "third", "first", "GROUNDS", "grounds the first claim"))
        self.assertEqual(body, "- [[first]] — grounds the first claim\n")
        self.assertEqual(self.cli("link", *base, "--type", "GROUNDS", "--prose", "same edge again")[0], 4)
        self.assertEqual(self.cli("link", *base, "--type", "BOGUS", "--prose", "xyz")[0], 2)
        self.assertEqual(self.cli("link", *base, "--type", "APPLIES", "--prose", "ab")[0], 2)
        bad_from = ["--from", "ghost"] + base[4:]
        self.assertEqual(self.cli("link", "--agent", "RESEARCHER", *bad_from, "--type", "APPLIES", "--prose", "xyz")[0], 2)
        self.assertEqual(self.wp("WP2"), (0, []))


class SealAndList(WriteCase):
    def test_10_direct_wiki_write_flags_wp1_and_adopt_clears_it(self):
        self.assertEqual(self.wp("WP1")[1][0]["check"], "wp1-unverifiable")  # no seal yet
        rc, out = self.cli("seal")
        self.assertEqual((rc, out["count"]), (0, kblint.lint(self.root)["file_count"]))
        self.assertEqual(self.cli("seal")[0], 4)  # one seal; re-base with --reseal
        self.assertEqual(self.wp("WP1"), (0, []))
        first = self.root / "KB" / "wiki" / "alpha" / "first.md"
        first.write_text(first.read_text(encoding="utf-8") + "hand edit\n", encoding="utf-8")
        (self.root / "KB" / "wiki" / "beta" / "loose.md").write_text("# Loose\n", encoding="utf-8")
        rc, findings = self.wp("WP1")
        self.assertEqual(rc, 2)  # WARN through P2-S2 (D4)
        self.assertEqual(sorted((f["path"], f["check"], f["severity"]) for f in findings),
                         [("KB/wiki/alpha/first.md", "wp1-edited", "WARN"), ("KB/wiki/beta/loose.md", "wp1-new", "WARN")])
        self.assertIn("--adopt KB/wiki/alpha/first.md", findings[0]["detail"])
        adopt = ["land", "--adopt", "KB/wiki/alpha/first.md", "KB/wiki/beta/loose.md"]
        self.assertEqual(self.cli(*adopt, "--reason", "hand edit")[0], 2)  # needs --endorsed-by owner
        self.assertEqual(self.cli("land", "--adopt", "KB/RAW/source-one.md", "--reason", "r",
                                  "--endorsed-by", "owner")[0], 2)
        rc, out = self.cli(*adopt, "--reason", "hand edit", "--endorsed-by", "owner")
        self.assertEqual((rc, out["ledger_seq"]), (0, 1))
        self.assertEqual(self.wp("WP1"), (0, []))
        self.assertEqual(self.cli(*adopt, "--reason", "again", "--endorsed-by", "owner")[0], 2)  # nothing to adopt
        (self.root / "KB" / "wiki" / "beta" / "loose.md").unlink()
        self.assertEqual([f["check"] for f in self.wp("WP1")[1]], ["wp1-deleted"])
        self.assertEqual(self.cli("seal", "--reseal", "--reason", "r")[0], 2)
        rc, out = self.cli("seal", "--reseal", "--reason", "phase test", "--endorsed-by", "owner")
        self.assertEqual((rc, out["ledger_seq"], out["count"]), (0, 2, 1))
        rows = self.ledger()
        self.assertEqual([r["event"] for r in rows], ["adopt", "reseal"])
        self.assertEqual(rows[1]["files"], {"KB/wiki/beta/loose.md": None})
        self.assertEqual(self.wp("WP1"), (0, []))
        self.assertEqual(self.wp("WP2"), (0, []))

    def test_list_json_filters_by_state_origin_and_since(self):
        self.gap("from-think", "RESEARCHER", "t1", "--origin", "skill:brain-think")
        _, by_hand = self.gap("by-hand", "owner", "t2")
        self.cli("withdraw", by_hand["id"], "--reason", "test", "--by", "owner")
        rc, out = self.cli("list")
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(i["id"].split("/")[0] for i in out["items"]), ["RESEARCHER", "owner"])
        self.assertTrue(all({"origin", "proposed_at"} <= set(i) for i in out["items"]))
        self.assertEqual([i["origin"] for i in self.cli("list", "--origin", "skill:")[1]["items"]],
                         ["skill:brain-think"])
        self.assertEqual([i["id"] for i in self.cli("list", "--state", "withdrawn")[1]["items"]], [by_hand["id"]])
        self.assertEqual(len(self.cli("list", "--since", TODAY)[1]["items"]), 2)
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        self.assertEqual(self.cli("list", "--since", tomorrow)[1]["items"], [])
        self.assertEqual(self.cli("list", "--since", "yesterday")[0], 1)
        self.assertEqual(self.cli("put", "--agent", "RESEARCHER", "--kind", "gap", "--slug", "o", "--confidence", "low",
                                  "--source-ref", "owner:" + TODAY, "--gap-kind", "thin", "--target", "x",
                                  "--body-file", str(self.body), "--origin", "chat")[0], 2)

    def test_contract_constants_and_no_network(self):
        self.assertEqual(kbw.LEDGER_EVENTS, ("put", "withdraw", "reject", "land", "unland", "resolve", "adopt", "reseal", "recover"))
        self.assertEqual(kbw.FAULT_POINTS, ("after-page", "after-derived", "after-ledger", "after-proposal", "after-case"))
        self.assertIn("_objects", kbw.RESERVED_DIRS)
        self.assertIn("_ops", kbw.RESERVED_DIRS)
        self.assertEqual(set(kbw.VERB_FN), set(kbw.VERBS))
        self.assertEqual({"WP1", "WP2"} <= set(kblint.RULES), True)
        self.assertEqual(kblint.WP1_SEVERITY, "WARN")
        for name in ("kb-write.py", "kb-lint.py"):
            hits = [l for l in (TOOLS / name).read_text(encoding="utf-8").splitlines() if NO_NETWORK_RE.search(l)]
            self.assertEqual(hits, [], name)
        self.assertEqual(dash_stamp(), LIVE_DASH_BEFORE)


LONG = " ".join(["Inbox write-back lands through one gate with a ledger row and a seal."] * 12)
SUPERSEDE = "# First\n\n## Core Claim\nFirst claim here, sharpened.\n\n## Evidence\nZebrafish evidence kept. %s\n" % LONG


class Land(WriteCase):
    indexes = True

    def setUp(self):
        super().setUp()
        self.body.write_text("# Fourth\n\n## Core Claim\n%s\n" % LONG, encoding="utf-8")
        rc, out = self.cli("seal")
        assert rc == 0, out

    def land(self, pid, *extra):
        return self.cli("land", pid, "--endorsed-by", "owner", *extra)

    def test_p2s2_01_land_new_stem_writes_wiki_with_provenance(self):
        rc, out = self.article()
        self.assertEqual(rc, 0, out)
        pid = out["id"]
        rc, res = self.land(pid)
        self.assertEqual(rc, 0, res)
        page = (self.root / res["path"]).read_text(encoding="utf-8")
        self.assertEqual(page.count("**Provenance:**"), 1)
        self.assertIn("**Type:** article", page)
        self.assertIn("**Confidence:** moderate", page)
        row = self.ledger()[-1]
        self.assertEqual((row["event"], row["id"], row["actor"]), ("land", pid, "owner"))
        self.assertIsNone(row["prior"][res["path"]])
        meta, _ = kbw.parse((self.root / "KB/inbox" / (pid + ".md")).read_text(encoding="utf-8"))
        self.assertEqual((meta["state"], meta["endorsed_by"], meta["landed_path"]), ("landed", "owner", res["path"]))
        self.assertTrue(meta["decided_at"])
        self.assertEqual(self.wp("WP1")[0], 0)

    def test_p2s2_02_dry_run_writes_nothing(self):
        pid = self.article()[1]["id"]
        before, ledger = kb_testkit.tree_digest(self.root / "KB"), len(self.ledger())
        rc, _ = self.land(pid, "--dry-run")
        self.assertEqual(rc, 0)
        self.assertEqual((kb_testkit.tree_digest(self.root / "KB"), len(self.ledger())), (before, ledger))

    def test_p2s2_03_fault_rolls_back_bytes_and_exits_3(self):
        import os
        pid = self.article()[1]["id"]
        wiki, ledger = self.wiki_digest(), len(self.ledger())
        os.environ[kbw.FAULT_ENV] = "postcheck"
        try:
            rc, out = self.land(pid)
        finally:
            os.environ.pop(kbw.FAULT_ENV, None)
        self.assertEqual(rc, 3, out)
        self.assertEqual((self.wiki_digest(), len(self.ledger())), (wiki, ledger))

    def test_p2s2_04_unland_restores_prior_bytes(self):
        wiki = self.wiki_digest()
        pid = self.article()[1]["id"]
        self.assertEqual(self.land(pid)[0], 0)
        rc, out = self.cli("unland", pid, "--endorsed-by", "owner", "--reason", "test")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.wiki_digest(), wiki)
        self.assertEqual(self.ledger()[-1]["event"], "unland")
        meta, _ = kbw.parse((self.root / "KB/inbox" / (pid + ".md")).read_text(encoding="utf-8"))
        self.assertEqual(meta["state"], "open")

    def test_p2s2_05_supersede_inherits_sources_and_replaces_provenance(self):
        self.body.write_text("# First\n\n## Core Claim\nFirst claim here, sharpened.\n\n## Evidence\n"
                             "Zebrafish evidence kept. %s\n" % LONG, encoding="utf-8")
        rc, out = self.article("--supersedes", "wiki:first", "--category", "alpha")
        self.assertEqual(rc, 0, out)
        rc, res = self.land(out["id"])
        self.assertEqual(rc, 0, res)
        page = (self.root / res["path"]).read_text(encoding="utf-8")
        self.assertIn("[[RAW/source-one.md]]", page)
        self.assertEqual(page.count("**Provenance:**"), 1)
        self.body.write_text("# First\n\n## Core Claim\nFirst claim here, sharpened twice.\n\n## Evidence\n"
                             "Zebrafish evidence kept. %s\n" % LONG, encoding="utf-8")
        rc, out2 = self.article("--supersedes", "wiki:first", "--category", "alpha", "--slug", "fourth-b")
        self.assertEqual(rc, 0, out2)
        self.assertEqual(self.land(out2["id"])[0], 0)
        page = (self.root / res["path"]).read_text(encoding="utf-8")
        self.assertEqual(page.count("**Provenance:**"), 1)
        self.assertIn(out2["id"].split("/", 1)[1], page)

    def test_p2s2_06_reject_and_resolve(self):
        pid = self.article()[1]["id"]
        self.assertEqual(self.cli("reject", pid, "--by", "RESEARCHER", "--reason", "no")[0], 2)
        rc, out = self.cli("reject", pid, "--by", "owner", "--reason", "off-voice")
        self.assertEqual(rc, 0, out)
        meta, _ = kbw.parse((self.root / out["path"]).read_text(encoding="utf-8"))
        self.assertEqual((meta["state"], meta["reason"]), ("rejected", "off-voice"))
        self.assertTrue(meta["decided_at"])
        gid = self.gap()[1]["id"]
        self.assertEqual(self.cli("resolve", gid, "--by", "owner", "--reason", "covered")[0], 0)
        self.assertEqual(self.ledger()[-1]["event"], "resolve")

    def test_p2s2_08_correction_land_records_hook_skipped(self):
        rc, out = self.article("--origin", "correction:C-0001")
        self.assertEqual(rc, 0, out)
        with mock.patch.object(kbw, "HOOK", self.tmp / "absent" / "kb-correct.py"):
            rc, res = self.land(out["id"])
        self.assertEqual(rc, 0, res)
        self.assertTrue(self.ledger()[-1].get("hook_skipped"), self.ledger()[-1])

    def test_p2s2_08b_correction_land_rolls_back_when_the_hook_fails(self):
        rc, out = self.article("--origin", "correction:C-0001")  # C-0001 has no record: landed exits nonzero
        self.assertEqual(rc, 0, out)
        state, rows = kb_testkit.state_digest(self.root), self.ledger()
        rc, res = self.land(out["id"])
        self.assertEqual(rc, 3, res)
        self.assertIn("regression registration failed", res["detail"])
        self.assertEqual((kb_testkit.state_digest(self.root), self.ledger()), (state, rows))
        self.assertEqual(list((self.inbox / "_ops").iterdir()), [])

    # ---- recovery: preimages, journal, fault points ----

    def fault(self, point, *args):
        import os
        os.environ[kbw.FAULT_ENV] = point
        try:
            return self.cli(*args)
        finally:
            os.environ.pop(kbw.FAULT_ENV, None)

    def state(self, pid):
        meta, _ = kbw.parse((self.inbox / (pid + ".md")).read_text(encoding="utf-8"))
        return meta["state"]

    def test_recovery_01_land_stores_preimages_content_addressed(self):
        self.body.write_text(SUPERSEDE, encoding="utf-8")
        pid = self.article("--supersedes", "wiki:first", "--category", "alpha")[1]["id"]
        rc, res = self.land(pid)
        self.assertEqual(rc, 0, res)
        prior = self.ledger()[-1]["prior"]["KB/wiki/alpha/first.md"]
        obj = self.inbox / "_objects" / prior
        self.assertEqual(kbw.sha256(obj.read_bytes()), prior)
        self.assertEqual(obj.read_text(encoding="utf-8"), kb_testkit.WIKI["alpha/first.md"])
        self.assertFalse((self.root / ".git").exists())
        self.assertEqual(self.wp("WP2")[0], 0)  # _objects/ is reserved

    def test_recovery_02_supersede_then_unland_without_git(self):
        wiki = self.wiki_digest()
        self.body.write_text(SUPERSEDE, encoding="utf-8")
        pid = self.article("--supersedes", "wiki:first", "--category", "alpha")[1]["id"]
        self.assertEqual(self.land(pid)[0], 0)
        self.assertNotEqual(self.wiki_digest(), wiki)
        rc, out = self.cli("unland", pid, "--endorsed-by", "owner", "--reason", "test")
        self.assertEqual(rc, 0, out)
        self.assertIn("KB/wiki/alpha/first.md", out["exact"])
        self.assertEqual(self.wiki_digest(), wiki)
        self.assertEqual(self.state(pid), "open")

    def test_recovery_03_unland_refuses_a_page_changed_since_the_land(self):
        pid = self.article()[1]["id"]
        rc, res = self.land(pid)
        page = self.root / res["path"]
        page.write_text(page.read_text(encoding="utf-8") + "\nHand edit.\n", encoding="utf-8")
        rc, out = self.cli("unland", pid, "--endorsed-by", "owner", "--reason", "test")
        self.assertEqual(rc, 4, out)
        self.assertIn("changed since the land", out["detail"])

    def test_recovery_04_corrupt_object_is_never_restored(self):
        self.body.write_text(SUPERSEDE, encoding="utf-8")
        pid = self.article("--supersedes", "wiki:first", "--category", "alpha")[1]["id"]
        self.assertEqual(self.land(pid)[0], 0)
        prior = self.ledger()[-1]["prior"]["KB/wiki/alpha/first.md"]
        (self.inbox / "_objects" / prior).write_bytes(b"tampered\n")
        self.assertIsNone(kbw.get_object(self.root, prior))
        rc, out = self.cli("unland", pid, "--endorsed-by", "owner", "--reason", "test")
        self.assertEqual(rc, 4, out)  # no git, no valid object: refuse rather than guess

    def test_recovery_05_land_fault_at_every_point_recovers_and_converges(self):
        for point in ("after-page", "after-derived", "after-ledger", "after-proposal"):
            with self.subTest(point=point):
                self.tearDown()
                self.setUp()
                pid = self.article()[1]["id"]
                state, rows = kb_testkit.state_digest(self.root), self.ledger()
                rc, out = self.fault(point, "land", pid, "--endorsed-by", "owner")
                self.assertEqual(rc, 9, out)
                self.assertEqual(len(list((self.inbox / "_ops").iterdir())), 1)
                rc, out = self.cli("list")  # any invocation recovers first
                self.assertEqual(rc, 0, out)
                rec = out["recovered"][0]
                self.assertEqual(self.ledger()[-1]["event"], "recover")
                self.assertEqual(list((self.inbox / "_ops").iterdir()), [])
                if point == "after-proposal":  # the last step: the op completes
                    self.assertEqual(rec["action"], "completed")
                    self.assertEqual(self.state(pid), "landed")
                    self.assertEqual(self.land(pid)[0], 2)  # rerun: already landed
                else:
                    self.assertEqual(rec["action"], "rolled back")
                    self.assertEqual(kb_testkit.state_digest(self.root), state)
                    self.assertEqual(self.ledger()[:-1], rows)
                    self.assertEqual(self.land(pid)[0], 0)  # rerun converges
                self.assertEqual(self.state(pid), "landed")
                self.assertEqual(len([r for r in self.ledger() if r["event"] == "land"]), 1)
                self.assertEqual(self.wp("WP1")[0], 0)
                self.assertEqual(self.wp("WP2")[0], 0)

    def test_recovery_06_unland_fault_at_every_point_recovers_and_converges(self):
        for point in ("after-page", "after-derived", "after-ledger", "after-proposal"):
            with self.subTest(point=point):
                self.tearDown()
                self.setUp()
                wiki = self.wiki_digest()
                pid = self.article()[1]["id"]
                self.assertEqual(self.land(pid)[0], 0)
                state, rows = kb_testkit.state_digest(self.root), self.ledger()
                rc, out = self.fault(point, "unland", pid, "--endorsed-by", "owner", "--reason", "t")
                self.assertEqual(rc, 9, out)
                self.assertEqual(self.cli("list")[0], 0)
                if point == "after-proposal":
                    self.assertEqual(self.state(pid), "open")
                else:
                    self.assertEqual((kb_testkit.state_digest(self.root), self.ledger()[:-1]), (state, rows))
                    self.assertEqual(self.cli("unland", pid, "--endorsed-by", "owner", "--reason", "t")[0], 0)
                self.assertEqual((self.state(pid), self.wiki_digest()), ("open", wiki))
                self.assertEqual(self.wp("WP1")[0], 0)

    def test_recovery_07_legacy_instance_without_objects_falls_back_to_git(self):
        self.tearDown()
        self.git = True
        self.setUp()
        wiki = self.wiki_digest()
        self.body.write_text(SUPERSEDE, encoding="utf-8")
        pid = self.article("--supersedes", "wiki:first", "--category", "alpha")[1]["id"]
        self.assertEqual(self.land(pid)[0], 0)
        shutil.rmtree(self.inbox / "_objects")  # an instance from before the preimage store
        rc, out = self.cli("unland", pid, "--endorsed-by", "owner", "--reason", "test")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.wiki_digest(), wiki)

    def test_config_owner_and_agents_are_instance_settings(self):
        (self.root / "KB" / "kb.json").write_text(json.dumps({"owner": "ada", "agents": ["SCOUT"]}), encoding="utf-8")
        self.assertEqual(kbw.agent_names(self.root) >= {"ada", "SCOUT", "RESEARCHER"}, True)
        self.assertNotIn("owner", kbw.agent_names(self.root))
        rc, out = self.cli("put", "--agent", "SCOUT", "--kind", "article", "--slug", "scouted", "--category", "beta",
                           "--confidence", "low", "--source-ref", "owner:" + TODAY, "--body-file", str(self.body))
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.cli("land", out["id"], "--endorsed-by", "owner")[0], 2)
        rc, res = self.cli("land", out["id"], "--endorsed-by", "ada")
        self.assertEqual(rc, 0, res)
        self.assertEqual(self.ledger()[-1]["actor"], "ada")
        self.assertIn("endorsed ada", (self.root / res["path"]).read_text(encoding="utf-8"))
        (self.root / "KB" / "kb.json").write_text(json.dumps({"owner": "Ada Lovelace"}), encoding="utf-8")
        self.assertEqual(self.cli("list")[0], 1)

    def test_p2s2_07_land_requires_owner(self):
        pid = self.article()[1]["id"]
        self.assertEqual(self.cli("land", pid, "--endorsed-by", "ORCHESTRATOR")[0], 2)
        self.assertEqual(self.cli("land", pid)[0], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
