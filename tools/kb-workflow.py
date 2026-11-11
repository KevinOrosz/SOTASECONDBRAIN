#!/usr/bin/env python3
"""Read-only review summaries and explicit, resumable Markdown-to-inbox imports. Stdlib only."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import kb_config

ROOT = Path(__file__).resolve().parent.parent
CHECKPOINT = 'KB/output/last-verify.json'


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT / 'tools' / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


kbw, kbe = load('kb-write.py'), load('kb-eval.py')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def measurement(root):
    report = kbe.run(root)
    binding = {'corpus': kbe.corpus_seal(root), 'eval': digest(root / 'KB/output/retrieval-eval.json'),
               'method': report['retrieval']['new']}
    return {'binding': binding, 'recall': report['new']['combined'], 'k': report['recall_at']}


def undo_health(root, rows):
    """Check currently landed proposals; historical reversed lands need not remain undoable."""
    states = {pid: meta.get('state') for pid, _, meta in kbw.proposals(root)}
    latest = {row['id']: row for row in rows if row['event'] == 'land'}
    issues, legacy = [], []
    for pid, row in latest.items():
        if states.get(pid) != 'landed':
            continue
        for path, sha in row.get('prior', {}).items():
            if not sha or not path.startswith('KB/wiki/'):
                continue
            if kbw.get_object(root, sha) is not None:
                continue
            entry = {'id': pid, 'path': path, 'sha256': sha}
            if kbw.git_bytes(root, path, sha) is not None:
                legacy.append(entry)
            else:
                issues.append(entry)
    return {'missing_or_corrupt': issues, 'legacy_git_required': legacy}


def signature_health(root):
    """Recheck stored signed receipts against the ledger and current trusted public keys."""
    checked, problems, prefix = 0, [], b''
    ledger = root / kbw.LEDGER
    for line in ledger.read_bytes().splitlines(keepends=True) if ledger.exists() else []:
        row = json.loads(line)
        if row.get('approval_mode') == 'ssh-signature':
            checked += 1
            try:
                receipt = row['approval']
                payload = json.loads(receipt['payload'])
                kbw.verify_signature(root, receipt['payload'].encode(), receipt['signature'].encode('ascii'), row['actor'])
                expected_prefix = hashlib.sha256(prefix).hexdigest() if prefix else None
                post = {p: sha for p, sha in row['files'].items() if not p.startswith('KB/inbox/')}
                if (payload['proposal'] != row['id'] or payload['owner'] != row['actor']
                        or payload.get("reinstate_reason") != row.get("reinstates", {}).get("reason")
                        or payload['ledger_hash'] != expected_prefix or payload['post'] != post):
                    raise ValueError('signed payload does not match ledger position, identity or postimages')
            except (OSError, ValueError, KeyError, kbw.Fail) as exc:
                problems.append({'seq': row.get('seq'), 'error': str(exc)})
        prefix += line
    return {'checked': checked, 'signature_failures': problems}


def brief(root, since):
    kbw.configure(root)
    rows = kbw.read_ledger(root)
    if since < 0 or since > len(rows):
        raise ValueError("--since must be a ledger sequence between 0 and the current head")
    def check():
        if list((root / kbw.OPS).glob("*.json")) or kbw.load_seal(root) is None or kbw.drift(root, rows):
            raise ValueError("incomplete operation, missing seal, or wiki drift; run make verify")
    check()
    snapshot = state_hash(root)
    def event(row):
        return {k: row[k] for k in ("seq", "event", "id", "origin", "actor", "ts")} | {
            "source": kbw.LEDGER + "#L" + str(row["seq"])}
    changes = [event(row) | {"fact_change": row.get("fact_change"), "reason": row["reason"],
                             "reinstates": row.get("reinstates")}
               for row in rows[since:] if row["event"] in ("land", "unland")
               and (row.get("fact_change") or row.get("undoes_land") or row["origin"].startswith("correction:"))]
    reg = kb_config.path(root, "regressions")
    report = kbe.regressions(root, reg)
    if report["invalid"]:
        raise ValueError("invalid regression file; run make verify")
    pending = [{"id": pid, "source": rel, "kind": meta["kind"]} for pid, rel, meta in kbw.proposals(root)
               if meta["state"] == "open"]
    hashes = {path: value for row in rows for path, value in row["files"].items()}
    for item in pending:
        if hashes.get(item["source"]) != digest(root / item["source"]):
            raise ValueError("pending proposal differs from its ledger entry: " + item["id"])
    withdrawn = [{"path": path, "claim": claim, "decision": event(row)} for (path, claim), row
                 in kbw.withdrawn_claims(rows).items()]
    reviews = kbw.fact_reviews(root, rows)
    changed_paths = set()
    for row in rows[since:]:
        change = row.get("fact_change")
        if not change and row.get("undoes_land"):
            change = rows[row["undoes_land"] - 1].get("fact_change")
        if change:
            changed_paths.add(change["path"])
    current = [{"source": path, "claim": kbw.claim_of((root / path).read_text())}
               for path in sorted(changed_paths) if (root / path).is_file() and kbw.kblint.read_meta(root / path)["type"] == "fact"]
    check()
    if snapshot != state_hash(root):
        raise ValueError("inputs changed during brief; retry")
    return {"since": since, "through": len(rows), "changes": changes, "withdrawn": withdrawn,
            "current_facts": current, "pending": pending, "unresolved": reviews,
            "awaiting_replay": [{"id": cid, "source": str(reg.relative_to(root))} for cid in report["unchecked_ids"]],
            "failed_cases": report["failures"]}


def status(root):
    kbw.configure(root)
    rows = kbw.read_ledger(root)
    props = [{'id': pid, 'kind': meta['kind'], 'state': meta['state']}
             for pid, _, meta in kbw.proposals(root) if meta['state'] == 'open']
    corrections = []
    for path in sorted((root / 'KB/inbox/_corrections').glob('C-*/record.json')):
        rec = json.loads(path.read_text())
        if rec['stage'] not in ('landed', 'killed', 'failed', 'flagged'):
            corrections.append({k: rec.get(k) for k in ('cid', 'stage', 'await')})
    checkpoint = json.loads((root / CHECKPOINT).read_text()) if (root / CHECKPOINT).exists() else None
    seq = checkpoint['ledger_seq'] if checkpoint else 0
    prefix = rows[:seq]
    prefix_hash = hashlib.sha256(json.dumps(prefix, sort_keys=True).encode()).hexdigest()
    trusted = bool(checkpoint and len(prefix) == seq and prefix_hash == checkpoint.get('ledger_prefix_hash'))
    changes = [{k: row.get(k) for k in ('seq', 'ts', 'event', 'id', 'actor', 'approval_mode')}
               for row in rows if row['event'] in ('land', 'unland', 'adopt', 'reseal')
               and (not trusted or row['seq'] > seq)]
    cutoff = (datetime.now() - timedelta(days=7)).isoformat()
    week = [row for row in rows if row.get('ts', '') >= cutoff and row['event'] in ('land', 'unland')]
    reg = kb_config.path(root, 'regressions')
    regressions = kbe.regressions(root, reg) if reg.exists() else {'error': 'regression file missing'}
    current = measurement(root)
    previous = checkpoint.get('measurement') if trusted else None
    comparable = bool(previous and previous['binding'] == current['binding'])
    return {'pending': props, 'corrections': corrections, 'changes_since_verify': changes,
            'last_verify': checkpoint.get('at') if checkpoint else None, 'checkpoint_matches_ledger': trusted,
            'weekly': {event: sum(row['event'] == event for row in week) for event in ('land', 'unland')},
            'undo': undo_health(root, rows), 'signatures': signature_health(root), 'regressions': regressions,
            'retrieval': dict(current, comparison='same corpus, eval and method' if comparable else 'no comparable baseline',
                              delta=current['recall'] - previous['recall'] if comparable else None),
            'unfinished_operations': [p.name for p in sorted((root / kbw.OPS).glob('*.json'))],
            'note': 'Verification checks consistency; it does not record human review or authenticate actors.'}


def checkpoint(root, expected=None):
    rows = kbw.read_ledger(root)
    current = state_hash(root)
    if expected is not None and current != expected:
        raise ValueError('instance changed during verification; checkpoint not saved')
    data = {'at': datetime.now(timezone.utc).isoformat(), 'ledger_seq': len(rows),
            'ledger_prefix_hash': hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest(),
            'state_hash': current, 'measurement': measurement(root)}
    target = root / CHECKPOINT
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=target.parent, prefix='.verify-')
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, indent=2)
            stream.write('\n')
        os.replace(name, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return data


def state_hash(root):
    paths = set()
    for directory in ('KB/wiki', 'KB/RAW', 'KB/inbox', 'tools'):
        paths.update(p for p in (root / directory).rglob('*') if p.is_file()
                     and '__pycache__' not in p.parts and p.name != '.lock')
    paths.update(root / p for p in ('KB/kb.json', 'KB/output/retrieval-eval.json'))
    paths.add(kb_config.path(root, 'regressions'))
    return hashlib.sha256(json.dumps({str(p.relative_to(root)): digest(p) for p in sorted(paths)},
                                     sort_keys=True).encode()).hexdigest()


def adopt(root, a):
    source = Path(a.folder).resolve()
    if not source.is_dir():
        raise ValueError('source folder does not exist')
    kbw.configure(root)
    kbw.check_agent(root, a.agent)
    if a.category not in {p.name for p in (root / 'KB/wiki').iterdir() if p.is_dir()}:
        raise ValueError('--category must name an existing wiki category')
    if a.confidence not in kbw.kblint.CONFIDENCE:
        raise ValueError('--confidence must be an existing confidence value')
    selected = sorted(source.rglob('*.md'))
    if a.select:
        selected = [source / name for name in a.select]
    if a.limit:
        selected = selected[:a.limit]
    existing = {ref for _, _, meta in kbw.proposals(root) for ref in meta.get('source_refs', [])}
    fact_id = getattr(a, 'fact_id', None)
    if fact_id and (len(selected) != 1 or not kbw.SLUG_RE.fullmatch(fact_id)):
        raise ValueError('--fact-id requires one selected note and a valid page stem')
    rows = kbw.read_ledger(root)
    items = []
    for path in selected:
        item = {'source': str(path), 'state': 'preview', 'warnings': []}
        items.append(item)
        try:
            if path.is_symlink() or not path.resolve().is_relative_to(source) or any(
                    p.is_symlink() for p in path.parents if p != source and source in p.parents):
                raise ValueError('symlinks and paths outside the selected folder are refused')
            if path.suffix.lower() != '.md' or not path.is_file():
                raise ValueError('select a regular Markdown file')
            raw = path.read_bytes()
            text = raw.decode('utf-8')
            if not text.strip():
                raise ValueError('empty note')
            if text.startswith('---'):
                raise ValueError('frontmatter needs manual conversion; original left untouched')
            sha = hashlib.sha256(raw).hexdigest()
            raw_rel = 'imports/' + sha + '.md'
            ref = 'raw:' + raw_rel
            item.update(sha256=sha, raw_path='KB/RAW/' + raw_rel)
            target_stem = fact_id or path.stem
            prior = kbw.withdrawn_claims(rows).get(('KB/wiki/%s/%s.md' % (a.category, target_stem), kbw.claim_of(text)))
            if prior:
                item.update(state='withdrawn', decision_seq=prior['seq'])
                item['warnings'].append('Withdrawn claim; review the ledger before proposing reinstatement')
                continue
            if ref in existing:
                item['state'] = 'already-proposed'
                continue
            if not re.search(r'^# ', text, re.M):
                text = '# ' + path.stem.replace('-', ' ') + '\n\n' + text
                item['warnings'].append('Title inferred from filename; review it')
            if '## Core Claim' not in text:
                item['warnings'].append('Missing Core Claim; author it before landing')
            if not fact_id and len(text.split()) < 100:
                item['warnings'].append('Below 100 words; may not pass land validation')
            for link in re.findall(r'\[\[([^]|#]+)', text):
                if kbw.article_path(root, link) is None:
                    item['warnings'].append('Review unresolved link: ' + link)
            slug = re.sub('[^a-z0-9]+', '-', path.stem.lower()).strip('-')[:45] or 'note'
            slug += '-' + sha[:10]
            slug = fact_id or slug
            item['slug'] = slug
            if not a.apply:
                continue
            target = root / 'KB/RAW' / raw_rel
            if target.is_symlink() or not target.resolve().is_relative_to((root / 'KB/RAW').resolve()):
                raise ValueError('source snapshot destination escapes RAW')
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.read_bytes() != raw:
                raise ValueError('source snapshot collision; refusing overwrite')
            if not target.exists():
                with target.open('xb') as stream:
                    stream.write(raw)
            with tempfile.TemporaryDirectory(prefix='kb-import-') as temp:
                body = Path(temp) / 'body.md'
                body.write_text(text, encoding='utf-8')
                args = kbw.parser().parse_args(['put', '--agent', a.agent, '--kind', 'article', '--slug', slug,
                    '--category', a.category, '--confidence', a.confidence, '--source-ref', ref,
                    '--origin', 'skill:adopt-folder', '--body-file', str(body)])
                if fact_id:
                    args.type = 'fact'
                    if kbw.article_path(root, fact_id):
                        args.supersedes = 'wiki:' + fact_id
                result = kbw.cmd_put(root, args)
            item.update(state='proposed', id=result['id'])
            existing.add(ref)
        except (OSError, ValueError, kbw.Fail) as exc:
            item.update(state='blocked', error=str(exc))
    return {'mode': 'apply' if a.apply else 'preview', 'items': items,
            'note': 'Originals are unchanged. Apply snapshots sources and creates inbox proposals only; interrupted imports can be rerun.'}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('verb', choices=('brief', 'status', 'checkpoint', 'state-hash', 'adopt-folder', 'undo-health', 'signature-health'))
    ap.add_argument('folder', nargs='?')
    ap.add_argument('--root', default=str(ROOT))
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--expected-state')
    ap.add_argument('--since', type=int, default=0, help='brief: exclusive ledger cursor')
    ap.add_argument('--fact-id', help='import one note as a fact with this stable page stem')
    ap.add_argument('--agent')
    ap.add_argument('--category')
    ap.add_argument('--confidence')
    ap.add_argument('--select', action='append', help='relative Markdown path; repeat to select files')
    ap.add_argument('--limit', type=int, help='small test batch size')
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()
    try:
        if not (root / 'KB/wiki').is_dir():
            raise ValueError('no instance; run bootstrap first')
        if a.verb == 'state-hash':
            print(state_hash(root))
            return 0
        if a.verb == 'adopt-folder':
            if not all((a.folder, a.agent, a.category, a.confidence)):
                raise ValueError('import requires folder, --agent, --category and --confidence')
            if a.limit is not None and a.limit < 1:
                raise ValueError('--limit must be positive')
            out = adopt(root, a)
        elif a.verb == 'brief':
            out = brief(root, a.since)
        elif a.verb == 'checkpoint':
            out = checkpoint(root, a.expected_state)
        elif a.verb == 'signature-health':
            out = signature_health(root)
        elif a.verb == 'undo-health':
            out = undo_health(root, kbw.read_ledger(root))
        else:
            out = status(root)
        if a.verb == 'status' and not a.json:
            print('Pending: %d proposals; %d corrections' % (len(out['pending']), len(out['corrections'])))
            print('Last verify: %s; ledger checkpoint matches: %s' % (out['last_verify'] or 'never', out['checkpoint_matches_ledger']))
            for row in out['changes_since_verify']:
                print('  #{seq} {event} {id} actor={actor} approval={approval_mode}'.format(**row))
            print('Past 7 days: %d lands, %d unlands' % (out['weekly']['land'], out['weekly']['unland']))
            print('Regressions: %s failed, %s invalid; answer UNCHECKED: %s' % (out['regressions'].get('failed', '?'), out['regressions'].get('invalid', '?'), out['regressions'].get('unchecked_ids', [])))
            if out['unfinished_operations']:
                print('Unfinished operations: ' + ', '.join(out['unfinished_operations']))
            print('Signed receipts: %d checked, %d failures' % (out['signatures']['checked'], len(out['signatures']['signature_failures'])))
            print('Undo missing/corrupt: %d; legacy git: %d' % (len(out['undo']['missing_or_corrupt']), len(out['undo']['legacy_git_required'])))
            print('Retrieval recall@%s: %.3f; %s' % (out['retrieval']['k'], out['retrieval']['recall'], out['retrieval']['comparison']))
            for row in out['pending'] + out['corrections']:
                print('  ' + json.dumps(row))
            print(out['note'])
        else:
            print(json.dumps(out, indent=2))
        return int(bool(out.get('signature_failures')) or bool(out.get('signatures', {}).get('signature_failures'))
                   or bool(out.get('missing_or_corrupt')) or bool(out.get('undo', {}).get('missing_or_corrupt'))
                   or bool(out.get('regressions', {}).get('error')) or bool(out.get('regressions', {}).get('failed')) or bool(out.get('regressions', {}).get('invalid'))
                   or bool(out.get('unfinished_operations')) or any(i['state'] == 'blocked' for i in out.get('items', [])))
    except (OSError, ValueError, KeyError, kbw.Fail) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
