"""Recovery commands exercised on disposable brains."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))
import kb_testkit


class Backups(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = kb_testkit.fixture(self.tmp / "source", regressions=True)
        self.archive = self.tmp / "backup.zip"

    def cli(self, *args, rc=0):
        p = subprocess.run([str(TOOLS.parent / "bin/kb"), "backup", "--root", str(self.root), *map(str, args)],
                           text=True, capture_output=True)
        self.assertEqual(p.returncode, rc, p.stdout + p.stderr)
        return json.loads(p.stdout) if p.stdout else p.stderr

    def test_roundtrip_preserves_instance_and_query(self):
        (self.root / "KB/RAW/empty").mkdir()
        self.assertTrue(self.cli("create", self.archive)["payload_verified"])
        inventory = self.cli("inspect", self.archive)
        self.assertFalse(inventory["payload_verified"])
        self.assertIn("evals/regressions.jsonl", inventory["inventory"]["files"])
        self.assertIn("KB/RAW/empty", inventory["inventory"]["directories"])
        self.assertTrue(self.cli("verify", self.archive)["payload_verified"])
        dest = self.tmp / "recovered"
        self.cli("restore", self.archive, dest)
        for folder in ("KB", "evals", "agents"):
            self.assertEqual(kb_testkit.tree_digest(dest / folder), kb_testkit.tree_digest(self.root / folder))
        self.assertTrue((dest / "KB/RAW/empty").is_dir())
        evaluator = kb_testkit.load("kb-eval.py")
        self.assertEqual(evaluator.ranked(dest, "zebrafish")["results"][0]["stem"], "first")
        self.cli("restore", self.archive, dest, rc=1)
        self.cli("create", self.archive, rc=1)

    def test_restored_ledger_and_objects_can_undo_a_supersession(self):
        def write(root, *args):
            proc = subprocess.run([sys.executable, str(TOOLS / "kb-write.py"), *args, "--root", str(root), "--json"],
                                  text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            return json.loads(proc.stdout)
        write(self.root, "seal")
        draft = self.tmp / "draft.md"
        page = Path("KB/wiki/alpha/day.md")
        for day in ("Monday", "Tuesday"):
            draft.write_text("# Day\n\n## Core Claim\nThe workshop is on " + day + ".\n")
            flags = ["--supersedes", "wiki:day"] if day == "Tuesday" else []
            proposal = write(self.root, "put", "--agent", "RESEARCHER", "--kind", "article", "--type", "fact",
                             "--slug", "day", "--category", "alpha", "--confidence", "high",
                             "--source-ref", "owner:2026-01-01", "--body-file", str(draft), *flags)
            write(self.root, "land", proposal["id"], "--endorsed-by", "owner")
            if day == "Monday":
                original = (self.root / page).read_bytes()
        self.cli("create", self.archive)
        dest = self.tmp / "recovered"
        self.cli("restore", self.archive, dest)
        write(dest, "unland", proposal["id"], "--reason", "recovery drill", "--endorsed-by", "owner")
        self.assertEqual((dest / page).read_bytes(), original)
        self.assertIn("Tuesday", (self.root / page).read_text())

    def test_wrong_payload_hash_and_cleanup(self):
        self.cli("create", self.archive)
        bad = self.tmp / "changed.zip"
        with zipfile.ZipFile(self.archive) as src, zipfile.ZipFile(bad, "w") as dst:
            for name in src.namelist():
                data = src.read(name)
                if name == "manifest.json":
                    m = json.loads(data)
                    next(iter(m["files"].values()))["sha256"] = "0"*64
                    data = json.dumps(m)
                dst.writestr(name, data)
        self.assertFalse(self.cli("inspect", bad)["payload_verified"])
        self.assertIn("hash mismatch", self.cli("verify", bad, rc=1))
        dest = self.tmp / "failed"
        self.cli("restore", bad, dest, rc=1)
        self.assertFalse(dest.exists())

    def test_refuses_unsafe_paths_links_and_active_writer(self):
        bad = self.tmp / "unsafe.zip"
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr("KB/../outside", b"x")
            z.writestr("manifest.json", json.dumps({"format":"kb-backup/1", "directories":["KB","KB/wiki"],
                "files":{"KB/../outside":{"sha256":hashlib.sha256(b"x").hexdigest(), "size":1}}}))
        self.cli("restore", bad, self.tmp / "destination", rc=1)
        self.assertFalse((self.tmp / "outside").exists())
        inbox = self.root / "KB/inbox"
        inbox.mkdir(exist_ok=True)
        (inbox / ".lock").touch()
        self.cli("create", self.archive, rc=1)
        (inbox / ".lock").unlink()
        (self.root / "KB/RAW/external").symlink_to(self.tmp)
        self.cli("create", self.archive, rc=1)
        self.assertFalse(self.archive.exists())


if __name__ == "__main__":
    unittest.main()
