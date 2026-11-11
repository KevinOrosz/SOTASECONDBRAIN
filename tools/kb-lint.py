#!/usr/bin/env python3
"""kb-lint.py — wiki header contract v2. One deterministic linter, zero LLM calls.

Usage:  python3 tools/kb-lint.py [--root R] [--json] [--category NAME|_root] [--rule contract|WP1|WP2|all]
                                 [--contract] [--capture-baseline] [--migrate dry-run|write|revert]
Reads:  KB/wiki/**/*.md, <registry> (skill column, status != RETIRED),
        <router> (registered_names), <baseline> (paths from KB/kb.json),
        KB/inbox/** (WP1/WP2; schema, seal and ledger owned by tools/kb-write.py)
Writes: nothing, except --migrate write|revert (one **Type:** line per file) and
        --capture-baseline (the baseline "lint" key; every other key preserved).
Exit:   0 PASS · 1 FAIL/FATAL · 2 WARN

Canonical homes (spec §1.1): CONTRACT = header keys, order, enums, META, budgets;
read_meta(path) = header parsing; RULES = lint rules (later phases append, never redefine).
Spec: docs/second-brain-loop/SPEC.md §1.2 + P1.
Stdlib only, Python 3.9 compatible.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
import kb_config  # noqa: E402

TYPE_REQUIRED = False  # P1-S3 flips this; until then a missing Type is WARN, not FAIL

LEGACY_KEYS = ("Category", "Sources", "Tags", "Updated", "Articles", "Scope", "Status", "System")
V2_KEYS = ("Type", "Depends-On", "Consumers", "Confidence", "Last-Verified", "Provenance")  # canonical order
META = frozenset(LEGACY_KEYS + V2_KEYS)
P2_MANAGED = ("Confidence", "Provenance")
CONFIDENCE = ("high", "moderate", "low")
INDEX_TYPES = ("routing", "taxonomy")
# type -> (path default, soft budget, hard budget); words after the H1, META lines excluded
TYPES = {
    "routing": ("KB/wiki/_index.md", None, 6000),
    "taxonomy": ("<cat>/_index.md", None, 6000),
    "fact": ("<cat>/<stem>.md", 80, 200),
    "article": ("<cat>/<stem>.md", 400, 2000),
    "source": ("SOURCE_OVERRIDES", None, 15000),
    "position": (None, 400, 800),
    "gateway": (None, 150, 300),
}
SOURCE_OVERRIDES = (
    "spirituality-philosophy/aphorisms-and-power-quotes",
    "clients/testimonials",
    "clients/client-pricing-structures",
    "spirituality-philosophy/terence-mckenna-quotes-archive",
    "business-marketing/post-ideas-swipe-file",
)
CHECKS = {
    "header-missing-h1": "FAIL",
    "header-duplicate-key": "FAIL",
    "header-legacy-duplicate": "WARN",
    "header-order": "WARN",
    "type-missing": "FAIL" if TYPE_REQUIRED else "WARN",
    "type-invalid": "FAIL",
    "type-path-conflict": "FAIL",
    "confidence-invalid": "FAIL",
    "date-invalid": "FAIL",
    "dangling-depends-on": "FAIL",
    "self-dependency": "FAIL",
    "orphan-consumer": "FAIL",
    "duplicate-id": "FAIL",
    "cycle": "WARN",
    "budget-hard": "FAIL",
    "budget-soft": "WARN",
}

H1_PREFIX = "# "
HEADER_KEY = r"^\*\*[A-Za-z0-9][A-Za-z0-9 -]*:\*\*"
KEY_RE = re.compile(r"^\*\*([A-Za-z0-9][A-Za-z0-9 -]*):\*\*\s*(.*?)\s*$")
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

CONTRACT = {
    "version": 2,
    "header": {
        "start": "first non-blank line must start with '# '",
        "continues": "contiguous blank lines and lines matching " + HEADER_KEY,
        "legacy_keys": list(LEGACY_KEYS),
        "v2_keys_canonical_order": list(V2_KEYS),
        "v2_run": "one contiguous run directly after **Updated:**; else after the last legacy key",
        "depends_on": "comma-separated plain stems, not [[links]]",
        "consumers": "comma-separated skill:<REGISTRY skill> | agent:<router registered NAME>",
        "last_verified": "ISO date <= today; absent = unverified, never fresh",
        "p2_managed": list(P2_MANAGED),
    },
    "meta": sorted(META),
    "enums": {"type": list(TYPES), "confidence": list(CONFIDENCE)},
    "types": {t: {"path_default": d, "soft_words": s, "hard_words": h} for t, (d, s, h) in TYPES.items()},
    "index_types": list(INDEX_TYPES),
    "source_overrides": list(SOURCE_OVERRIDES),
    "type_required": TYPE_REQUIRED,
    "body_words": "words after the H1, minus META lines",
    "id": "article stem; unique case-insensitively; never equal to a category folder name",
    "checks": CHECKS,
    "exit_codes": {"0": "PASS", "1": "FAIL/FATAL", "2": "WARN"},
}


def parse_header(text: str) -> dict:
    """Header block = H1 at the first non-blank line, then contiguous blank or **Key:** lines."""
    lines = text.split("\n")
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i == len(lines) or not lines[i].startswith(H1_PREFIX):
        return {"lines": lines, "h1": None, "header_end": None, "keys": []}
    j, keys = i + 1, []
    while j < len(lines):
        m = KEY_RE.match(lines[j])
        if m:
            keys.append((j, m.group(1), m.group(2)))
        elif lines[j].strip():
            break
        j += 1
    return {"lines": lines, "h1": i, "header_end": j, "keys": keys}


def meta_of(h: dict) -> dict:
    first = {}
    for _, k, v in h["keys"]:
        first.setdefault(k, v)

    def items(key):
        return [s.strip() for s in first.get(key, "").split(",") if s.strip()]

    return {
        "type": first.get("Type") or None,
        "depends_on": items("Depends-On"),
        "consumers": items("Consumers"),
        "confidence": first.get("Confidence") or None,
        "last_verified": first.get("Last-Verified") or None,
        "updated": first.get("Updated") or None,
        "provenance": first.get("Provenance") or None,
        "header_end": h["header_end"],
    }


def read_meta(path) -> dict:
    """Header fields of one wiki file. header_end is None when there is no H1.
    last_verified stays None when absent: callers label whether they fell back to updated."""
    return meta_of(parse_header(Path(path).read_text(encoding="utf-8", errors="replace")))


def body_words(h: dict) -> int:
    start = h["h1"] + 1 if h["h1"] is not None else 0
    n = 0
    for line in h["lines"][start:]:
        m = KEY_RE.match(line)
        if not (m and m.group(1) in META):
            n += len(line.split())
    return n


def default_type(wrel: str) -> str:
    """Type a wiki path gets with no **Type:** line (wrel is relative to KB/wiki)."""
    if wrel == "_index.md":
        return "routing"
    if wrel.endswith("/_index.md"):
        return "taxonomy"
    if wrel[:-3] in SOURCE_OVERRIDES:
        return "source"
    return "article"


def run_start(h: dict) -> int:
    """Line where the v2 run belongs: after **Updated:**, else after the last legacy key,
    else at the first header key (or straight after the H1 when the header has none)."""
    keys = h["keys"]
    updated = [i for i, k, _ in keys if k == "Updated"]
    if updated:
        return updated[0] + 1
    legacy = [i for i, k, _ in keys if k in LEGACY_KEYS]
    if legacy:
        return legacy[-1] + 1
    return keys[0][0] if keys else h["h1"] + 1


def collect(root: Path) -> list:
    wiki = root / "KB" / "wiki"
    files = []
    for p in sorted(wiki.rglob("*.md")):
        wrel = p.relative_to(wiki).as_posix()
        h = parse_header(p.read_text(encoding="utf-8", errors="replace"))
        meta = meta_of(h)
        dt = default_type(wrel)
        files.append({
            "path": p,
            "rel": p.relative_to(root).as_posix(),
            "wrel": wrel,
            "id": wrel[:-3] if p.name == "_index.md" else p.stem,
            "stem": p.stem,
            "is_index": p.name == "_index.md",
            "h": h,
            "meta": meta,
            "default_type": dt,
            "type": meta["type"] if meta["type"] in TYPES else dt,
            "words": body_words(h),
        })
    return files


def in_category(f: dict, category) -> bool:
    if category is None:
        return True
    parts = f["wrel"].split("/")
    return len(parts) == 1 if category == "_root" else len(parts) > 1 and parts[0] == category


def load_skills(root: Path) -> dict:
    """REGISTRY skill -> status cell."""
    p = kb_config.path(root, "registry")
    skills = {}
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            cells = [c.strip() for c in line.split("|")]
            if len(cells) > 3 and cells[1].isdigit():
                skills[cells[2].strip("`")] = cells[-2]
    return skills


def load_agents(root: Path) -> set:
    p = kb_config.path(root, "router")
    if not p.is_file():
        return set()
    data = json.loads(p.read_text(encoding="utf-8"))
    return set(data.get("registered_names") or data.get("name_activation", {}).get("registered_names", []))


def baseline_path(root: Path) -> Path:
    return kb_config.path(root, "baseline")


def load_baseline(root: Path) -> dict:
    p = baseline_path(root)
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def finding(f, check: str, detail: str) -> dict:
    return {"path": f["rel"] if f else "KB/wiki", "id": f["id"] if f else "", "check": check,
            "severity": CHECKS[check], "detail": detail}


def find_cycles(edges: dict) -> list:
    """Iterative DFS over id -> {ids}. Each cycle once, rotated to its smallest node."""
    color, seen, cycles = {}, set(), []
    for start in sorted(edges):
        if color.get(start):
            continue
        color[start], path, stack = 1, [start], [iter(sorted(edges.get(start, ())))]
        while stack:
            nxt = next(stack[-1], None)
            if nxt is None:
                stack.pop()
                color[path.pop()] = 2
            elif not color.get(nxt):
                color[nxt] = 1
                path.append(nxt)
                stack.append(iter(sorted(edges.get(nxt, ()))))
            elif color[nxt] == 1:
                cyc = path[path.index(nxt):]
                k = cyc.index(min(cyc))
                rot = tuple(cyc[k:] + cyc[:k])
                if rot not in seen:
                    seen.add(rot)
                    cycles.append(rot)
    return cycles


def rule_contract(ctx: dict) -> list:
    """Header contract v2 over the full file set (global checks always see every file)."""
    out, today = [], ctx["today"]
    articles = [f for f in ctx["files"] if not f["is_index"]]
    ids = {}
    for f in articles:
        ids.setdefault(f["stem"].casefold(), []).append(f)

    for f in ctx["files"]:
        h, meta = f["h"], f["meta"]
        if h["h1"] is None:
            out.append(finding(f, "header-missing-h1", "first non-blank line is not '# '"))
            continue
        for key, n in sorted(Counter(k for _, k, _ in h["keys"] if k in META).items()):
            if n > 1:
                check = "header-duplicate-key" if key in V2_KEYS else "header-legacy-duplicate"
                out.append(finding(f, check, "%s x%d" % (key, n)))
        run = [(i, k) for i, k, _ in h["keys"] if k in V2_KEYS]
        if run:
            lines_at = [i for i, _ in run]
            ranks = [V2_KEYS.index(k) for _, k in run]
            if ranks != sorted(ranks) or lines_at != list(range(lines_at[0], lines_at[0] + len(run))) \
                    or lines_at[0] != run_start(h):
                out.append(finding(f, "header-order", "v2 keys %s; want one run in order %s at line %d"
                                   % ([k for _, k in run], list(V2_KEYS), run_start(h) + 1)))
        t = meta["type"]
        if t is None:
            out.append(finding(f, "type-missing", "path default: " + f["default_type"]))
        elif t not in TYPES:
            out.append(finding(f, "type-invalid", "%r not in %s" % (t, list(TYPES))))
        elif f["is_index"] != (t in INDEX_TYPES):
            out.append(finding(f, "type-path-conflict", "%s on %s" % (t, "an _index.md" if f["is_index"]
                                                                      else "a non-index page")))
        if meta["confidence"] is not None and meta["confidence"] not in CONFIDENCE:
            out.append(finding(f, "confidence-invalid", "%r not in %s" % (meta["confidence"], list(CONFIDENCE))))
        for key in ("Updated", "Last-Verified"):
            value = meta[key.lower().replace("-", "_")]
            if value is None:
                continue
            try:
                d = date.fromisoformat(value) if ISO_RE.match(value) else None
            except ValueError:
                d = None
            if d is None:
                out.append(finding(f, "date-invalid", "%s %r is not YYYY-MM-DD" % (key, value)))
            elif d > today:
                out.append(finding(f, "date-invalid", "%s %s is after today %s" % (key, value, today)))

    cats = {p.name.casefold() for p in (ctx["root"] / "KB" / "wiki").iterdir() if p.is_dir()}
    for key, group in sorted(ids.items()):
        for f in group:
            if len(group) > 1:
                others = [g["rel"] for g in group if g is not f]
                out.append(finding(f, "duplicate-id", "case-insensitive collision with " + ", ".join(others)))
            if key in cats:
                out.append(finding(f, "duplicate-id", "id equals category folder " + key))

    edges, by_key = {}, {k: g[0] for k, g in ids.items()}
    for f in ctx["files"]:
        src = f["stem"].casefold() if not f["is_index"] else f["id"]
        for dep in f["meta"]["depends_on"]:
            k = dep.casefold()
            if not f["is_index"] and k == src:
                out.append(finding(f, "self-dependency", dep))
            elif k not in ids:
                out.append(finding(f, "dangling-depends-on", dep + " resolves to no article id"))
            else:
                edges.setdefault(src, set()).add(k)
        for c in f["meta"]["consumers"]:
            kind, _, name = c.partition(":")
            if kind == "skill" and name in ctx["skills"]:
                if ctx["skills"][name].startswith("RETIRED"):
                    out.append(finding(f, "orphan-consumer", c + " is RETIRED in the skill registry"))
            elif kind == "skill":
                out.append(finding(f, "orphan-consumer", c + " is not in the skill registry"))
            elif kind == "agent":
                if name not in ctx["agents"]:
                    out.append(finding(f, "orphan-consumer", c + " is not a router registered NAME"))
            else:
                out.append(finding(f, "orphan-consumer", c + " has no skill:/agent: prefix"))
    for cyc in find_cycles(edges):
        out.append(finding(by_key.get(cyc[0]), "cycle", " -> ".join(cyc + (cyc[0],))))

    over_soft = 0
    for f in ctx["files"]:
        _, soft, hard = TYPES[f["type"]]
        if f["words"] > hard:
            out.append(finding(f, "budget-hard", "%d words > %d (%s)" % (f["words"], hard, f["type"])))
        if soft and f["words"] > soft and f["rel"] in ctx["selected"]:
            over_soft += 1
    ctx["stats"]["over_soft_budget"] = over_soft
    base = ctx["baseline"].get("lint", {}).get("over_soft_budget")
    if ctx["category"] is None and base is not None and over_soft > base:
        out.append(finding(None, "budget-soft", "%d pages over soft budget > baseline %d" % (over_soft, base)))
    return out


RULES = {"contract": rule_contract}

# ---------- P2: write-back provenance (spec P2 §6 16-17). Inbox schema + ledger: kb-write.py ----------
WP1_SEVERITY = "WARN"  # D4: WARN through P2-S2; P2-S3 flips this to FAIL
CHECKS.update({
    "wp1-unverifiable": WP1_SEVERITY,
    "wp1-new": WP1_SEVERITY,
    "wp1-edited": WP1_SEVERITY,
    "wp1-deleted": WP1_SEVERITY,
    "wp2-ledger": "FAIL",
    "wp2-stray": "FAIL",
    "wp2-parse": "FAIL",
    "wp2-unknown-key": "FAIL",
    "wp2-invalid": "FAIL",
    "wp2-state": "FAIL",
})
_KBW = []


def kbw():
    """kb-write.py, loaded on first WP use (it imports this module, so never at load time)."""
    if not _KBW:
        spec = importlib.util.spec_from_file_location("kb_write", Path(__file__).resolve().parent / "kb-write.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _KBW.append(mod)
    return _KBW[0]


def rule_wp1(ctx: dict) -> list:
    """Every KB/wiki file's hash equals its last ledger files entry, else its seal entry.
    Sees changes, not authors."""
    w, root = kbw(), ctx["root"]
    try:
        rows = w.read_ledger(root)
    except ValueError as e:
        return [finding(None, "wp1-unverifiable", str(e))]
    if w.load_seal(root) is None:
        return [finding(None, "wp1-unverifiable", "no %s; run: python3 tools/kb-write.py seal" % w.SEAL)]
    out = []
    for rel, (want, disk) in w.drift(root, rows).items():
        check = "wp1-new" if want is None else "wp1-deleted" if disk is None else "wp1-edited"
        out.append(finding({"rel": rel, "id": Path(rel).stem}, check,
                           "disk %s vs expected %s; record it: python3 tools/kb-write.py land --adopt %s "
                           "--reason R --endorsed-by OWNER" % ((disk or "absent")[:12], (want or "absent")[:12], rel)))
    return out


def rule_wp2(ctx: dict) -> list:
    """Inbox files parse, carry only known keys, sit in agent folders, and match their last ledger
    event; nothing else lives under KB/inbox except the reserved names."""
    w, root = kbw(), ctx["root"]
    inbox = root / w.INBOX
    if not inbox.is_dir():
        return []
    out = []

    def bad(path, check, detail, pid=""):
        out.append(finding({"rel": path.relative_to(root).as_posix(), "id": pid}, check, detail))

    try:
        states = w.last_states(w.read_ledger(root))
    except ValueError as e:
        bad(root / w.LEDGER, "wp2-ledger", str(e))
        states = None
    agents = w.agent_names(root)
    for entry in sorted(inbox.iterdir()):
        if entry.name in w.RESERVED_FILES or entry.name in w.RESERVED_DIRS:
            if entry.is_symlink() or not (entry.is_file() if entry.name in w.RESERVED_FILES else entry.is_dir()):
                bad(entry, "wp2-stray", "reserved name with the wrong file type")
            continue
        if entry.is_symlink() or not entry.is_dir() or entry.name not in agents:
            bad(entry, "wp2-stray", "not a reserved name nor an agent folder (a registered agent or the owner, see KB/kb.json)")
            continue
        for p in sorted(entry.iterdir()):
            pid = entry.name + "/" + p.name[:-3]
            if p.is_symlink() or not p.is_file() or not w.FILE_RE.match(p.name):
                bad(p, "wp2-stray", "agent folders hold only YYYY-MM-DD-slug.md files")
                continue
            try:
                meta, _ = w.parse(p.read_text(encoding="utf-8"))
            except (ValueError, UnicodeDecodeError) as e:
                bad(p, "wp2-parse", str(e), pid)
                continue
            for check, detail in w.problems(meta, w.owner(root)):
                bad(p, "wp2-" + check, detail, pid)
            if meta.get("id") != pid or meta.get("proposed_by") != entry.name:
                bad(p, "wp2-invalid", "id %r / proposed_by %r disagree with the path %s"
                    % (meta.get("id"), meta.get("proposed_by"), pid), pid)
            if states is not None and states.get(pid) != meta.get("state"):
                bad(p, "wp2-state", "state %r but the last ledger event implies %r"
                    % (meta.get("state"), states.get(pid)), pid)
    return out


RULES["WP1"] = rule_wp1
RULES["WP2"] = rule_wp2


def lint(root, *, category=None, rule="contract", today=None) -> dict:
    root = Path(root)
    files = collect(root)
    selected = [f for f in files if in_category(f, category)]
    ctx = {
        "root": root, "files": files, "selected": {f["rel"] for f in selected}, "category": category,
        "today": today or date.today(), "skills": load_skills(root), "agents": load_agents(root),
        "baseline": load_baseline(root), "stats": {"over_soft_budget": 0},
    }
    names = list(RULES) if rule == "all" else [rule]
    findings = [x for n in names for x in RULES[n](ctx)
                if category is None or x["path"] in ctx["selected"]]
    findings.sort(key=lambda x: (x["path"], x["check"], x["detail"]))
    sev = Counter(x["severity"] for x in findings)
    return {
        "file_count": len(selected),
        "typed_explicit": sum(1 for f in selected if f["meta"]["type"] is not None),
        "by_type": dict(sorted(Counter(f["type"] for f in selected).items())),
        "counts": {"fail": sev["FAIL"], "warn": sev["WARN"],
                   "over_soft_budget": ctx["stats"]["over_soft_budget"],
                   "cycles": sum(1 for x in findings if x["check"] == "cycle")},
        "baseline": ctx["baseline"].get("lint"),
        "findings": findings,
    }


def exit_code(rep: dict) -> int:
    return 1 if rep["counts"]["fail"] else 2 if rep["counts"]["warn"] else 0


def render(rep: dict) -> str:
    c, base = rep["counts"], rep["baseline"]
    out = [
        "kb-lint: %d file(s) · typed %d/%d · by_type %s" % (
            rep["file_count"], rep["typed_explicit"], rep["file_count"],
            " ".join("%s=%d" % kv for kv in rep["by_type"].items())),
        "  FAIL %d · WARN %d · over_soft_budget %d (baseline %s) · cycles %d" % (
            c["fail"], c["warn"], c["over_soft_budget"], base["over_soft_budget"] if base else "none", c["cycles"]),
    ]
    groups = {}
    for x in rep["findings"]:
        groups.setdefault((x["severity"], x["check"]), []).append(x)
    for (sev, check), xs in sorted(groups.items()):
        if len(xs) > 5:
            out.append("  %s %s x%d: %s (+%d more)" % (sev, check, len(xs), ", ".join(x["path"] for x in xs[:3]),
                                                      len(xs) - 3))
        else:
            out.extend("  %s %s: %s — %s" % (sev, check, x["path"], x["detail"]) for x in xs)
    out.append("RESULT: " + ("FAIL" if c["fail"] else "WARN" if c["warn"] else "PASS"))
    return "\n".join(out)


def migrate(root, category: str, mode: str) -> int:
    """Insert (write) or remove (revert) one **Type:** line per file in one category."""
    root = Path(root)
    done, skipped, refused = 0, 0, []
    for f in [f for f in collect(root) if in_category(f, category)]:
        data = f["path"].read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            refused.append((f["rel"], "not UTF-8"))
            continue
        h = parse_header(text)
        lines = h["lines"]
        if h["h1"] is None:
            refused.append((f["rel"], "no H1"))
            continue
        typed = [i for i, k, _ in h["keys"] if k == "Type"]
        if mode == "revert":
            others = sorted({k for _, k, _ in h["keys"] if k in V2_KEYS and k != "Type"})
            if not typed:
                skipped += 1
            elif others or len(typed) > 1:
                refused.append((f["rel"], "other v2 keys present: %s" % (others or ["Type x%d" % len(typed)])))
            else:
                f["path"].write_bytes("\n".join(lines[:typed[0]] + lines[typed[0] + 1:]).encode("utf-8"))
                done += 1
            continue
        if typed:
            skipped += 1
            continue
        pos = run_start(h)
        new = lines[:pos] + ["**Type:** " + f["default_type"]] + lines[pos:]
        if "\n".join(new[:pos] + new[pos + 1:]).encode("utf-8") != data:
            refused.append((f["rel"], "removing the line would not reproduce the original bytes"))
            continue
        if mode == "write":
            f["path"].write_bytes("\n".join(new).encode("utf-8"))
        else:
            print("  +**Type:** %s  %s:%d" % (f["default_type"], f["rel"], pos + 1))
        done += 1
    verb = {"dry-run": "would insert", "write": "inserted", "revert": "removed"}[mode]
    print("migrate %s %s: %d %s · %d skipped · %d refused" % (mode, category, done, verb, skipped, len(refused)))
    for rel, why in refused:
        print("  REFUSED %s — %s" % (rel, why))
    return 1 if refused else 0


def capture_baseline(root) -> int:
    root = Path(root)
    p = baseline_path(root)
    if not p.is_file():
        print("FATAL: %s not found" % p, file=sys.stderr)
        return 1
    base = json.loads(p.read_text(encoding="utf-8"))
    rep = lint(root)
    base["lint"] = {"captured": date.today().isoformat(), "over_soft_budget": rep["counts"]["over_soft_budget"]}
    p.write_text(json.dumps(base, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("baseline: lint.over_soft_budget = %d (captured %s)" % (base["lint"]["over_soft_budget"],
                                                                 base["lint"]["captured"]))
    return 0


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # usage errors are FATAL (1); 2 means WARN here
        self.print_usage(sys.stderr)
        print("FATAL: " + message, file=sys.stderr)
        sys.exit(1)


def main(argv=None) -> int:
    ap = _Parser(description="Lint KB/wiki against header contract v2 (read-only unless --migrate/--capture-baseline).")
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    ap.add_argument("--category", help="one wiki folder, or _root for KB/wiki/_index.md")
    ap.add_argument("--rule", default="contract", choices=list(RULES) + ["all"])
    ap.add_argument("--contract", action="store_true", help="print CONTRACT and exit")
    ap.add_argument("--capture-baseline", action="store_true", help="write the baseline lint key")
    ap.add_argument("--migrate", choices=("dry-run", "write", "revert"), help="requires --category")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()

    if args.contract:
        print(json.dumps(CONTRACT, ensure_ascii=False, indent=1))
        return 0
    wiki = root / "KB" / "wiki"
    if not wiki.is_dir():
        print("FATAL: %s not found" % wiki, file=sys.stderr)
        return 1
    if args.category and args.category != "_root" and not (wiki / args.category).is_dir():
        print("FATAL: no category %r under %s" % (args.category, wiki), file=sys.stderr)
        return 1
    if args.migrate:
        if not args.category:
            print("FATAL: --migrate requires --category NAME|_root", file=sys.stderr)
            return 1
        return migrate(root, args.category, args.migrate)
    if args.capture_baseline:
        return capture_baseline(root)

    rep = lint(root, category=args.category, rule=args.rule)
    print(json.dumps(rep, ensure_ascii=False, indent=1) if args.json else render(rep))
    return exit_code(rep)


if __name__ == "__main__":
    sys.exit(main())
