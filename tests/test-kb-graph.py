#!/usr/bin/env python3
"""Tests for kb-graph.py / kb-graph-query.py.

The load-bearing assertion is NON-MUTATION: the graph layer is derived, and KB/RAW plus
KB/wiki must be byte-identical before and after every build and every query. Mirrors the
tree-digest pattern in test-kb-autolink.py.

Run: python3 tools/test-kb-graph.py
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
ROOT = TOOLS.parent


def load(name: str):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_")[:-3], TOOLS / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


kbgraph = load("kb-graph.py")
kbquery = load("kb-graph-query.py")


def tree_digest(path: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(path.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(path).as_posix().encode("utf-8"))
            h.update(p.read_bytes())
    return h.hexdigest()


def fixture(tmp: Path) -> Path:
    """A miniature KB exercising every parse branch the real corpus contains."""
    root = tmp / "repo"
    wiki, raw, out = root / "KB" / "wiki", root / "KB" / "RAW", root / "KB" / "output"
    (wiki / "alpha").mkdir(parents=True)
    (wiki / "beta").mkdir(parents=True)
    raw.mkdir(parents=True)
    out.mkdir(parents=True)

    (raw / "source-one.md").write_text("raw one\n", encoding="utf-8")
    (raw / "source-two.md").write_text("raw two\n", encoding="utf-8")
    (raw / "never-cited.md").write_text("orphan source\n", encoding="utf-8")

    # canonical article: wikilink sources, Connections with em-dash prose, open questions
    (wiki / "alpha" / "first.md").write_text(
        "# First\n\n**Category:** alpha\n**Sources:** [[RAW/source-one.md]]\n**Updated:** 2026-01-01\n\n"
        "## Core Claim\nFirst claim here.\n\n"
        "## Evidence\nBody text mentioning zebrafish only here.\n\n"
        "## Connections\n- [[second]] — the relation prose\n- [[third]]\n\n"
        "## Open Questions\n- what is unresolved\n", encoding="utf-8")
    # bare-filename Sources (the 60-article shape) + '## Related' instead of '## Connections'
    (wiki / "alpha" / "second.md").write_text(
        "# Second\n\n**Category:** alpha\n**Sources:** `source-two.md`\n**Updated:** 2026-01-02\n\n"
        "## Core Claim\nSecond claim.\n\n"
        "## Related\n- [[alpha/first]] — points back\n", encoding="utf-8")
    # declared category disagrees with folder; no sources at all
    (wiki / "beta" / "third.md").write_text(
        "# Third\n\n**Category:** alpha / beta\n**Updated:** 2026-01-03\n\n"
        "## Core Claim\nThird claim.\n", encoding="utf-8")
    (wiki / "_index.md").write_text("# Index\n", encoding="utf-8")
    return root


class GraphBuild(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = fixture(self.tmp)
        self.out = self.root / "KB" / "output"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def build(self):
        g, errors = kbgraph.build(self.root, self.out, quiet=True)
        self.assertEqual(errors, [])
        return g

    def test_counts_and_nodes(self):
        g = self.build()
        self.assertEqual(g["counts"]["articles"], 3)
        self.assertEqual(g["counts"]["categories"], 2)
        self.assertEqual(g["counts"]["raw_sources"], 3)
        self.assertEqual({n["stem"] for n in g["nodes"]["article"]}, {"first", "second", "third"})

    def test_bare_filename_sources_are_parsed(self):
        """The 60-article backticked/bare Sources shape must not lose provenance."""
        g = self.build()
        cites = {(e["s"], e["o"]) for e in g["edges"] if e["p"] == "CITES_SOURCE" and e["o"]}
        self.assertIn(("first", "source-one.md"), cites)
        self.assertIn(("second", "source-two.md"), cites)

    def test_uncompiled_raw_is_visible(self):
        g = self.build()
        self.assertEqual(g["counts"]["raw_uncompiled"], 1)
        uncited = [r for r in g["nodes"]["raw"] if not r["cited_by"]]
        self.assertEqual([r["name"] for r in uncited], ["never-cited.md"])

    def test_related_section_links_are_captured(self):
        """A section-scoped parser would silently drop '## Related' — 22.5% of the real graph."""
        g = self.build()
        rel = {(e["s"], e["o"]) for e in g["edges"] if e["p"] == "RELATES_TO"}
        self.assertIn(("second", "first"), rel)
        self.assertIn(("first", "second"), rel)

    def test_relation_prose_is_carried_and_bare_links_marked(self):
        g = self.build()
        by_pair = {(e["s"], e["o"]): e for e in g["edges"] if e["p"] == "RELATES_TO"}
        self.assertEqual(by_pair[("first", "second")]["prose"], "the relation prose")
        self.assertEqual(by_pair[("first", "second")]["type"], "UNTYPED")
        self.assertEqual(by_pair[("first", "third")]["prose"], "")
        self.assertEqual(by_pair[("first", "third")]["type"], "BARE")

    def test_category_mismatch_detected(self):
        g = self.build()
        self.assertEqual(g["counts"]["category_mismatch"], 1)
        self.assertEqual(g["category_mismatch"][0]["article"], "third")

    def test_folder_is_canonical_category(self):
        """A compound '**Category:** alpha / beta' must not create a phantom taxonomy bucket."""
        g = self.build()
        cats = {e["o"] for e in g["edges"] if e["p"] == "IN_CATEGORY"}
        self.assertEqual(cats, {"alpha", "beta"})

    def test_open_questions_extracted(self):
        g = self.build()
        self.assertEqual(len(g["open_questions"]), 1)
        self.assertEqual(g["open_questions"][0]["article"], "first")

    def test_manifest_matches_disk(self):
        g = self.build()
        for row in g["manifest"]:
            data = (self.root / row["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), row["content_hash"])

    def test_build_does_not_mutate_kb(self):
        before = tree_digest(self.root / "KB" / "wiki")
        raw_before = tree_digest(self.root / "KB" / "RAW")
        self.build()
        self.assertEqual(tree_digest(self.root / "KB" / "wiki"), before)
        self.assertEqual(tree_digest(self.root / "KB" / "RAW"), raw_before)

    def test_check_reports_drift(self):
        g = self.build()
        (self.out / "kb-graph.json").write_text(json.dumps(g), encoding="utf-8")
        self.assertEqual(kbgraph.check(self.root, self.out), 0)
        target = self.root / "KB" / "wiki" / "alpha" / "first.md"
        target.write_text(target.read_text(encoding="utf-8") + "\nedited\n", encoding="utf-8")
        self.assertEqual(kbgraph.check(self.root, self.out), 2)


class GraphQuery(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = fixture(self.tmp)
        self.out = self.root / "KB" / "output"
        g, _ = kbgraph.build(self.root, self.out, quiet=True)
        (self.out / "kb-graph.json").write_text(json.dumps(g), encoding="utf-8")
        self.graph = kbquery.Graph(self.root)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_connect_returns_path_with_prose(self):
        res = kbquery.verb_connect(self.graph, "first", "second", 5)
        self.assertEqual(res["hops"], 1)
        self.assertIn("the relation prose", res["paths"][0]["steps"][0])

    def test_connect_reports_honest_failure(self):
        """No path must say so, never invent one."""
        iso = self.root / "KB" / "wiki" / "beta" / "isolated.md"
        iso.write_text("# Isolated\n\n**Category:** beta\n\n## Core Claim\nAlone.\n", encoding="utf-8")
        g, _ = kbgraph.build(self.root, self.out, quiet=True)
        (self.out / "kb-graph.json").write_text(json.dumps(g), encoding="utf-8")
        res = kbquery.verb_connect(kbquery.Graph(self.root), "isolated", "second", 5)
        self.assertEqual(res["paths"], [])
        self.assertIn("no path", res["note"])

    def test_provenance_both_directions(self):
        fwd = kbquery.verb_provenance(self.graph, "first")
        self.assertEqual([s["name"] for s in fwd["sources"]], ["source-one.md"])
        rev = kbquery.verb_provenance(self.graph, "never-cited.md")
        self.assertEqual(rev["direction"], "raw->articles")
        self.assertIn("NEVER COMPILED", rev["note"])

    def test_provenance_flags_sourceless_article(self):
        res = kbquery.verb_provenance(self.graph, "third")
        self.assertIn("NO SOURCE RECORDED", res["note"])

    def test_search_finds_body_only_text(self):
        """The whole point of the BM25 layer: text that appears in no title or claim."""
        res = kbquery.verb_search(self.root, self.graph, "zebrafish", 5)
        self.assertEqual([r["stem"] for r in res["results"]][:1], ["first"])

    def test_gaps_counts_uncompiled(self):
        res = kbquery.verb_gaps(self.graph, self.root, 10)
        self.assertEqual(res["uncompiled_raw"]["count"], 1)

    def test_query_does_not_mutate_kb(self):
        before = tree_digest(self.root / "KB" / "wiki")
        raw_before = tree_digest(self.root / "KB" / "RAW")
        kbquery.verb_search(self.root, self.graph, "zebrafish claim", 5)
        kbquery.verb_connect(self.graph, "first", "second", 5)
        kbquery.verb_provenance(self.graph, "first")
        kbquery.verb_gaps(self.graph, self.root, 5)
        kbquery.verb_themes(self.root, self.graph, "anything")
        self.assertEqual(tree_digest(self.root / "KB" / "wiki"), before)
        self.assertEqual(tree_digest(self.root / "KB" / "RAW"), raw_before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
