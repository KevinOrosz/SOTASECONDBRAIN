"""Public metadata checks over disposable local commits and annotated tags."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check-git-privacy.py"
spec = importlib.util.spec_from_file_location("git_privacy", SCRIPT)
privacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(privacy)
MASKED = "123+tester@users.noreply.github.com"
UNMASKED = "fixture@example.invalid"
ZERO = "0" * 40


class GitPrivacy(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.git("init", "-q")
        base = self.commit(UNMASKED)
        self.addCleanup(patch.stopall)
        patch.object(privacy, "PUBLIC_BASE", base).start()
        patch.object(privacy, "git", lambda *args: self.git("--no-replace-objects", *args)).start()

    def git(self, *args, email=MASKED):
        env = dict(os.environ, GIT_AUTHOR_NAME="Tester", GIT_AUTHOR_EMAIL=email,
                   GIT_COMMITTER_NAME="Tester", GIT_COMMITTER_EMAIL=email,
                   GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
        return subprocess.check_output(["git", "-C", str(self.root), *args], env=env)

    def commit(self, email):
        self.git("-c", "commit.gpgsign=false", "commit", "--allow-empty", "-qm", "fixture", email=email)
        return self.git("rev-parse", "HEAD").decode().strip()

    def test_entire_new_history_and_explicit_update(self):
        first = self.commit(MASKED)
        self.assertEqual(privacy.inspect_updates([(first, ZERO)]), (1, 0))
        self.commit(UNMASKED)
        tip = self.commit(MASKED)
        for old in (first, ZERO):
            with self.assertRaisesRegex(ValueError, "noreply") as result:
                privacy.inspect_updates([(tip, old)])
            self.assertNotIn(UNMASKED, str(result.exception))

    def test_tags_check_tagger_even_for_existing_commit(self):
        self.git("-c", "tag.gpgSign=false", "tag", "-a", "safe", "-m", "fixture")
        self.git("-c", "tag.gpgSign=false", "tag", "-a", "private", "-m", "fixture", email=UNMASKED)
        safe, private = [self.git("rev-parse", name).decode().strip() for name in ("safe", "private")]
        self.assertEqual(privacy.inspect_updates([(safe, ZERO)]), (0, 1))
        with self.assertRaisesRegex(ValueError, "tagger"):
            privacy.inspect_updates([(private, ZERO)])
        self.assertEqual(privacy.inspect_updates([(ZERO, private)]), (0, 0))


if __name__ == "__main__":
    unittest.main()
