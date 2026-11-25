#!/usr/bin/env python3
"""Reject unmasked author, committer and annotated-tag identities before public pushes."""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# This existing public history predates the guard. Moving this boundary requires review.
PUBLIC_BASE = "017f560e9aca6bca4c7352d866e442a061038fde"
OID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
MASKED = re.compile(rb"(?:[A-Za-z0-9_+.-]+@users\.noreply\.github\.com|noreply@github\.com)", re.I)


def git(*args):
    proc = subprocess.run(["git", "--no-replace-objects", *args], capture_output=True)
    if proc.returncode:
        raise ValueError("Git object unavailable; fetch complete history and retry")
    return proc.stdout


def object_id(value):
    if not isinstance(value, str) or not OID.fullmatch(value):
        raise ValueError("invalid Git object ID")
    return value


def check_headers(data, roles, oid):
    lines = data.split(b"\n\n", 1)[0].splitlines()
    for role in roles:
        entries = [line for line in lines if line.startswith(role + b" ")]
        if len(entries) != 1:
            raise ValueError("missing or duplicate identity on object " + oid[:12])
        match = re.fullmatch(rb".* <([^<>]*)> [0-9]+ [+-][0-9]{4}", entries[0])
        if not match or not MASKED.fullmatch(match.group(1)):
            raise ValueError("use a GitHub noreply address for " + role.decode() + " on object " + oid[:12])


def inspect_updates(updates):
    commits = set()
    tags = set()
    for new, old in updates:
        new, old = object_id(new), object_id(old)
        if not new.strip("0"):
            continue
        tip = new
        kind = git("cat-file", "-t", tip).strip()
        while kind == b"tag":
            data = git("cat-file", "tag", tip)
            if tip not in tags:
                check_headers(data, (b"tagger",), tip)
                tags.add(tip)
            tip = object_id(data.splitlines()[0].removeprefix(b"object ").decode())
            kind = git("cat-file", "-t", tip).strip()
        if kind != b"commit":
            continue
        revs = [tip, "^" + PUBLIC_BASE]
        if old.strip("0"):
            old_type = git("cat-file", "-t", old + "^{}").strip()
            if old_type == b"commit":
                revs.append("^" + old + "^{}")
        commits.update(git("rev-list", *revs).decode().splitlines())
    for commit in sorted(commits):
        check_headers(git("cat-file", "commit", commit), (b"author", b"committer"), commit)
    return len(commits), len(tags)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", type=Path, help="GitHub Actions push or pull request event")
    args = parser.parse_args()
    if args.event:
        event = json.loads(args.event.read_text())
        if "pull_request" in event:
            pr = event["pull_request"]
            updates = [(pr["head"]["sha"], pr["base"]["sha"])]
        else:
            # For annotated tag pushes the event SHA may be peeled. Inspect the actual tag object.
            ref = event["ref"]
            new = event["after"]
            if ref.startswith("refs/tags/") and new.strip("0"):
                new = git("show-ref", "--verify", "--hash", ref).decode().strip()
            updates = [(new, event["before"])]
    else:
        updates = []
        for line in sys.stdin:
            local_ref, local_id, remote_ref, remote_id = line.split()
            updates.append((local_id, remote_id))
    commits, tags = inspect_updates(updates)
    print("Public metadata checked: %d new commits, %d annotated tags" % (commits, tags))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError) as exc:
        sys.exit(str(exc))
