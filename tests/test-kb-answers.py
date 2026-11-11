import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))
import kb_testkit


class Answers(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.tmp = Path(temp.name)
        self.root = kb_testkit.fixture(self.tmp / "brain", regressions=True)
        self.command("write", "seal")
        self.answer = self.tmp / "reply.md"
        self.answer.write_text("The meeting is Tuesday.")
        self.propose("The meeting is Tuesday.", False)
        self.page = self.root / "KB/wiki/alpha/meeting.md"

    def command(self, verb, *args, rc=0):
        cmd = [str(TOOLS.parent / "bin/kb"), verb]
        if verb == "answers":
            cmd += ["--root", str(self.root), *args]
        else:
            cmd += [*args, "--root", str(self.root), "--json"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(r.returncode, rc, r.stdout + r.stderr)
        return json.loads(r.stdout) if r.stdout else None

    def propose(self, claim, replace, extra=""):
        body = self.tmp / "draft.md"
        body.write_text("# Meeting\n\n## Core Claim\n" + claim + "\n" + extra)
        flags = ["--supersedes", "wiki:meeting"] if replace else []
        pid = self.command("write", "put", "--kind", "article", "--type", "fact", "--agent", "RESEARCHER",
                           "--slug", "meeting", "--category", "alpha", "--confidence", "high",
                           "--source-ref", "owner:2026-01-01", "--body-file", str(body), *flags)["id"]
        self.command("write", "land", pid, "--endorsed-by", "owner")

    def capture(self, name):
        line = self.page.read_text().splitlines().index("The meeting is Tuesday.") + 1
        obj = self.command("answers", "capture", "--question", "When?", "--answer-file", str(self.answer),
                           "--cite", "alpha/meeting.md", str(line), str(line))
        path = self.tmp / name
        path.write_text(json.dumps(obj))
        return path

    def test_capture_revision_and_replacement(self):
        before = kb_testkit.tree_digest(self.root / "KB")
        receipt = self.capture("first.answer.json")
        self.assertEqual(self.command("answers", "check", str(receipt))["status"], "current")
        self.assertEqual(before, kb_testkit.tree_digest(self.root / "KB"))
        self.propose("The meeting is Tuesday.", True, "\n## Notes\nBring a notebook.\n")
        self.assertEqual(self.command("answers", "check", str(receipt), rc=1)["status"], "review_context")
        self.propose("The meeting is Thursday.", True)
        out = self.command("answers", "check", str(receipt), rc=1)
        self.assertEqual(out["citations"][0]["status"], "missing")

    def test_audit_and_queue_include_drift_and_bad_files(self):
        self.capture("one.answer.json")
        self.answer.write_text("Tuesday, according to the meeting note.")
        self.capture("two.answer.json")
        self.page.write_text(self.page.read_text()+"direct edit\n")
        (self.tmp / "bad.answer.json").write_text("{")
        audit = self.command("answers", "audit", str(self.tmp), rc=1)
        self.assertEqual(audit["counts"], {"invalid": 1, "review_citation": 2})
        result = self.command("answers", "queue", str(self.tmp), rc=1)
        self.assertEqual(result["review"][0]["page"], "alpha/meeting.md")
        self.assertEqual(len(result["review"][0]["answers"]), 2)
        self.assertIsNone(result["review"][1]["page"])

    def test_tampered_receipt_and_outside_page(self):
        path = self.capture("one.answer.json")
        obj = json.loads(path.read_text())
        obj["answer"] += " Changed."
        path.write_text(json.dumps(obj))
        self.command("answers", "check", str(path), rc=2)
        self.command("answers", "capture", "--question", "When?", "--answer-file", str(self.answer),
                     "--cite", "../kb.json", "1", "1", rc=2)


if __name__ == "__main__":
    unittest.main()
