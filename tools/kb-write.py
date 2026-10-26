#!/usr/bin/env python3
"""kb-write.py — the one write path from an agent into the KB: inbox proposals + a hash ledger.

Usage:  python3 tools/kb-write.py VERB [--root R] [--json] ...
  put       --agent A --kind article|gap --slug S --confidence C --source-ref REF... --body-file F
            [--type T --category CAT --supersedes wiki:STEM --resolves ID --gap-kind K --target X
             --query Q --origin O]
  link      --agent A --from STEM --to STEM --type LINK_TYPE --prose P --source-ref REF... --confidence C
            [--origin O]
  withdraw  ID --reason R --by A                      the proposing agent pulls its own open proposal
  reject    ID --reason R --by OWNER                  the owner declines an open proposal (stamps decided_at)
  resolve   ID --reason R --by OWNER                  the owner closes an open gap without a land
  list      [--state S] [--origin PREFIX] [--since YYYY-MM-DD]
  seal                                                first snapshot: sha256 of every KB/wiki/**/*.md
  seal --reseal --reason R --endorsed-by OWNER        one reseal row re-basing every drifted wiki path
  land ID... --endorsed-by OWNER [--dry-run]          the only path that writes KB/wiki (see land below)
  land --adopt PATH... --reason R --endorsed-by OWNER one adopt row recording hand edits to wiki paths
  unland ID --reason R --endorsed-by OWNER            undo one land and reopen its proposal
Exit:   0 ok · 1 usage or IO · 2 contract violation · 3 post-check failed, rolled back · 4 conflict
        (duplicate open proposal, seal exists, existing stem, stale base_hash, changed since land) · 5 lock held
        · 9 simulated crash (KB_WRITE_FAULT test seam only; the next invocation recovers)
JSON:   success {"ok":true,"verb","id","path","ledger_seq"} · error {"error","detail"}
        · list {"ok":true,"verb":"list","items":[{... "origin","proposed_at"}]}

Canonical home (spec §1.1) of the inbox schema, verb set, ledger enum and write allowlist: this
docstring + the constants below. kb-lint WP1/WP2 import them; nothing else redefines them.

Layout      KB/inbox/{AGENT}/{YYYY-MM-DD}-{slug}.md — AGENT = a registered agent id or the owner id
            (both from KB/kb.json, see config()). Slug ^[a-z0-9]+(-[a-z0-9]+)*$, max 60 chars; a taken name gets -2, -3, ...
            Reserved: _seal.json, _ledger.jsonl, .lock, _corrections/, _objects/, _ops/. Anything else
            is a WP2 stray.
Inbox file  '---', flat YAML subset ('key: value' per line; lists and quoted scalars are JSON), '---',
            body. Keys = COMMON_KEYS + KIND_KEYS[kind] + TOOL_KEYS; any other key is a WP2 violation.
source_refs raw:<path under KB/RAW> · wiki:<known target> · output:<path under output/ or KB/output/>
            · owner:<ISO date> · query:<sha12> (missing-gaps only). New-stem articles need at least
            one raw: or owner:; a supersede inherits the base page's Sources.
dedupe_key  sha256(kind|gap_kind|target|norm(title))[:12]. target = category/stem (article), --target
            (gap), from>to (link). title = body H1, else slug (article, gap); link_type (link).
            norm = lowercase, non-alphanumeric runs -> one space. A hit on an open proposal exits 4.
Ledger      KB/inbox/_ledger.jsonl, append-only, never git-reverted. seq runs 1, 2, 3 ... One row per
            event: {"seq","ts","event","id","actor","origin","files","prior","resolved","reason"};
            files/prior map root-relative paths to sha256, null = absent. A KB/wiki path's expected
            hash is its last ledger files entry, else its _seal.json entry (WP1). Rows are never edited;
            only recover truncates, and only the rows an unfinished op appended. The put row is an
            inbox file's provenance trace; tools never write run-log rows. A land row whose origin is
            correction:CID also carries "hook_skipped" when tools/kb-correct.py is absent.
Writes      only through _write(root, rel, data, verb), checked against ALLOW; tmp file + os.replace,
            data None deletes, ledger appends fsync'd; every mutation holds KB/inbox/.lock (O_CREAT|O_EXCL).
land        Preflight (exit 2 unless): open, not a gap, seal present, WP1 clean on every staged wiki
            path, the H1 header parses (kb-lint read_meta), body >= 100 words (outside 200-400 WARNs),
            every [[link]] resolves. Exit 4: existing stem, stale base_hash. Stage: the page with
            Type + Confidence + Provenance set by set_run (Provenance replaced, never appended; a
            supersede with no Sources line inherits the base page's); category _index row
            '| [[stem]] | claim<=300 |' + Articles + Updated; master _index Status + category row +
            Updated + Recent Updates; the catalog page's Articles (KB/kb.json catalog, skipped while absent). Supersedes skip every count bump.
            A link appends '- [[to]] — prose' under ## Connections (else ## Related, else a new
            Connections before Open Questions) and one KB/output/kb-edge-types.json row.
            Post-check: kb-index + kb-graph rebuild, kb-graph --check 0, autolink unresolved <=
            preflight, kb-eval --check 0 with recall@6 >= preflight, kb-eval --regressions
            the regressions file (KB/kb.json regressions) 0 when it exists, kb-lint 0 FAIL. Any miss restores
            every captured byte and exits 3; env KB_WRITE_FAULT=postcheck forces one (test seam, read
            only in postcheck). Then: land row, a resolve row per gap, proposal state landed. A
            correction:CID origin calls tools/kb-correct.py landed CID --ledger-seq N --root R after
            the row, inside the op: a failing hook rolls the whole land back (exit 3), so no correction
            enters the wiki without its regression case. --dry-run prints a unified diff per staged
            file + one JSON summary with the post-check plan, writes nothing.
unland      Per file the land row wrote: untouched since and its prior bytes known (null, the object
            _objects/<sha256>, else a commit in git whose sha256 matches) -> exact restore; else the
            page exits 4 and an index, catalog or edge-type file gets the land's edits reversed in
            place. Rebuild, kb-graph --check, kb-lint 0 FAIL (miss -> exit 3), unland row, proposal
            back to open.
Recovery    Preimages: land and unland store every touched file's prior bytes, write-once, at
            KB/inbox/_objects/<sha256> (hash verified on read; git is only the fallback for instances
            older than _objects). Journal: each land/unland writes KB/inbox/_ops/<op>.json first
            {"op","verb","id","last","ledger_size","files":{rel:{"pre","post"}},"steps"} and marks
            FAULT_POINTS as it passes them; the file is removed when the op ends. Every kb-write and
            kb-correct invocation first runs recover: an op whose last step is marked and whose files
            all sit at their post hashes is completed, any other is rolled back (files to their pre
            bytes, ledger truncated to ledger_size); either way one recover row. KB_WRITE_FAULT=<point>
            dies at that boundary leaving the journal (exit 9, test seam).

Spec: docs/second-brain-loop/SPEC.md §1.3 + P2. Zero LLM calls.
Stdlib only, Python 3.9 compatible.
"""
from __future__ import annotations

import argparse
import contextlib
import difflib
import hashlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_")[:-3], TOOLS / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(TOOLS))
import kb_config  # noqa: E402

kblint = _load("kb-lint.py")
prov = _load("kb-provenance.py")  # raw source hashing at land  # header contract: CONFIDENCE, TYPES, INDEX_TYPES
autolink = _load("kb-autolink.py")  # _known_targets for wiki: refs and link ends

INBOX = "KB/inbox"
SEAL = INBOX + "/_seal.json"
LEDGER = INBOX + "/_ledger.jsonl"
LOCK = INBOX + "/.lock"
RESERVED_FILES = ("_seal.json", "_ledger.jsonl", ".lock")
OBJECTS = INBOX + "/_objects"  # content-addressed preimages
OPS = INBOX + "/_ops"  # durable operation journals
RESERVED_DIRS = ("_corrections", "_objects", "_ops")
MASTER = "KB/wiki/_index.md"
CATALOG = kb_config.DEFAULTS["catalog"]  # rebound per root by configure()
EDGE_TYPES = "KB/output/kb-edge-types.json"
DERIVED = ("KB/output/kb-index.json", "KB/output/content-seeds.json", "KB/output/kb-graph.json",
           kb_config.DEFAULTS["dashboard"])  # kb-index + kb-graph rebuild these after land and unland
REGRESSIONS = kb_config.DEFAULTS["regressions"]  # the post-check skips the gate while the file is absent
HOOK = TOOLS / "kb-correct.py"  # P3; correction: lands call it after the ledger row
FAULT_ENV = "KB_WRITE_FAULT"  # =postcheck forces a post-check failure; =<FAULT_POINTS> a crash (test seam)
FAULT_POINTS = ("after-page", "after-derived", "after-ledger", "after-proposal", "after-case")
LAND_WORDS = (100, 200, 400)  # body words: under the first exits 2; outside the other two WARNs

VERBS = ("put", "link", "withdraw", "reject", "resolve", "list", "seal", "land", "unland")
LEDGER_EVENTS = ("put", "withdraw", "reject", "land", "unland", "resolve", "adopt", "reseal", "recover")
EVENT_STATE = {"put": "open", "withdraw": "withdrawn", "reject": "rejected", "land": "landed",
               "unland": "open", "resolve": "resolved"}
ALLOW = {  # verb -> root-relative dir prefixes (trailing /) or exact files it may write
    "put": (INBOX + "/",),
    "link": (INBOX + "/",),
    "withdraw": (INBOX + "/",),
    "reject": (INBOX + "/",),
    "resolve": (INBOX + "/",),
    "land": ("KB/wiki/", CATALOG, EDGE_TYPES) + DERIVED + (INBOX + "/",),
    "unland": ("KB/wiki/", CATALOG, EDGE_TYPES) + DERIVED + (INBOX + "/",),
    "seal": (SEAL,),
    "adopt": (LEDGER,),
    "reseal": (LEDGER,),
}  # recover = land's allowlist + the regressions file (configure() sets both)

KINDS = ("article", "gap", "link")
STATES = ("open", "landed", "withdrawn", "rejected", "resolved")
GAP_KINDS = ("stale", "thin", "contradictory", "missing", "skill")
COMMON_KEYS = ("id", "kind", "state", "proposed_by", "proposed_at", "source_refs", "confidence", "origin",
               "dedupe_key")
KIND_KEYS = {
    "article": ("type", "category", "stem", "supersedes", "base_hash", "resolves"),
    "gap": ("gap_kind", "target", "query"),
    "link": ("link_from", "link_to", "link_type", "prose"),
}
REQUIRED_KIND_KEYS = {"article": ("type", "category", "stem"), "gap": ("gap_kind", "target"),
                      "link": ("link_from", "link_to", "link_type", "prose")}
TOOL_KEYS = ("endorsed_by", "decided_at", "landed_path", "reason")
REF_PREFIXES = ("raw", "wiki", "output", "owner", "query")

AGENT_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,31}$")
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
STEM_RE = re.compile(r"^[A-Za-z0-9]+(-[A-Za-z0-9]+)*$")  # live stems include mahaShivaratri-...
SLUG_MAX = 60
FILE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9]+(-[a-z0-9]+)*\.md$")
ID_RE = re.compile(r"^([A-Z][A-Z0-9_]{1,31}|[a-z][a-z0-9_-]{1,31})/\d{4}-\d{2}-\d{2}-[a-z0-9]+(-[a-z0-9]+)*$")

# ---------- instance config (founder/harness agnostic) ----------
CONFIG = kb_config.CONFIG  # optional; every key has a neutral default (tools/kb_config.py)
OWNER_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")


def config(root: Path) -> dict:
    """Instance settings: owner = the one human id that endorses lands (lowercase); agents = extra agent
    ids (UPPERCASE); agents_glob = a pattern whose matches' parent folder names are agent ids. Unknown keys
    are ignored so other tools can share the file."""
    try:
        cfg = kb_config.load(root)
    except ValueError:
        raise Fail(1, "io", "%s is not valid JSON" % CONFIG)
    if not OWNER_RE.match(str(cfg["owner"])):
        raise Fail(1, "io", "%s owner %r: want lowercase ^[a-z][a-z0-9_-]{1,31}$" % (CONFIG, cfg["owner"]))
    return cfg


def configure(root: Path) -> None:
    """Rebind the instance paths (catalog, dashboard, regressions) from KB/kb.json for this root."""
    global CATALOG, DERIVED, REGRESSIONS
    CATALOG = kb_config.rel(root, "catalog")
    DERIVED = DERIVED[:3] + (kb_config.rel(root, "dashboard"),)
    REGRESSIONS = kb_config.rel(root, "regressions")
    for verb in ("land", "unland"):
        ALLOW[verb] = ("KB/wiki/", CATALOG, EDGE_TYPES) + DERIVED + (INBOX + "/",)
    ALLOW["recover"] = ALLOW["land"] + (REGRESSIONS,)


def owner(root: Path) -> str:
    return config(root)["owner"]
ORIGIN_RE = re.compile(r"^(skill:[a-z0-9-]+|correction:C-\d{4}|brain-dream:\d{4}-\d{2}-\d{2}:[^:\s]+:[^:\s]+)$")
KEY_RE = re.compile(r"^[a-z_]+$")
SHA12_RE = re.compile(r"^[0-9a-f]{12}$")
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
YAML_WORDS = ("null", "true", "false", "yes", "no", "on", "off", "~")


class Fail(Exception):
    def __init__(self, code: int, error: str, detail: str):
        super().__init__(detail)
        self.code, self.error, self.detail = code, error, detail


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def iso_date(value: str):
    try:
        return date.fromisoformat(value) if ISO_RE.match(value or "") else None
    except ValueError:
        return None


# ---------- inbox file format ----------

def _scalar(value) -> str:
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    s = str(value)
    if (not s or s != s.strip() or s[0] in "[]{}\"'#&*!|>%@`,?-" or ": " in s or " #" in s or "\n" in s
            or s.lower() in YAML_WORDS):
        return json.dumps(s, ensure_ascii=False)
    return s


def render(meta: dict, body: str) -> str:
    return "---\n" + "".join("%s: %s\n" % (k, _scalar(v)) for k, v in meta.items()) + "---\n" + body


def parse(text: str):
    """(meta, body) of one inbox file. ValueError on anything outside the flat subset."""
    if not text.startswith("---\n"):
        raise ValueError("no '---' frontmatter on line 1")
    end = text.find("\n---\n", 3)
    if end < 0:
        raise ValueError("frontmatter never closes with '---'")
    meta = {}
    for n, line in enumerate(text[4:end].split("\n"), 2):
        key, sep, value = line.partition(":")
        if not sep or not KEY_RE.match(key):
            raise ValueError("line %d: not 'key: value'" % n)
        if key in meta:
            raise ValueError("line %d: duplicate key %s" % (n, key))
        value = value.strip()
        try:
            meta[key] = json.loads(value) if value[:1] in ('"', "[") else value
        except ValueError:
            raise ValueError("line %d: bad JSON value for %s" % (n, key))
    return meta, text[end + 5:]


def ref_prefixes(owner_id: str = "") -> tuple:
    """REF_PREFIXES plus the configured owner id, an alias of owner: (keeps pre-config history valid)."""
    return REF_PREFIXES + ((owner_id,) if owner_id and owner_id not in REF_PREFIXES else ())


def problems(meta: dict, owner_id: str = "") -> list:
    """(check, detail) pairs for one parsed frontmatter; check is 'unknown-key' or 'invalid'."""
    out, kind = [], meta.get("kind")
    unknown = sorted(set(meta) - set(COMMON_KEYS) - set(TOOL_KEYS) - set(KIND_KEYS.get(kind, ())))
    if unknown:
        out.append(("unknown-key", "unknown key(s) for kind %s: %s" % (kind, ", ".join(unknown))))
    missing = [k for k in COMMON_KEYS + REQUIRED_KIND_KEYS.get(kind, ()) if k not in meta]
    if missing:
        out.append(("invalid", "missing key(s): " + ", ".join(missing)))
    for key, value in meta.items():
        if key == "source_refs":
            if not (isinstance(value, list) and value and all(isinstance(r, str) for r in value)):
                out.append(("invalid", "source_refs must be a non-empty list of strings"))
            else:
                ok = ref_prefixes(owner_id)
                bad = [r for r in value if r.partition(":")[0] not in ok or not r.partition(":")[2]]
                if bad:
                    out.append(("invalid", "source_refs prefix not in %s: %s" % (list(ok), bad)))
        elif not isinstance(value, str):
            out.append(("invalid", "%s must be a scalar" % key))
    article_types = [t for t in kblint.TYPES if t not in kblint.INDEX_TYPES]
    for key, enum in (("kind", KINDS), ("state", STATES), ("confidence", kblint.CONFIDENCE),
                      ("gap_kind", GAP_KINDS), ("type", article_types)):
        if key in meta and meta[key] not in enum:
            out.append(("invalid", "%s %r not in %s" % (key, meta[key], list(enum))))
    if meta.get("origin") and not ORIGIN_RE.match(str(meta["origin"])):
        out.append(("invalid", "origin %r is not skill:NAME, correction:C-NNNN or brain-dream:DATE:T:M"
                    % meta["origin"]))
    if "dedupe_key" in meta and not SHA12_RE.match(str(meta["dedupe_key"])):
        out.append(("invalid", "dedupe_key %r is not 12 hex chars" % meta["dedupe_key"]))
    return out


# ---------- disk state ----------

def agent_names(root: Path) -> set:
    """Owner id + config agents + parent folders of agents_glob matches (regular files only)."""
    cfg = config(root)
    names = {cfg["owner"]} | {a for a in cfg["agents"] if AGENT_RE.match(str(a))}
    if cfg["agents_glob"]:
        for m in root.glob(cfg["agents_glob"]):
            if m.is_file() and not m.is_symlink() and AGENT_RE.match(m.parent.name):
                names.add(m.parent.name)
    return names


def proposals(root: Path):
    """(id, rel, meta) for every parseable inbox file in an agent folder; WP2 reports the rest."""
    inbox, agents = root / INBOX, agent_names(root)
    if not inbox.is_dir():
        return
    for folder in sorted(inbox.iterdir()):
        if folder.name not in agents or not folder.is_dir():
            continue
        for p in sorted(folder.iterdir()):
            if not (p.is_file() and FILE_RE.match(p.name)):
                continue
            try:
                meta, _ = parse(p.read_text(encoding="utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            yield folder.name + "/" + p.name[:-3], p.relative_to(root).as_posix(), meta


def read_ledger(root: Path) -> list:
    """Every ledger row, oldest first. ValueError on a bad line, unknown event or a seq gap."""
    p = root / LEDGER
    if not p.is_file():
        return []
    rows, lines = [], p.read_text(encoding="utf-8").split("\n")
    if lines[-1]:
        raise ValueError("%s line %d: no trailing newline (truncated append)" % (LEDGER, len(lines)))
    for n, line in enumerate(lines[:-1], 1):
        try:
            row = json.loads(line)
        except ValueError:
            raise ValueError("%s line %d: not JSON" % (LEDGER, n))
        if not isinstance(row, dict) or row.get("event") not in LEDGER_EVENTS:
            raise ValueError("%s line %d: event not in %s" % (LEDGER, n, list(LEDGER_EVENTS)))
        if row.get("seq") != len(rows) + 1:
            raise ValueError("%s line %d: seq %r, want %d (append-only, no gaps)" % (LEDGER, n, row.get("seq"),
                                                                                    len(rows) + 1))
        if not isinstance(row.get("files"), dict):
            raise ValueError("%s line %d: files must be an object" % (LEDGER, n))
        rows.append(row)
    return rows


def last_states(rows: list) -> dict:
    """id -> the state its last ledger event implies; a land row's resolved list resolves those gaps."""
    states = {}
    for row in rows:
        if row["event"] in EVENT_STATE and row.get("id"):
            states[row["id"]] = EVENT_STATE[row["event"]]
        if row["event"] == "land":
            for gid in row.get("resolved") or ():
                states[gid] = "resolved"
    return states


def wiki_hashes(root: Path) -> dict:
    """Root-relative path -> sha256 for KB/wiki/**/*.md, the set kb-lint lints and the seal covers."""
    wiki = root / "KB" / "wiki"
    return {p.relative_to(root).as_posix(): sha256(p.read_bytes()) for p in sorted(wiki.rglob("*.md"))}


def load_seal(root: Path):
    p = root / SEAL
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def expected_hashes(root: Path, rows: list):
    """Wiki path -> expected sha256 (None = expected absent): last ledger files entry, else the seal.
    None when there is no seal yet."""
    seal = load_seal(root)
    if seal is None:
        return None
    expected = dict(seal["files"])
    for row in rows:
        for path, digest in row["files"].items():
            if path.startswith("KB/wiki/"):
                expected[path] = digest
    return expected


def drift(root: Path, rows: list) -> dict:
    """Wiki path -> (expected, disk) for every path whose disk hash differs from its expected hash."""
    expected, disk = expected_hashes(root, rows), wiki_hashes(root)
    return {p: (expected.get(p), disk.get(p)) for p in sorted(set(expected) | set(disk))
            if expected.get(p) != disk.get(p)}


# ---------- the one write path ----------

def _allowed(verb: str, rel: str) -> bool:
    return any(rel == a or (a.endswith("/") and rel.startswith(a)) for a in ALLOW.get(verb, ()))


def _write(root: Path, rel: str, data, verb: str, append: bool = False) -> None:
    """The one write path. data None deletes rel (land rollback, unland of a new page)."""
    parts = rel.split("/")
    if ".." in parts or "" in parts or not _allowed(verb, rel):
        raise Fail(2, "write refused", "%s may not write %s (allowlist: %s)" % (verb, rel, ALLOW.get(verb, ())))
    path = root / rel
    if data is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
    real = Path(os.path.realpath(path.parent)) / path.name
    try:
        real_rel = real.relative_to(os.path.realpath(root)).as_posix()
    except ValueError:
        real_rel = None
    if real_rel is None or not _allowed(verb, real_rel):
        raise Fail(2, "write refused", "%s resolves outside the %s allowlist" % (rel, verb))
    if data is None:
        if path.is_file():
            path.unlink()
        return
    if append:
        with open(path, "ab") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        return
    tmp = path.with_name("." + path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


@contextlib.contextmanager
def locked(root: Path):
    path = root / LOCK
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        raise Fail(5, "lock held", "%s exists: another kb-write is running, or one crashed (remove it only "
                                   "once none runs; the next run recovers its op)" % LOCK)
    try:
        os.write(fd, str(os.getpid()).encode("ascii"))
        os.close(fd)
        yield
    finally:
        os.unlink(path)


def append_ledger(root: Path, verb: str, event: str, pid: str, actor: str, origin: str, files: dict,
                  prior: dict, resolved=(), reason: str = "", extra=None) -> int:
    rows = read_ledger(root)
    row = {"seq": len(rows) + 1, "ts": now(), "event": event, "id": pid, "actor": actor, "origin": origin,
           "files": files, "prior": prior, "resolved": list(resolved), "reason": reason}
    row.update(extra or {})
    _write(root, LEDGER, (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"),
           verb, append=True)
    return row["seq"]


# ---------- validation helpers ----------

def need(cond, detail: str, code: int = 2, error: str = "contract violation") -> None:
    if not cond:
        raise Fail(code, error, detail)


def check_agent(root: Path, agent: str) -> None:
    need(agent in agent_names(root), "agent %r is not a registered agent nor the owner (see %s)" % (agent, CONFIG))


def article_path(root: Path, stem: str):
    if not STEM_RE.match(stem):
        return None
    hits = [p for p in (root / "KB" / "wiki").rglob(stem + ".md") if p.name != "_index.md"]
    return hits[0] if len(hits) == 1 else None


def check_refs(root: Path, refs: list, kind: str, gap_kind: str = "") -> None:
    need(refs, "at least one --source-ref is required")
    known = autolink._known_targets(root / "KB" / "wiki")[0]
    for ref in refs:
        prefix, sep, rest = ref.partition(":")
        ok = ref_prefixes(owner(root))
        need(sep and rest and prefix in ok, "source ref %r: prefix not in %s" % (ref, list(ok)))
        prefix = "owner" if prefix == owner(root) else prefix
        if prefix in ("raw", "output"):
            bases = ["KB/RAW"] if prefix == "raw" else ["output", "KB/output"]
            ok = False
            for base in bases:
                b = os.path.realpath(root / base)
                p = os.path.realpath(os.path.join(b, rest))
                ok = ok or (p.startswith(b + os.sep) and os.path.isfile(p))
            need(ok, "source ref %r: no such file under %s" % (ref, " or ".join(bases)))
        elif prefix == "wiki":
            need(rest in known, "source ref %r: not a known wiki target" % ref)
        elif prefix == "owner":
            d = iso_date(rest)
            need(d is not None and d <= date.today(), "source ref %r: not an ISO date <= today" % ref)
        else:
            need(kind == "gap" and gap_kind == "missing", "source ref %r: query: is allowed only on missing-gaps" % ref)
            need(SHA12_RE.match(rest), "source ref %r: query: wants 12 lowercase hex chars" % ref)


def norm(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def dedupe_key(kind: str, gap_kind: str, target: str, title: str) -> str:
    return sha256("|".join((kind, gap_kind, target, norm(title))).encode("utf-8"))[:12]


def h1(body: str) -> str:
    for line in body.split("\n"):
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def new_id(root: Path, agent: str, slug: str) -> str:
    base, n = "%s-%s" % (date.today().isoformat(), slug), 1
    while True:
        pid = "%s/%s%s" % (agent, base, "" if n == 1 else "-%d" % n)
        if not (root / INBOX / (pid + ".md")).exists():
            return pid
        n += 1


def store(root: Path, verb: str, agent: str, slug: str, meta: dict, body: str) -> dict:
    """Dedupe against open proposals, then write the inbox file and its put row under the lock."""
    with locked(root):
        for pid, _, other in proposals(root):
            if other.get("state") == "open" and other.get("dedupe_key") == meta["dedupe_key"]:
                raise Fail(4, "duplicate", "open proposal %s has dedupe_key %s" % (pid, meta["dedupe_key"]))
        pid = new_id(root, agent, slug)
        meta = dict({"id": pid}, **meta)
        need(not problems(meta, owner(root)), "self-check: %s" % problems(meta, owner(root)))
        rel = "%s/%s.md" % (INBOX, pid)
        data = render(meta, body).encode("utf-8")
        _write(root, rel, data, verb)
        seq = append_ledger(root, verb, "put", pid, agent, meta["origin"], {rel: sha256(data)}, {rel: None})
    return {"ok": True, "verb": verb, "id": pid, "path": rel, "ledger_seq": seq}


# ---------- verbs ----------

def cmd_put(root: Path, a) -> dict:
    check_agent(root, a.agent)
    need(a.kind in ("article", "gap"), "--kind %r not in ['article', 'gap'] (links use the link verb)" % a.kind)
    need(SLUG_RE.match(a.slug or "") and len(a.slug) <= SLUG_MAX,
         "--slug %r must match %s, max %d chars" % (a.slug, SLUG_RE.pattern, SLUG_MAX))
    need(a.confidence in kblint.CONFIDENCE, "--confidence %r not in %s" % (a.confidence, list(kblint.CONFIDENCE)))
    need(not a.origin or ORIGIN_RE.match(a.origin), "--origin %r is not skill:NAME, correction:C-NNNN or "
                                                    "brain-dream:DATE:T:M" % a.origin)
    try:
        body = Path(a.body_file).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError, TypeError) as e:
        raise Fail(1, "io", "--body-file: %s" % e)
    need(body.strip(), "--body-file is empty")
    need(not body.startswith("---"), "--body-file opens with '---': frontmatter is tool-set, pass flags instead")
    if not body.endswith("\n"):
        body += "\n"
    refs = a.source_ref or []
    meta = {"kind": a.kind, "state": "open", "proposed_by": a.agent, "proposed_at": now(), "source_refs": refs,
            "confidence": a.confidence, "origin": a.origin or ""}
    if a.kind == "gap":
        need(not (a.type or a.category or a.supersedes or a.resolves),
             "--type/--category/--supersedes/--resolves are article flags")
        need(a.gap_kind in GAP_KINDS, "--gap-kind %r not in %s" % (a.gap_kind, list(GAP_KINDS)))
        need((a.target or "").strip(), "--target is required for a gap")
        check_refs(root, refs, "gap", a.gap_kind)
        meta["dedupe_key"] = dedupe_key("gap", a.gap_kind, a.target.strip(), h1(body) or a.slug)
        meta.update({"gap_kind": a.gap_kind, "target": a.target.strip()})
        if a.query:
            meta["query"] = a.query
        return store(root, "put", a.agent, a.slug, meta, body)

    need(not (a.gap_kind or a.target or a.query), "--gap-kind/--target/--query are gap flags")
    article_types = [t for t in kblint.TYPES if t not in kblint.INDEX_TYPES]
    typ = a.type or "article"
    need(typ in article_types, "--type %r not in %s" % (typ, article_types))
    categories = {d.name for d in (root / "KB" / "wiki").iterdir() if d.is_dir()}
    extra = {}
    if a.supersedes:
        stem = a.supersedes[5:] if a.supersedes.startswith("wiki:") else ""
        page = article_path(root, stem)
        need(page is not None, "--supersedes %r: want wiki:<stem> of one existing article" % a.supersedes)
        category = page.parent.name
        need(a.category in (None, category), "--category %r but %s lives in %s" % (a.category, stem, category))
        extra = {"supersedes": a.supersedes, "base_hash": sha256(page.read_bytes())}
    else:
        stem, category = a.slug, a.category
        need(category in categories, "--category %r is not a folder under KB/wiki" % category)
        need(any(r.startswith(("raw:", "owner:")) for r in refs),
             "a new stem needs at least one raw: or owner: source ref")
    if a.resolves:
        need(ID_RE.match(a.resolves), "--resolves %r is not an inbox id" % a.resolves)
        gaps = [m for pid, _, m in proposals(root) if pid == a.resolves]
        need(gaps and gaps[0].get("kind") == "gap" and gaps[0].get("state") == "open",
             "--resolves %s is not an open gap" % a.resolves)
        extra["resolves"] = a.resolves
    check_refs(root, refs, "article")
    meta["dedupe_key"] = dedupe_key("article", "", "%s/%s" % (category, stem), h1(body) or a.slug)
    meta.update({"type": typ, "category": category, "stem": stem})
    meta.update(extra)
    return store(root, "put", a.agent, a.slug, meta, body)


def cmd_link(root: Path, a) -> dict:
    check_agent(root, a.agent)
    need(a.confidence in kblint.CONFIDENCE, "--confidence %r not in %s" % (a.confidence, list(kblint.CONFIDENCE)))
    need(not a.origin or ORIGIN_RE.match(a.origin), "--origin %r is not skill:NAME, correction:C-NNNN or "
                                                    "brain-dream:DATE:T:M" % a.origin)
    need(article_path(root, a.link_from or "") is not None, "--from %r is not one existing article stem" % a.link_from)
    known = autolink._known_targets(root / "KB" / "wiki")[0]
    need(a.link_to in known and a.link_to != a.link_from, "--to %r is not a known wiki target other than --from"
         % a.link_to)
    graph = root / "KB" / "output" / "kb-graph.json"
    vocab = ["RELATES_TO"]
    if graph.is_file():
        vocab = json.loads(graph.read_text(encoding="utf-8")).get("type_vocabulary") or vocab
    need(a.type in vocab, "--type %r not in kb-graph type_vocabulary %s" % (a.type, vocab))
    prose = (a.prose or "").strip()
    need(len(prose) >= 3, "--prose needs at least 3 characters")
    refs = a.source_ref or []
    check_refs(root, refs, "link")
    slug = re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", ("link-%s-%s" % (a.link_from, a.link_to)).lower()))
    slug = slug[:SLUG_MAX].strip("-")
    meta = {"kind": "link", "state": "open", "proposed_by": a.agent, "proposed_at": now(), "source_refs": refs,
            "confidence": a.confidence, "origin": a.origin or "",
            "dedupe_key": dedupe_key("link", "", "%s>%s" % (a.link_from, a.link_to), a.type),
            "link_from": a.link_from, "link_to": a.link_to, "link_type": a.type, "prose": prose}
    return store(root, "link", a.agent, slug, meta, "- [[%s]] — %s\n" % (a.link_to, prose))


def proposal_rel(root: Path, pid: str) -> str:
    need(ID_RE.match(pid or ""), "%r is not an inbox id AGENT/YYYY-MM-DD-slug" % pid)
    rel = "%s/%s.md" % (INBOX, pid)
    need((root / rel).is_file(), "no proposal %s" % pid, code=1, error="io")
    return rel


def read_proposal(root: Path, rel: str):
    """(meta, body, bytes) of one inbox file; exit 2 unless it parses clean."""
    old = (root / rel).read_bytes()
    try:
        meta, body = parse(old.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise Fail(2, "contract violation", "%s: %s" % (rel, e))
    bad = problems(meta, owner(root))
    need(not bad, "%s: %s" % (rel, "; ".join(d for _, d in bad)))
    return meta, body, old


def transition(root: Path, verb: str, event: str, pid: str, actor: str, state: str, reason: str,
               check=None) -> int:
    """Move one open proposal to state: rewrite its frontmatter, append its ledger row. Caller holds the
    lock. Every event but withdraw is a decision and stamps decided_at."""
    rel = "%s/%s.md" % (INBOX, pid)
    meta, body, old = read_proposal(root, rel)
    if check:
        check(meta)
    need(meta["state"] == "open", "%s is %s, not open" % (pid, meta["state"]))
    meta.update({"state": state, "reason": reason})
    if event != "withdraw":
        meta["decided_at"] = now()
    data = render(meta, body).encode("utf-8")
    _write(root, rel, data, verb)
    return append_ledger(root, verb, event, pid, actor, meta["origin"], {rel: sha256(data)}, {rel: sha256(old)},
                         reason=reason)


def cmd_withdraw(root: Path, a) -> dict:
    need((a.reason or "").strip(), "--reason is required")
    rel = proposal_rel(root, a.id)

    def proposer(meta):
        need(a.by == meta["proposed_by"], "--by %r: only the proposer %s withdraws it" % (a.by, meta["proposed_by"]))

    with locked(root):
        seq = transition(root, "withdraw", "withdraw", a.id, a.by, "withdrawn", a.reason.strip(), proposer)
    return {"ok": True, "verb": "withdraw", "id": a.id, "path": rel, "ledger_seq": seq}


def cmd_decide(root: Path, a) -> dict:
    """reject (any kind) or resolve (gaps only): the owner's decision on one open proposal."""
    need((a.reason or "").strip(), "--reason is required")
    need(a.by == owner(root), "--by %s is required: %s is the owner's decision" % (owner(root), a.verb))
    rel = proposal_rel(root, a.id)

    def gaps_only(meta):
        need(a.verb == "reject" or meta["kind"] == "gap", "%s is a %s: resolve closes gaps; land the rest"
             % (a.id, meta["kind"]))

    with locked(root):
        seq = transition(root, a.verb, a.verb, a.id, owner(root), EVENT_STATE[a.verb], a.reason.strip(), gaps_only)
    return {"ok": True, "verb": a.verb, "id": a.id, "path": rel, "ledger_seq": seq}


def cmd_list(root: Path, a) -> dict:
    need(a.since is None or iso_date(a.since), "--since %r is not YYYY-MM-DD" % a.since, code=1, error="usage")
    need(a.state is None or a.state in STATES, "--state %r not in %s" % (a.state, list(STATES)), code=1,
         error="usage")
    items = []
    for pid, rel, meta in proposals(root):
        if a.state and meta.get("state") != a.state:
            continue
        if a.origin and not str(meta.get("origin", "")).startswith(a.origin):
            continue
        if a.since and str(meta.get("proposed_at", ""))[:10] < a.since:
            continue
        items.append({"id": pid, "kind": meta.get("kind"), "state": meta.get("state"),
                      "proposed_by": meta.get("proposed_by"), "proposed_at": meta.get("proposed_at"),
                      "origin": meta.get("origin"), "confidence": meta.get("confidence"), "path": rel})
    return {"ok": True, "verb": "list", "items": items}


def endorsed(root: Path, a) -> None:
    need((a.reason or "").strip(), "--reason is required")
    need(a.endorsed_by == owner(root), "--endorsed-by %s (the owner) is required" % owner(root))


def cmd_seal(root: Path, a) -> dict:
    if not a.reseal:
        need(not (root / SEAL).exists(), "%s exists; re-base with seal --reseal --reason R --endorsed-by OWNER"
             % SEAL, code=4, error="conflict")
        with locked(root):
            files = wiki_hashes(root)
            data = {"sealed_at": now(), "count": len(files), "files": files}
            _write(root, SEAL, (json.dumps(data, indent=1) + "\n").encode("utf-8"), "seal")
        return {"ok": True, "verb": "seal", "id": "", "path": SEAL, "ledger_seq": None, "count": len(files)}
    endorsed(root, a)
    need((root / SEAL).is_file(), "no %s yet; run seal first" % SEAL)
    with locked(root):
        moved = drift(root, read_ledger(root))
        seq = append_ledger(root, "reseal", "reseal", "", owner(root), "", {p: d for p, (_, d) in moved.items()},
                            {p: e for p, (e, _) in moved.items()}, reason=a.reason.strip())
    return {"ok": True, "verb": "seal", "id": "", "path": LEDGER, "ledger_seq": seq, "count": len(moved)}


def cmd_adopt(root: Path, a) -> dict:
    endorsed(root, a)
    need((root / SEAL).is_file(), "no %s yet; run seal first" % SEAL)
    rels = []
    for given in a.adopt:
        p = Path(given)
        p = p if p.is_absolute() else root / p
        try:
            rel = Path(os.path.realpath(p)).relative_to(os.path.realpath(root)).as_posix()
        except ValueError:
            rel = given
        need(rel.startswith("KB/wiki/") and rel.endswith(".md") and ".." not in rel.split("/"),
             "--adopt %r is not a KB/wiki/**/*.md path" % given)
        rels.append(rel)
    with locked(root):
        moved = drift(root, read_ledger(root))
        still = [r for r in rels if r not in moved]
        need(not still, "nothing to adopt: %s match their expected hash" % ", ".join(still))
        seq = append_ledger(root, "adopt", "adopt", "", owner(root), "", {r: moved[r][1] for r in rels},
                            {r: moved[r][0] for r in rels}, reason=a.reason.strip())
    return {"ok": True, "verb": "land", "id": "", "path": LEDGER, "ledger_seq": seq, "count": len(rels)}


# ---------- land: compose ----------

COUNT = r"^(\*\*%s:\*\*\s*)(\d+)"  # group 2 = the integer a land bumps
CATROW = r"^(\|\s*\[\[%s/_index[^\]]*\]\][^|\n]*\|\s*)(\d+)"  # master Categories row, Articles cell
ROW_RE = re.compile(r"^\|\s*\[\[([^\]|]+)\]\]\s*\|")  # category _index '| [[stem]] | claim |'
CLAIM_RE = re.compile(r"^##\s+Core Claim\s*$(.*?)(?=^##\s|\Z)", re.M | re.S)  # kb-index's rule


def set_run(text: str, values: dict) -> str:
    """The one header-run writer (spec P2 §2, §4). Each V2 key in values gets exactly one header line at
    its canonical slot: after the v2 keys that precede it, else at kb-lint run_start. None drops the key.
    Every other line stays, so Provenance is replaced, never appended. The text must open with an H1."""
    lines = text.split("\n")
    for key in kblint.V2_KEYS:
        if key not in values:
            continue
        h = kblint.parse_header("\n".join(lines))
        for i in reversed([i for i, k, _ in h["keys"] if k == key]):
            del lines[i]
        if values[key] is None:
            continue
        h = kblint.parse_header("\n".join(lines))
        before = [i for i, k, _ in h["keys"] if k in kblint.V2_KEYS[:kblint.V2_KEYS.index(key)]]
        lines.insert(before[-1] + 1 if before else kblint.run_start(h), "**%s:** %s" % (key, values[key]))
    return "\n".join(lines)


def compose_article(root: Path, meta: dict, body: str, pid: str, seq: int, today: str, known: set):
    """(rel, page, warnings) for an article land; exit 2 or 4 on a preflight miss."""
    stem, category = meta["stem"], meta["category"]
    rel = "KB/wiki/%s/%s.md" % (category, stem)
    need((root / "KB" / "wiki" / category).is_dir(), "category %s is not a folder under KB/wiki" % category)
    h = kblint.parse_header(body)
    need(h["h1"] is not None, "%s: the body's first non-blank line is not '# '" % pid)
    text = body
    if meta.get("supersedes"):
        page = root / rel
        need(page.is_file(), "supersede target %s is gone" % rel, 4, "conflict")
        need(sha256(page.read_bytes()) == meta.get("base_hash"), "stale base_hash: %s changed since the put" % rel,
             4, "conflict")
        if not any(k == "Sources" for _, k, _ in h["keys"]):
            base = kblint.parse_header(page.read_text(encoding="utf-8"))
            sources = [base["lines"][i] for i, k, _ in base["keys"] if k == "Sources"]
            later = [i for i, k, _ in h["keys"] if k in ("Updated",) + kblint.V2_KEYS]
            pos = later[0] if later else h["keys"][-1][0] + 1 if h["keys"] else h["h1"] + 1
            text = "\n".join(h["lines"][:pos] + sources + h["lines"][pos:])
    else:
        need(stem.casefold() not in {k.casefold() for k in known},
             "stem %s exists (an article, category or _index)" % stem, 4, "conflict")
    prov = "inbox %s · proposed %s · endorsed %s %s · ledger %d" % (pid, meta["proposed_by"], owner(root), today, seq)
    text = set_run(text, {"Type": meta["type"], "Confidence": meta["confidence"], "Provenance": prov})
    h = kblint.parse_header(text)
    got = kblint.meta_of(h)  # read_meta on the staged bytes
    need((got["type"], got["confidence"], got["provenance"]) == (meta["type"], meta["confidence"], prov),
         "self-check: read_meta disagrees with the composed header of %s" % rel)
    words = kblint.body_words(h)
    need(words >= LAND_WORDS[0], "%s: %d body words; land needs at least %d" % (pid, words, LAND_WORDS[0]))
    warns = [] if LAND_WORDS[1] <= words <= LAND_WORDS[2] else [
        "%s: %d body words, outside %d-%d" % (rel, words, LAND_WORDS[1], LAND_WORDS[2])]
    loose = sorted({m.group(2) for m in autolink.LINK_RE.finditer(text)
                    if autolink._classify(m.group(2), bool(m.group(1)), known | {stem})["kind"]
                    not in ("resolved", "excluded")})
    need(not loose, "%s: unresolved [[links]]: %s" % (pid, ", ".join(loose)))
    return rel, text, warns


def compose_link(root: Path, meta: dict, known: set):
    """(rel, page) for a link land: '- [[to]] — prose' appended under ## Connections, else ## Related,
    else under a new ## Connections before ## Open Questions, or at the end."""
    page = article_path(root, meta["link_from"])
    need(page is not None, "link_from %s is no longer one existing article" % meta["link_from"])
    need(meta["link_to"] in known, "link_to %s is no longer a known wiki target" % meta["link_to"])
    lines = page.read_text(encoding="utf-8").split("\n")
    bullet = "- [[%s]] — %s" % (meta["link_to"], meta["prose"].strip())
    heads = [i for i, line in enumerate(lines) if line.startswith("## ")]
    for name in ("## Connections", "## Related"):
        at = [i for i in heads if lines[i].strip() == name]
        if at:
            end = next((i for i in heads if i > at[0]), len(lines))
            lines.insert(max(i for i in range(at[0], end) if lines[i].strip()) + 1, bullet)
            break
    else:
        questions = [i for i in heads if re.match(r"^## Open Questions?\s*$", lines[i])]
        if questions:
            lines[questions[0]:questions[0]] = ["## Connections", bullet, ""]
        else:
            while lines and not lines[-1].strip():
                lines.pop()
            lines += ["", "## Connections", bullet, ""]
    return page.relative_to(root).as_posix(), "\n".join(lines)


def claim_of(text: str) -> str:
    """Index-row claim: the Core Claim section as kb-index reads it, else the first body paragraph."""
    m = CLAIM_RE.search(text)
    claim = " ".join(m.group(1).split()) if m else ""
    if not claim:
        h, para = kblint.parse_header(text), []
        for line in h["lines"][h["header_end"] or 0:]:
            if line.strip() and not line.startswith("#"):
                para.append(line.strip())
            elif para:
                break
        claim = " ".join(para)
    return claim.replace("|", "\\|")[:300].rstrip()


def bump(text: str, pattern: str, sign: int, what: str) -> str:
    m = re.search(pattern, text, re.M)
    need(m, "%s: no line matching %s" % (what, pattern))
    return text[:m.start(2)] + str(int(m.group(2)) + sign) + text[m.end(2):]


def stamp_updated(text: str, today: str) -> str:
    return re.sub(r"^(\*\*Updated:\*\*\s*)\S+", lambda m: m.group(1) + today, text, count=1, flags=re.M)


def index_row(text: str, stem: str, claim: str, what: str) -> str:
    """Replace stem's '| [[stem]] | claim |' row, else insert it before the first row that sorts after it,
    else after the last row."""
    lines = text.split("\n")
    rows = [(i, m.group(1).strip()) for i, line in enumerate(lines) for m in [ROW_RE.match(line)] if m]
    need(rows, "%s: no '| [[stem]] | claim |' rows to extend" % what)
    row = "| [[%s]] | %s |" % (stem, claim)
    hit = [i for i, s in rows if s == stem]
    if hit:
        lines[hit[0]] = row
    else:
        later = [i for i, s in rows if s.casefold() > stem.casefold()]
        lines.insert(later[0] if later else rows[-1][0] + 1, row)
    return "\n".join(lines)


def drop_row(text: str, stem: str) -> str:
    lines = text.split("\n")
    hit = [i for i, line in enumerate(lines) for m in [ROW_RE.match(line)] if m and m.group(1).strip() == stem]
    return "\n".join(lines[:hit[0]] + lines[hit[0] + 1:]) if hit else text


def recent(text: str, stem: str, action, today: str) -> str:
    """Add the newest Recent Updates row for stem (action), or drop it (action None)."""
    lines = text.split("\n")
    head = [i for i, line in enumerate(lines) if line.strip() == "## Recent Updates"]
    need(head, "%s: no ## Recent Updates" % MASTER)
    sep = next((i for i in range(head[0] + 1, len(lines)) if re.match(r"^\|[\s|:-]+\|\s*$", lines[i])), None)
    need(sep is not None, "%s: ## Recent Updates has no table" % MASTER)
    if action:
        lines.insert(sep + 1, "| %s | [[%s]] | %s |" % (today, stem, action))
        return "\n".join(lines)
    i = sep + 1
    while i < len(lines) and lines[i].startswith("|"):
        if "[[%s]]" % stem in lines[i]:
            del lines[i]
            break
        i += 1
    return "\n".join(lines)


def stage_runtime(root: Path, meta: dict, page: str, sign: int, today: str) -> dict:
    """rel -> bytes for the index, catalog and edge-type edits of one land (sign +1), or their reversal in
    place (sign -1: unland, for files whose exact prior bytes git cannot give back). Updated stays on
    reversal. Supersedes skip every count bump."""
    out = {}

    def text(rel):
        if rel not in out:
            need((root / rel).is_file(), "%s is missing" % rel)
            out[rel] = (root / rel).read_text(encoding="utf-8")
        return out[rel]

    if meta["kind"] == "link":
        p = root / EDGE_TYPES
        cache = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {"vocabulary": [], "edges": []}
        edge = {"s": meta["link_from"], "o": meta["link_to"],
                "hash": sha256(meta["prose"].strip().encode("utf-8"))[:16], "type": meta["link_type"]}
        if sign > 0:
            cache["edges"].append(edge)
        elif edge in cache["edges"]:
            del cache["edges"][len(cache["edges"]) - 1 - cache["edges"][::-1].index(edge)]
        return {EDGE_TYPES: json.dumps(cache, ensure_ascii=False, indent=1).encode("utf-8")}
    stem, category, new = meta["stem"], meta["category"], not meta.get("supersedes")
    cidx = "KB/wiki/%s/_index.md" % category
    t = index_row(text(cidx), stem, claim_of(page), cidx) if sign > 0 or not new else drop_row(text(cidx), stem)
    if sign > 0:
        t = stamp_updated(t, today)
    out[cidx] = bump(t, COUNT % "Articles", sign, cidx) if new else t
    m = recent(text(MASTER), stem, ("created" if new else "updated") if sign > 0 else None, today)
    if sign > 0:
        m = stamp_updated(m, today)
    if new:
        m = bump(bump(m, COUNT % "Status", sign, MASTER), CATROW % re.escape(category), sign, MASTER)
        if (root / CATALOG).is_file():  # the catalog page is optional
            out[CATALOG] = bump(text(CATALOG), COUNT % "Articles", sign, CATALOG)
    out[MASTER] = m
    return {rel: t.encode("utf-8") for rel, t in out.items()}


# ---------- land: write, post-check, rollback ----------

def file_hash(root: Path, rel: str):
    p = root / rel
    return sha256(p.read_bytes()) if p.is_file() else None


def git_bytes(root: Path, rel: str, digest: str):
    """rel's bytes with this sha256 from the last 50 commits that touched it; None when git has none."""
    def git(*args):
        try:
            r = subprocess.run(["git", "-C", str(root)] + list(args), capture_output=True)
        except OSError:
            return None
        return r.stdout if r.returncode == 0 else None

    for commit in (git("log", "--format=%H", "-n", "50", "--", rel) or b"").decode("ascii").split():
        data = git("show", "%s:./%s" % (commit, rel))
        if data is not None and sha256(data) == digest:
            return data
    return None


# ---------- recovery: preimages + operation journal ----------

class Crash(BaseException):
    """KB_WRITE_FAULT=<point>: the op dies at that boundary, journal left in place (test seam). A
    BaseException so no in-process rollback catches it."""


def put_object(root: Path, data: bytes, verb: str) -> str:
    """Store data at _objects/<sha256>, write-once (a copy failing its hash is replaced)."""
    digest = sha256(data)
    rel = "%s/%s" % (OBJECTS, digest)
    if file_hash(root, rel) != digest:
        _write(root, rel, data, verb)
    return digest


def get_object(root: Path, digest: str):
    p = root / OBJECTS / digest
    if p.is_file():
        data = p.read_bytes()
        if sha256(data) == digest:
            return data
    return None


def prior_bytes(root: Path, rel: str, digest: str):
    """rel's bytes with this sha256: the preimage store first, git for instances older than _objects."""
    data = get_object(root, digest)
    return data if data is not None else git_bytes(root, rel, digest)


class Op:
    """One journaled land/unland. Every touched file's preimage is stored before the first write."""

    def __init__(self, root: Path, verb: str, pid: str, rels, last: str):
        self.root, self.verb = root, verb
        oid = "%s-%d" % (datetime.now().strftime("%Y%m%dT%H%M%S%f"), os.getpid())
        self.rel = "%s/%s.json" % (OPS, oid)
        files = {}
        for rel in sorted(set(rels)):
            p = root / rel
            files[rel] = {"pre": put_object(root, p.read_bytes(), verb) if p.is_file() else None, "post": None}
        lp = root / LEDGER
        self.j = {"op": oid, "verb": verb, "id": pid, "last": last, "ledger_size": lp.stat().st_size
                  if lp.is_file() else 0, "files": files, "steps": []}
        self.save()

    def save(self) -> None:
        _write(self.root, self.rel, (json.dumps(self.j, indent=1) + "\n").encode("utf-8"), self.verb)

    def pre(self, rel: str):
        return self.j["files"][rel]["pre"]

    def step(self, name: str) -> None:
        for rel, f in self.j["files"].items():
            f["post"] = file_hash(self.root, rel)
        self.j["steps"].append(name)
        self.save()
        if os.environ.get(FAULT_ENV) == name:
            raise Crash(name)

    def abort(self) -> None:
        restore(self.root, self.j, self.verb)
        self.done()

    def done(self) -> None:
        _write(self.root, self.rel, None, self.verb)


def restore(root: Path, j: dict, verb: str) -> dict:
    """Put every journaled file back to its pre bytes and drop ledger rows past ledger_size. Idempotent.
    Returns rel -> the hash it held before the restore, for the files that moved."""
    moved = {}
    for rel, f in sorted(j["files"].items()):
        cur = file_hash(root, rel)
        if cur == f["pre"]:
            continue
        data = None if f["pre"] is None else get_object(root, f["pre"])
        need(f["pre"] is None or data is not None, "op %s: preimage %s of %s missing from %s"
             % (j["op"], f["pre"], rel, OBJECTS), 2, "recover failed")
        _write(root, rel, data, verb)
        moved[rel] = cur
    lp = root / LEDGER
    if lp.is_file() and lp.stat().st_size > j["ledger_size"]:
        _write(root, LEDGER, lp.read_bytes()[:j["ledger_size"]], verb)
    return moved


def recover(root: Path) -> list:
    """Finish or roll back every unfinished op left in _ops/, one recover ledger row each."""
    d = root / OPS
    if not d.is_dir() or not any(d.glob("*.json")):
        return []
    out = []
    with locked(root):
        for p in sorted(d.glob("*.json")):
            rel = p.relative_to(root).as_posix()
            j = json.loads(p.read_text(encoding="utf-8"))
            if j["last"] in j["steps"] and all(file_hash(root, r) == f["post"] for r, f in j["files"].items()):
                action, files, prior = "completed", {}, {}
            else:
                moved = restore(root, j, "recover")
                action = "rolled back"
                files, prior = {r: j["files"][r]["pre"] for r in moved}, moved
            step = j["steps"][-1] if j["steps"] else "start"
            seq = append_ledger(root, "recover", "recover", j["id"], "kb-write", "", files, prior,
                                reason="%s %s op %s after %s" % (action, j["verb"], j["op"], step))
            _write(root, rel, None, "recover")
            out.append({"op": j["op"], "verb": j["verb"], "id": j["id"], "action": action, "step": step,
                        "ledger_seq": seq})
    return out


def postcheck(root: Path, verb: str, base) -> list:
    """Rebuild, then every gate of spec P2 §6 step 10; Fail(3) on the first miss. base None (unland) skips
    the autolink, recall and regression gates: removing a page may lower them. KB_WRITE_FAULT=postcheck
    forces a miss after every gate ran: the rollback test seam, read only here."""
    def gate(cond, detail):
        need(cond, detail, 3, "post-check failed")

    kbindex, kbgraph, out, notes = _load("kb-index.py"), _load("kb-graph.py"), root / "KB" / "output", []
    with contextlib.redirect_stdout(io.StringIO()):
        rc = kbindex.build(root)
    gate(rc == 0, "kb-index --root: rc %d" % rc)
    graph, errors = kbgraph.build(root, out, quiet=True)
    gate(graph is not None and not errors, "kb-graph --root: %s" % (errors or "no graph"))
    _write(root, "KB/output/kb-graph.json", json.dumps(graph, ensure_ascii=False, indent=1).encode("utf-8"), verb)
    with contextlib.redirect_stdout(io.StringIO()):
        rc = kbgraph.check(root, out)
    gate(rc == 0, "kb-graph --check: rc %d" % rc)
    if base is not None:
        unresolved = autolink.scan(root / "KB" / "wiki")["unresolved_occurrences"]
        gate(unresolved <= base["unresolved"], "autolink unresolved %d > preflight %d" % (unresolved, base["unresolved"]))
        res = _load("kb-eval.py").run(root)
        new, old = res["new"]["combined"], res["old"]["combined"]
        gate(not res["missing_gold"] and new >= old, "kb-eval --check: new %.3f old %.3f, missing gold %s"
             % (new, old, res["missing_gold"]))
        gate(new >= base["recall"], "recall@6 %.3f < preflight %.3f" % (new, base["recall"]))
        notes.append("recall@6 %.3f (preflight %.3f)" % (new, base["recall"]))
        if (root / REGRESSIONS).is_file():
            r = subprocess.run([sys.executable, str(TOOLS / "kb-eval.py"), "--root", str(root), "--regressions",
                                str(root / REGRESSIONS)], capture_output=True)
            gate(r.returncode == 0, "kb-eval --regressions: rc %d %s" % (r.returncode, r.stdout.decode()[-300:]))
            notes.append("regressions green")
        else:
            notes.append("regressions: %s absent, skipped" % REGRESSIONS)
    rep = kblint.lint(root)
    gate(rep["counts"]["fail"] == 0, "kb-lint %d FAIL: %s" % (rep["counts"]["fail"], [
        "%s %s" % (f["check"], f["path"]) for f in rep["findings"] if f["severity"] == "FAIL"][:5]))
    gate(os.environ.get(FAULT_ENV) != "postcheck", "%s=postcheck (test seam)" % FAULT_ENV)
    return notes


def apply(root: Path, verb: str, staged: dict, base, op: Op) -> list:
    """Write staged files, rebuild, post-check, marking after-page and after-derived. Returns the notes."""
    for rel, data in staged.items():
        _write(root, rel, data, verb)
    op.step("after-page")
    notes = postcheck(root, verb, base)
    op.step("after-derived")
    return notes


def rolled_back(op: Op, e: Exception) -> Fail:
    """Any miss after the op began: every journaled byte back, ledger rows dropped, exit 3."""
    op.abort()
    detail = e.detail if isinstance(e, Fail) else "%s: %s" % (type(e).__name__, e)
    return Fail(3, e.error if isinstance(e, Fail) and e.code == 3 else "rolled back", detail + "; rolled back")


def unified(root: Path, staged: dict) -> str:
    out = []
    for rel in sorted(staged):
        p = root / rel
        old = p.read_text(encoding="utf-8").splitlines(True) if p.is_file() else []
        new = staged[rel].decode("utf-8").splitlines(True) if staged[rel] is not None else []
        out.extend(line if line.endswith("\n") else line + "\n" for line in
                   difflib.unified_diff(old, new, "a/" + rel if p.is_file() else "/dev/null", "b/" + rel))
    return "".join(out)


def run_hook(root: Path, cid: str, seq: int) -> str:
    """Spec P2 §6 step 12: a correction land reports to kb-correct after its ledger row, inside the op.
    Absent = skipped (the row says hook_skipped); a failing hook fails the land, which rolls back."""
    if not HOOK.is_file():
        return "skipped"
    try:
        r = subprocess.run([sys.executable, str(HOOK), "landed", cid, "--ledger-seq", str(seq), "--root", str(root)],
                           capture_output=True)
        rc, err = r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace")[-300:]
    except OSError as e:
        rc, err = -1, str(e)
    need(rc == 0, "regression registration failed: kb-correct.py landed %s rc %d %s" % (cid, rc, err.strip()),
         3, "hook failed")
    return "ok"


# ---------- land / unland ----------

def land_one(root: Path, pid: str, dry: bool) -> dict:
    rel = proposal_rel(root, pid)
    with contextlib.nullcontext() if dry else locked(root):
        meta, body, old = read_proposal(root, rel)
        need(meta["state"] == "open", "%s is %s, not open" % (pid, meta["state"]))
        need(meta["kind"] != "gap", "%s is a gap: gaps resolve (resolve ID, or put --resolves), never land" % pid)
        need(load_seal(root) is not None, "no %s: WP1 cannot vouch for the targets; run seal first" % SEAL)
        rows = read_ledger(root)
        seq, today = len(rows) + 1, date.today().isoformat()
        known = autolink._known_targets(root / "KB" / "wiki")[0]
        if meta["kind"] == "article":
            page_rel, page, warns = compose_article(root, meta, body, pid, seq, today, known)
        else:
            (page_rel, page), warns = compose_link(root, meta, known), []
        names = prov.raw_refs(page if meta["kind"] == "article" else "", meta.get("source_refs", []))
        sources, gone = prov.hash_sources(root, names)
        need(not gone, "%s: raw source(s) not in KB/RAW: %s" % (pid, ", ".join(gone)))
        staged = {page_rel: page.encode("utf-8")}
        staged.update(stage_runtime(root, meta, page, 1, today))
        dirty = sorted(set(staged) & set(drift(root, rows)))
        need(not dirty, "WP1 not clean on %s: adopt or unland first" % ", ".join(dirty))
        gaps = []
        if meta.get("resolves"):
            state = {p: m.get("state") for p, _, m in proposals(root)}.get(meta["resolves"])
            if state == "open":
                gaps.append(meta["resolves"])
            else:
                warns.append("resolves %s: %s, not open; left as is" % (meta["resolves"], state))
        unresolved = autolink.scan(root / "KB" / "wiki")["unresolved_occurrences"]
        if dry:
            regress = ("kb-eval --regressions %s == 0" % REGRESSIONS if (root / REGRESSIONS).is_file()
                       else "kb-eval --regressions: %s absent, skipped" % REGRESSIONS)
            plan = ["kb-index --root rebuild", "kb-graph --root rebuild", "kb-graph --check == 0",
                    "autolink unresolved <= %d" % unresolved, "kb-eval --check == 0, recall@6 >= preflight", regress,
                    "kb-lint 0 FAIL", "any miss: restore every captured byte, exit 3"]
            return {"ok": True, "verb": "land", "id": pid, "path": page_rel, "ledger_seq": None, "dry_run": True,
                    "staged": sorted(staged), "sources": sources, "resolves": gaps, "postcheck": plan, "warnings": warns,
                    "diff": unified(root, staged)}
        base = {"unresolved": unresolved, "recall": _load("kb-eval.py").run(root)["new"]["combined"]}
        cid = meta["origin"][len("correction:"):] if meta["origin"].startswith("correction:") else ""
        hooked = bool(cid) and HOOK.is_file()
        rels = list(staged) + list(DERIVED) + [rel] + [proposal_rel(root, g) for g in gaps]
        if hooked:
            rels += [REGRESSIONS, "%s/_corrections/%s/record.json" % (INBOX, cid)]
        op = Op(root, "land", pid, rels, "after-case" if hooked else "after-proposal")
        out = {"ok": True, "verb": "land", "id": pid, "path": page_rel, "ledger_seq": seq, "resolved": gaps,
               "sources": sources,
               "warnings": warns}
        try:
            out["postcheck"] = apply(root, "land", staged, base, op)
            meta.update({"state": "landed", "landed_path": page_rel, "endorsed_by": owner(root), "decided_at": now()})
            data = render(meta, body).encode("utf-8")
            files = {p: sha256(d) for p, d in staged.items()}
            prior = {p: op.pre(p) for p in staged}
            files[rel], prior[rel] = sha256(data), sha256(old)
            extra = {"sources": sources}
            if cid and not HOOK.is_file():
                extra["hook_skipped"] = "tools/kb-correct.py absent"
            append_ledger(root, "land", "land", pid, owner(root), meta["origin"], files, prior, resolved=gaps,
                          extra=extra)
            op.step("after-ledger")
            for gid in gaps:
                transition(root, "land", "resolve", gid, owner(root), "resolved", "landed " + pid)
            _write(root, rel, data, "land")
            op.step("after-proposal")
            if cid:
                out["hook"] = run_hook(root, cid, seq)
            if hooked:
                op.step("after-case")
        except Exception as e:
            raise rolled_back(op, e)
        op.done()
    return out


def cmd_land(root: Path, a) -> dict:
    if a.adopt:
        need(not a.ids and not a.dry_run, "--adopt takes paths only: no IDs, no --dry-run", 1, "usage")
        return cmd_adopt(root, a)
    need(a.ids, "land wants ID... --endorsed-by OWNER, or --adopt PATH...", 1, "usage")
    need(a.endorsed_by == owner(root), "--endorsed-by %s is required, after the owner has read the proposal"
         % owner(root))
    outs = [land_one(root, pid, a.dry_run) for pid in a.ids]
    return outs[0] if len(outs) == 1 else {"ok": True, "verb": "land", "id": " ".join(a.ids), "path": "",
                                           "ledger_seq": outs[-1]["ledger_seq"], "items": outs}


def cmd_unland(root: Path, a) -> dict:
    endorsed(root, a)
    rel = proposal_rel(root, a.id)
    with locked(root):
        meta, body, old = read_proposal(root, rel)
        need(meta["state"] == "landed", "%s is %s, not landed" % (a.id, meta["state"]))
        rows = read_ledger(root)
        lands = [r for r in rows if r["event"] == "land" and r["id"] == a.id]
        need(lands, "no land row for %s in %s" % (a.id, LEDGER))
        row, page_rel = lands[-1], meta.get("landed_path")
        staged, reverse = {}, []
        for p in sorted(row["files"]):
            if p == rel:
                continue
            prior = row["prior"].get(p)
            if file_hash(root, p) == row["files"][p]:
                data = None if prior is None else prior_bytes(root, p, prior)
                if prior is None or data is not None:
                    staged[p] = data
                    continue
            need(p != page_rel, "%s changed since the land (sha256 %s, ledger row %d wrote %s), or neither %s nor "
                 "git holds its prior bytes: supersede it" % (p, file_hash(root, p), row["seq"], row["files"][p],
                                                            OBJECTS), 4, "conflict")
            reverse.append(p)
        if reverse:
            page = staged.get(page_rel)
            back = stage_runtime(root, meta, page.decode("utf-8") if page else "", -1, date.today().isoformat())
            staged.update({p: back[p] for p in reverse})
        dirty = sorted(set(staged) & set(drift(root, rows)))
        need(not dirty, "WP1 not clean on %s: adopt first" % ", ".join(dirty))
        op = Op(root, "unland", a.id, list(staged) + list(DERIVED) + [rel], "after-proposal")
        try:
            apply(root, "unland", staged, None, op)
            for key in TOOL_KEYS:
                meta.pop(key, None)
            meta["state"] = "open"
            data = render(meta, body).encode("utf-8")
            files = {p: sha256(d) if d is not None else None for p, d in staged.items()}
            prior = {p: op.pre(p) for p in staged}
            files[rel], prior[rel] = sha256(data), sha256(old)
            seq = append_ledger(root, "unland", "unland", a.id, owner(root), meta["origin"], files, prior,
                                reason=a.reason.strip())
            op.step("after-ledger")
            _write(root, rel, data, "unland")
            op.step("after-proposal")
        except Exception as e:
            raise rolled_back(op, e)
        op.done()
    return {"ok": True, "verb": "unland", "id": a.id, "path": page_rel, "ledger_seq": seq,
            "exact": sorted(set(staged) - set(reverse)), "reversed": reverse}


# ---------- CLI ----------

class _Parser(argparse.ArgumentParser):
    def error(self, message):  # usage errors exit 1; 2 is reserved for contract violations
        self.print_usage(sys.stderr)
        print("usage error: " + message, file=sys.stderr)
        sys.exit(1)


def parser() -> argparse.ArgumentParser:
    common = _Parser(add_help=False)
    common.add_argument("--root", default=str(ROOT))
    common.add_argument("--json", action="store_true", help="print one JSON object")
    ap = _Parser(description="Inbox proposals + hash ledger. Writes KB/inbox only; never KB/wiki.")
    sub = ap.add_subparsers(dest="verb", required=True)
    p = sub.add_parser("put", parents=[common])
    p.add_argument("--agent", required=True)
    p.add_argument("--kind", required=True)
    p.add_argument("--slug", required=True)
    p.add_argument("--confidence", required=True)
    p.add_argument("--source-ref", action="append")
    p.add_argument("--body-file", required=True)
    for flag in ("--type", "--category", "--supersedes", "--resolves", "--gap-kind", "--target", "--query",
                 "--origin"):
        p.add_argument(flag)
    p = sub.add_parser("link", parents=[common])
    p.add_argument("--agent", required=True)
    p.add_argument("--from", dest="link_from", required=True)
    p.add_argument("--to", dest="link_to", required=True)
    p.add_argument("--type", required=True)
    p.add_argument("--prose", required=True)
    p.add_argument("--source-ref", action="append")
    p.add_argument("--confidence", required=True)
    p.add_argument("--origin")
    p = sub.add_parser("withdraw", parents=[common])
    p.add_argument("id")
    p.add_argument("--reason")
    p.add_argument("--by", required=True)
    p = sub.add_parser("list", parents=[common])
    p.add_argument("--state")
    p.add_argument("--origin")
    p.add_argument("--since")
    p = sub.add_parser("seal", parents=[common])
    p.add_argument("--reseal", action="store_true")
    p.add_argument("--reason")
    p.add_argument("--endorsed-by")
    for verb in ("reject", "resolve"):
        p = sub.add_parser(verb, parents=[common])
        p.add_argument("id")
        p.add_argument("--reason")
        p.add_argument("--by", required=True)
    p = sub.add_parser("land", parents=[common])
    p.add_argument("ids", nargs="*", metavar="ID")
    p.add_argument("--adopt", nargs="+", metavar="PATH")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--reason")
    p.add_argument("--endorsed-by")
    p = sub.add_parser("unland", parents=[common])
    p.add_argument("id")
    p.add_argument("--reason")
    p.add_argument("--endorsed-by")
    return ap


VERB_FN = {"put": cmd_put, "link": cmd_link, "withdraw": cmd_withdraw, "list": cmd_list, "seal": cmd_seal,
           "land": cmd_land, "unland": cmd_unland, "reject": cmd_decide, "resolve": cmd_decide}


def main(argv=None) -> int:
    a = parser().parse_args(argv)
    root = Path(a.root).resolve()
    configure(root)
    try:
        need((root / "KB" / "wiki").is_dir(), "%s/KB/wiki not found" % root, code=1, error="io")
        recovered = recover(root)
        out = VERB_FN[a.verb](root, a)
        if recovered:
            out["recovered"] = recovered
    except Crash as e:
        print(json.dumps({"error": "crash", "detail": "%s=%s" % (FAULT_ENV, e)}) if a.json else
              "kb-write %s: simulated crash at %s (exit 9)" % (a.verb, e), file=sys.stdout if a.json else sys.stderr)
        return 9
    except Fail as e:
        if a.json:
            print(json.dumps({"error": e.error, "detail": e.detail}, ensure_ascii=False))
        else:
            print("kb-write %s: %s (exit %d) — %s" % (a.verb, e.error, e.code, e.detail), file=sys.stderr)
        return e.code
    except (OSError, ValueError) as e:  # ValueError = unreadable ledger, seal or graph JSON: a contract breach
        code, error = (1, "io") if isinstance(e, OSError) else (2, "contract violation")
        if a.json:
            print(json.dumps({"error": error, "detail": str(e)}, ensure_ascii=False))
        else:
            print("kb-write %s: %s (exit %d) — %s" % (a.verb, error, code, e), file=sys.stderr)
        return code
    if a.json:
        print(json.dumps(out, ensure_ascii=False))
    elif a.verb == "list":
        for it in out["items"]:
            print("%-44s %-7s %-9s %-24s %s" % (it["id"], it["kind"], it["state"], it["origin"] or "-",
                                                it["proposed_at"]))
        print("%d proposal(s)" % len(out["items"]))
    else:
        print("%s %s -> %s%s%s" % (a.verb, out["id"] or "-", out["path"],
                                   "" if out["ledger_seq"] is None else " (ledger %d)" % out["ledger_seq"],
                                   " · %d file(s)" % out["count"] if "count" in out else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
