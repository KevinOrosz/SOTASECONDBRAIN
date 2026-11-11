#!/usr/bin/env python3
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))
import kb_testkit


class Evidence(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = kb_testkit.fixture(Path(tmp.name), regressions=True)
        self.raw = self.root / "KB/RAW"

    def cli(self, *args, code=0):
        result = subprocess.run([str(TOOLS.parent / "bin/kb"), "evidence", "--root", str(self.root), *args],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, code, result.stderr + result.stdout)
        return json.loads(result.stdout) if result.stdout else None

    def test_diff_and_quote_lifecycle(self):
        (self.raw / "old.md").write_bytes(b"Opening\nDue Friday.\n")
        revision = self.raw / "new.md"
        revision.write_bytes(b"Note\nOpening\nDue Friday.")
        delta = self.cli("diff", "old.md", "new.md")
        self.assertNotEqual(delta["old_sha256"], delta["new_sha256"])
        self.assertEqual(delta["edits"][0]["added"], ["Note\n"])
        receipt = self.root / "pin.json"
        receipt.write_text(json.dumps(self.cli("pin", "old.md", "2", "2")))
        self.assertEqual(self.cli("check", str(receipt))["status"], "unchanged")
        self.assertEqual(self.cli("check", str(receipt), "--revision", "new.md")["matching_start_lines"], [3])
        revision.write_text("Due Friday.\nDue Friday.\n")
        self.assertEqual(self.cli("check", str(receipt), "--revision", "new.md", code=1)["status"], "ambiguous")
        revision.write_text("Due Monday.\n")
        self.assertEqual(self.cli("check", str(receipt), "--revision", "new.md", code=1)["status"], "missing")
        self.cli("pin", "../kb.json", "1", "1", code=2)

    def test_impact_follows_reverse_dependencies_and_terminates_on_cycle(self):
        wiki = self.root / "KB/wiki/alpha"
        second = wiki / "second.md"
        second.write_text(second.read_text().replace("**Type:** article", "**Type:** article\n**Depends-On:** first"))
        suite = self.root / "evals/regressions.jsonl"
        cases = [json.loads(line) for line in suite.read_text().splitlines()]
        next(c for c in cases if c["kind"] == "artifact")["targets"] = ["KB/wiki/alpha/*.md"]
        suite.write_text("".join(json.dumps(c) + "\n" for c in cases))
        report = self.cli("impact", "source-two.md")
        chains = {Path(p["path"]).stem: p["dependency_chain"] for p in report["pages"]}
        self.assertEqual(chains["second"], ["second"])
        self.assertEqual(chains["first"], ["second", "first"])
        self.assertEqual({c["id"] for c in report["linked_cases"]}, {"r-0002", "r-0003"})
        (self.raw / "source-two.md").unlink()
        self.assertFalse(self.cli("impact", "source-two.md")["present"])

    def test_rehearsal_predicts_search_without_mutating_live_brain(self):
        writer = TOOLS / "kb-write.py"
        def write(*args):
            proc = subprocess.run([sys.executable, str(writer), *args, "--root", str(self.root), "--json"],
                                  text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            return json.loads(proc.stdout)
        write("seal")
        draft = self.root / "fact.md"
        draft.write_text("# Launch site\n\n## Core Claim\nThe launch site is Quicksilver.\n")
        pid = write("put", "--kind", "article", "--type", "fact", "--agent", "RESEARCHER", "--slug", "launch-site",
                    "--category", "alpha", "--confidence", "high", "--source-ref", "owner:2026-01-01",
                    "--body-file", str(draft))["id"]
        baseline = kb_testkit.tree_digest(self.root / "KB")
        result = self.cli("rehearse", pid, "quicksilver")
        self.assertEqual(result["before"], [])
        self.assertEqual(result["after"], ["launch-site"])
        self.assertEqual(kb_testkit.tree_digest(self.root / "KB"), baseline)
        write("land", pid, "--endorsed-by", "owner")
        mod = kb_testkit.load("kb-eval.py")
        actual = [h["stem"] for h in mod.ranked(self.root, "quicksilver", k=8)["results"]]
        self.assertEqual(result["after"], actual)


if __name__ == "__main__":
    unittest.main()
