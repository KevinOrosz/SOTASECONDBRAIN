#!/usr/bin/env python3
"""Regression tests for tools/kb-autolink.py (stdlib only)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "kb-autolink.py"
SPEC = importlib.util.spec_from_file_location("kb_autolink", SCRIPT)
assert SPEC and SPEC.loader
KB_AUTOLINK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(KB_AUTOLINK)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


class KbAutolinkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.wiki = Path(self.temp.name) / "wiki"
        write(self.wiki / "alpha" / "_index.md", "# Alpha\n[[index-gap]]\n")
        write(
            self.wiki / "alpha" / "source.md",
            "# Source\n**Sources:** [[RAW/source.md]]\n"
            "[[known]] [[beta/known|Known]] [[known.md]] [[beta/_index]]\n"
            "[[missing-concept]] [[Missing Concept]] [[Known#Part]] ![[asset]]\n"
            "[[../escape]] [[UpperCase]] [[RAW/other.md]] [[https://example.com]]\n",
        )
        write(
            self.wiki / "alpha" / "second.md",
            "# Second\n**Sources:** [[RAW/second.md]]\n[[missing-concept]] [[multi]]\n",
        )
        write(self.wiki / "beta" / "_index.md", "# Beta\n")
        write(self.wiki / "beta" / "known.md", "# Known\n**Sources:** [[RAW/known.md]]\n")
        write(self.wiki / "gamma" / "other.md", "# Other\n**Sources:** [[RAW/other.md]]\n[[multi]]\n")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_normalization_findings_and_deduplication(self) -> None:
        before = tree_digest(self.wiki)
        report = KB_AUTOLINK.scan(self.wiki)
        self.assertEqual(before, tree_digest(self.wiki))
        self.assertEqual(report["article_count"], 4)
        self.assertEqual(report["resolved_occurrences"], 4)
        self.assertEqual(report["excluded"]["raw"], 5)
        self.assertEqual(report["excluded"]["http"], 1)

        strict = {item["normalized"]: item for item in report["strict"]}
        self.assertEqual(set(strict), {"missing-concept"})
        self.assertEqual(len(strict["missing-concept"]["locations"]), 2)
        self.assertEqual(strict["missing-concept"]["raw_provenance_count"], 2)

        loose = {item["normalized"] for item in report["loose"]}
        self.assertEqual(loose, {"Missing Concept"})
        reasons = {item["normalized"]: item["reason"] for item in report["blocked"]}
        self.assertEqual(reasons["multi"], "ambiguous-category")
        self.assertEqual(reasons["index-gap"], "index-only-provenance")
        self.assertEqual(reasons["Known#Part"], "fragment")
        self.assertEqual(reasons["asset"], "embed")
        self.assertEqual(reasons["../escape"], "path-traversal")
        self.assertEqual(reasons["UpperCase"], "invalid-stem")

    def test_json_cli_and_apply_refusal_write_nothing(self) -> None:
        before = tree_digest(self.wiki)
        run = subprocess.run(
            [sys.executable, str(SCRIPT), "--wiki", str(self.wiki), "--json"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout)["mode"], "report-only")
        refused = subprocess.run(
            [sys.executable, str(SCRIPT), "--wiki", str(self.wiki), "--apply"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(refused.returncode, 2)
        self.assertIn("BLOCKED", refused.stderr)
        self.assertEqual(before, tree_digest(self.wiki))

    @unittest.skipUnless((ROOT / "KB" / "wiki").is_dir(), "no instance yet: run ./bootstrap.sh")
    def test_live_corpus_is_resolved_and_unchanged(self) -> None:
        wiki = ROOT / "KB" / "wiki"
        before = tree_digest(wiki)
        report = KB_AUTOLINK.scan(wiki)
        self.assertEqual(report["unique_strict"], 0)
        self.assertEqual(report["unique_loose"], 0)
        self.assertEqual(report["unique_blocked"], 0)
        self.assertEqual(before, tree_digest(wiki))


if __name__ == "__main__":
    unittest.main(verbosity=2)
