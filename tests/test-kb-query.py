#!/usr/bin/env python3
"""Focused freshness regressions for tools/kb-query.py."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


TOOL = Path(__file__).resolve().parent.parent / "tools" / "kb-query.py"
SPEC = importlib.util.spec_from_file_location("command_kb_query", TOOL)
assert SPEC and SPEC.loader
QUERY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QUERY)


class QueryFreshnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.wiki = self.root / "KB" / "wiki" / "notes"
        self.output = self.root / "KB" / "output"
        self.wiki.mkdir(parents=True)
        self.output.mkdir(parents=True)
        self.article = self.wiki / "alpha.md"
        self.article.write_text("# Alpha\n", encoding="utf-8")
        self.index_path = self.output / "kb-index.json"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _index(self) -> dict:
        digest = hashlib.sha256(self.article.read_bytes()).hexdigest()
        return {
            "articles": [
                {"path": "KB/wiki/notes/alpha.md", "content_hash": digest}
            ]
        }

    def test_matching_content_hash_is_fresh(self) -> None:
        index = self._index()
        self.index_path.write_text(json.dumps(index), encoding="utf-8")
        self.assertEqual(QUERY.staleness_note(index, self.root, self.index_path), "")

    def test_same_day_edit_warns_even_when_index_is_touched_newer(self) -> None:
        index = self._index()
        self.index_path.write_text(json.dumps(index), encoding="utf-8")
        self.article.write_text("# Alpha\n\nChanged.\n", encoding="utf-8")
        newer = self.article.stat().st_mtime_ns + 2_000_000_000
        os.utime(self.index_path, ns=(newer, newer))
        note = QUERY.staleness_note(index, self.root, self.index_path)
        self.assertIn("index content drift", note)


if __name__ == "__main__":
    unittest.main()
