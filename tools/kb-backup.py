#!/usr/bin/env python3
"""Create, inspect, verify and restore local instance-data backups."""
import argparse
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import sys
import tempfile
import unicodedata
import zipfile
import zlib


ROOTS = ("KB", "evals", "agents")
SUPPORT = ("skills/REGISTRY.md", "config/router.json")
SUPPORT_NAMES = set(SUPPORT) | {str(Path(p).parent) for p in SUPPORT}
MANIFEST = "manifest.json"
FORMAT = "kb-backup/1"
CHUNK = 1024 * 1024
MAX_MANIFEST = 32 * CHUNK
MAX_BYTES = 64 * 1024**3
MAX_ENTRIES = 100000


def fail(message):
    raise ValueError(message)


def name_ok(name):
    if not isinstance(name, str) or not name or "\\" in name or any(ord(c) < 32 for c in name):
        fail("invalid archive path")
    path = PurePosixPath(name)
    if name != path.as_posix() or not path.parts or (path.parts[0] not in ROOTS and name not in SUPPORT_NAMES) or ".." in path.parts:
        fail("unexpected archive path: " + name)
    if name == "KB/inbox/.lock" or (name.startswith("KB/inbox/_ops/") and name.endswith(".json")):
        fail("unfinished write operation; recover the instance before creating a backup")


def inventory(root):
    if not (root / "KB/wiki").is_dir():
        fail("no initialized wiki")
    entries = {}
    def visit(path):
        name = path.relative_to(root).as_posix()
        name_ok(name)
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            entries[name] = None
            for child in sorted(path.iterdir()):
                visit(child)
        elif stat.S_ISREG(info.st_mode):
            entries[name] = info.st_size
        else:
            fail("links and special files are unsupported: " + name)
    for name in ROOTS:
        if os.path.lexists(root / name):
            visit(root / name)
    for name in SUPPORT:
        path = root / name
        if path.parent.is_symlink():
            fail("symlinked support directory: " + str(path.parent))
        if os.path.lexists(path):
            if not stat.S_ISREG(path.lstat().st_mode):
                fail("expected regular support file: " + name)
            entries[str(Path(name).parent)] = None
            entries[name] = path.stat().st_size
    return entries


def transfer(src, dest=None, limit=MAX_BYTES):
    digest = hashlib.sha256()
    size = 0
    while True:
        block = src.read(CHUNK)
        if not block:
            break
        size += len(block)
        if size > limit:
            fail("file exceeds declared size")
        digest.update(block)
        if dest is not None:
            dest.write(block)
    return size, digest.hexdigest()


def local_file(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        fail("source changed to a special file")
    return os.fdopen(fd, "rb")


def create(root, output):
    root = root.resolve()
    if any(output.resolve().is_relative_to(root / n) for n in ROOTS) or output.resolve() in {root / n for n in SUPPORT}:
        fail("choose an archive location outside the backed-up directories")
    if os.path.lexists(output):
        fail("archive destination exists")
    entries = inventory(root)
    if len(entries) > MAX_ENTRIES or sum(n or 0 for n in entries.values()) > MAX_BYTES:
        fail("instance exceeds backup size limits")
    manifest = {"format": FORMAT, "directories": [], "files": {}}
    with tempfile.TemporaryDirectory(dir=output.parent, prefix=".kb-backup-") as temp:
        archive = Path(temp) / "backup.zip"
        with archive.open("xb") as stream, zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for name, size in entries.items():
                if size is None:
                    manifest["directories"].append(name)
                    continue
                with local_file(root / name) as src, z.open(name, "w", force_zip64=True) as dst:
                    actual, digest = transfer(src, dst, size)
                if actual != size:
                    fail("instance changed during backup")
                manifest["files"][name] = {"size": size, "sha256": digest}
            z.writestr(MANIFEST, json.dumps(manifest, sort_keys=True, ensure_ascii=False))
        with zipfile.ZipFile(archive) as z:
            checked = catalog(z)
            check_bytes(z, checked)
        for name, row in manifest["files"].items():
            with local_file(root / name) as src:
                if transfer(src, limit=row["size"]) != (row["size"], row["sha256"]):
                    fail("source changed during backup: " + name)
        if inventory(root) != entries:
            fail("instance tree changed during backup")
        archive.chmod(0o600)
        os.link(archive, output)  # Atomic publication, including a concurrent destination collision.
    return summary(manifest, True)


def catalog(z):
    infos = z.infolist()
    if len(infos) > MAX_ENTRIES + 1 or len({i.filename for i in infos}) != len(infos):
        fail("too many or duplicate archive members")
    if MANIFEST not in z.namelist() or z.getinfo(MANIFEST).file_size > MAX_MANIFEST:
        fail("missing or oversized backup manifest")
    for info in infos:
        kind = stat.S_IFMT(info.external_attr >> 16)
        if kind not in (0, stat.S_IFREG) or info.is_dir() or info.flag_bits & 1:
            fail("non-regular or encrypted archive member")
    m = json.loads(z.read(MANIFEST))
    if not isinstance(m, dict) or m.get("format") != FORMAT:
        fail("unknown backup format")
    dirs, files = m.get("directories"), m.get("files")
    if not isinstance(dirs, list) or not isinstance(files, dict) or len(dirs)+len(files) > MAX_ENTRIES:
        fail("invalid manifest inventory")
    names = dirs + list(files)
    for name in names:
        name_ok(name)
    if len({unicodedata.normalize("NFC", n).casefold() for n in names}) != len(names):
        fail("duplicate or nonportable archive paths")
    parents = set(dirs)
    if ("KB/wiki" not in parents or any(n in files for n in ROOTS)
            or any(n in parents for n in SUPPORT) or any(str(Path(n).parent) in files for n in SUPPORT)):
        fail("invalid instance layout")
    if any("/" in n and str(PurePosixPath(n).parent) not in parents for n in names):
        fail("missing parent directory")
    if set(files) | {MANIFEST} != set(z.namelist()):
        fail("archive and manifest inventories differ")
    total = 0
    for name, row in files.items():
        if not isinstance(row, dict) or type(row.get("size")) != int or row["size"] != z.getinfo(name).file_size:
            fail("file size mismatch: " + name)
        digest = row.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            fail("invalid SHA-256: " + name)
        total += row["size"]
    if total > MAX_BYTES:
        fail("backup exceeds uncompressed size limit")
    return m


def check_bytes(z, m, dest=None):
    for name, row in m["files"].items():
        output = (dest / name).open("xb") if dest else nullcontext(None)
        with output as dst, z.open(name) as src:
            if transfer(src, dst, row["size"]) != (row["size"], row["sha256"]):
                fail("content hash mismatch: " + name)


def summary(m, verified):
    return {"format": FORMAT, "files": len(m["files"]), "directories": len(m["directories"]),
            "bytes": sum(r["size"] for r in m["files"].values()), "payload_verified": verified}


def restore(z, m, dest):
    dest.mkdir(mode=0o700)  # Exclusive: refuse even an existing empty directory.
    try:
        for name in sorted(m["directories"], key=lambda n: n.count("/")):
            (dest / name).mkdir(mode=0o700)
        check_bytes(z, m, dest)
    except BaseException:
        shutil.rmtree(dest)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    commands = parser.add_subparsers(dest="command", required=True)
    for cmd in ("create", "inspect", "verify", "restore"):
        p = commands.add_parser(cmd)
        p.add_argument("archive", type=Path)
        if cmd == "restore":
            p.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "create":
            result = create(args.root, args.archive)
        else:
            with zipfile.ZipFile(args.archive) as z:
                m = catalog(z)
                if args.command == "restore":
                    restore(z, m, args.destination)
                elif args.command == "verify":
                    check_bytes(z, m)
                result = summary(m, args.command != "inspect")
                if args.command == "inspect":
                    result["inventory"] = m
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError, EOFError, zlib.error) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
