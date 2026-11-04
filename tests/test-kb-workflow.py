#!/usr/bin/env python3
"""Feedback upgrades: real fixture operations, read-only contracts and refusal paths."""
import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import kb_testkit


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT / 'tools' / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


wf = load('kb-workflow.py')
kw = wf.kbw
kc = load('kb-correct.py')
graph = load('kb-graph-query.py')


class Workflow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = kb_testkit.fixture(self.base, indexes=True, regressions=True)
        kw.configure(self.root)
        kw.cmd_seal(self.root, argparse.Namespace(reseal=False))
        self.body = self.base / 'body.md'
        self.body.write_text('# Fresh note\n\n## Core Claim\nA sourced claim.\n\n## Evidence\n' + 'Supported by the source notes and checked before approval. ' * 15)

    def tearDown(self):
        self.tmp.cleanup()

    def proposal(self):
        a = kw.parser().parse_args(['put', '--agent', 'RESEARCHER', '--kind', 'article', '--slug', 'fresh-note',
            '--category', 'alpha', '--confidence', 'moderate', '--source-ref', 'raw:source-one.md', '--body-file', str(self.body)])
        return kw.cmd_put(self.root, a)['id']

    def args(self, source, **kwargs):
        d = dict(folder=str(source), agent='RESEARCHER', category='alpha', confidence='moderate',
                 select=None, limit=None, apply=False)
        d.update(kwargs)
        return argparse.Namespace(**d)

    def test_status_and_batch_review_write_nothing(self):
        pid = self.proposal()
        before = kb_testkit.tree_digest(self.root)
        report = wf.status(self.root)
        self.assertEqual(report['pending'][0]['id'], pid)
        a = kw.parser().parse_args(['list', '--diff'])
        review = kw.cmd_list(self.root, a)
        self.assertIn('Fresh note', review['items'][0]['preview']['diff'])
        self.assertEqual(kb_testkit.tree_digest(self.root), before)

    def test_checkpoint_comparison_and_ledger_tamper(self):
        wf.checkpoint(self.root)
        self.assertEqual(wf.status(self.root)['retrieval']['delta'], 0)
        self.proposal()
        wf.checkpoint(self.root)
        ledger = self.root / kw.LEDGER
        ledger.write_text(ledger.read_text().replace('RESEARCHER', 'OTHER'))
        self.assertFalse(wf.status(self.root)['checkpoint_matches_ledger'])

    def test_checkpoint_refuses_changed_inputs(self):
        stamp = wf.state_hash(self.root)
        self.proposal()
        with self.assertRaisesRegex(ValueError, 'changed'):
            wf.checkpoint(self.root, stamp)
        self.assertFalse((self.root / wf.CHECKPOINT).exists())

    def test_changed_eval_is_not_comparable(self):
        wf.checkpoint(self.root)
        p = self.root / 'KB/output/retrieval-eval.json'
        d = json.loads(p.read_text()); d['note'] = 'changed benchmark'; p.write_text(json.dumps(d))
        self.assertIsNone(wf.status(self.root)['retrieval']['delta'])

    def test_import_preview_apply_retry_and_source_preservation(self):
        source = self.base / 'notes'; source.mkdir()
        data = self.body.read_bytes(); (source / 'note.md').write_bytes(data)
        before = kb_testkit.tree_digest(self.root)
        preview = wf.adopt(self.root, self.args(source))
        self.assertEqual(preview['items'][0]['state'], 'preview')
        self.assertEqual(before, kb_testkit.tree_digest(self.root))
        wiki = kb_testkit.tree_digest(self.root / 'KB/wiki')
        applied = wf.adopt(self.root, self.args(source, apply=True))
        item = applied['items'][0]
        self.assertEqual(item['state'], 'proposed', item)
        self.assertEqual((self.root / item['raw_path']).read_bytes(), data)
        self.assertEqual((source / 'note.md').read_bytes(), data)
        self.assertEqual(wiki, kb_testkit.tree_digest(self.root / 'KB/wiki'))
        self.assertEqual(wf.adopt(self.root, self.args(source, apply=True))['items'][0]['state'], 'already-proposed')

    def test_import_refuses_escape_symlink_and_frontmatter(self):
        source = self.base / 'notes'; source.mkdir()
        (source / 'link.md').symlink_to(self.body)
        (source / 'front.md').write_text('---\ntitle: private\n---\nnotes')
        report = wf.adopt(self.root, self.args(source, apply=True))
        self.assertTrue(all(i['state'] == 'blocked' for i in report['items']))
        report = wf.adopt(self.root, self.args(source, select=['../body.md'], apply=True))
        self.assertEqual(report['items'][0]['state'], 'blocked')

    def test_import_requires_existing_category(self):
        with self.assertRaisesRegex(ValueError, 'existing'):
            wf.adopt(self.root, self.args(self.base, category='invented'))

    def test_next_invalid_id_and_terminal(self):
        with self.assertRaises(kc.Fail):
            kc.cmd_next(self.root, argparse.Namespace(cid='../escape', write_template=False))
        folder = self.root / kc.CORR / 'C-0001'; folder.mkdir(parents=True)
        (folder / 'record.json').write_text(json.dumps({'cid':'C-0001','stage':'killed','await':None}))
        self.assertIsNone(kc.cmd_next(self.root, argparse.Namespace(cid='C-0001', write_template=False))['next'])

    def test_next_conflict_read_only_and_template_no_overwrite(self):
        folder = self.root / kc.CORR / 'C-0001'; folder.mkdir(parents=True)
        (folder / 'record.json').write_text(json.dumps({'cid':'C-0001','stage':'diagnosed','await':'conflict',
                                                      'points':['claim'], 'paragraphs':[]}))
        before = kb_testkit.tree_digest(self.root)
        a = argparse.Namespace(cid='C-0001', write_template=False)
        out = kc.cmd_next(self.root, a)
        self.assertEqual(set(out['packet']), kc.PACKETS['conflict'])
        self.assertEqual(kb_testkit.tree_digest(self.root), before)
        a.write_template = True
        kc.cmd_next(self.root, a)
        with self.assertRaisesRegex(kc.Fail, 'overwrite'):
            kc.cmd_next(self.root, a)

    def test_stemming_and_explicit_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(ROOT / 'examples/demo-wiki', root / 'KB/wiki')
            shutil.copytree(ROOT / 'examples/demo-raw', root / 'KB/RAW')
            for tool in ('kb-index.py','kb-graph.py'):
                subprocess.run([sys.executable, str(ROOT / 'tools' / tool), '--root', str(root)], check=True, capture_output=True)
            g = graph.Graph(root)
            out = graph.verb_search(root, g, 'compost', 8)
            self.assertIn('composting', [r['stem'] for r in out['results']])
            self.assertTrue(out['retrieval']['stemming'])
            with mock.patch.object(graph, 'build_fts', return_value=None):
                out = graph.verb_search(root, g, 'compost', 8)
            self.assertFalse(out['retrieval']['stemming'])
            self.assertIn('unavailable', out['degraded'])

    def test_confirmation_refuses_non_tty(self):
        with mock.patch.object(sys.stdin, 'isatty', return_value=False):
            with self.assertRaisesRegex(kw.Fail, 'terminal'):
                kw.confirm_action(argparse.Namespace(confirm=True), 'test')

    def test_undo_health_detects_missing_objects(self):
        # Existing-page supersede needs a preimage for undo.
        self.body.write_text(kb_testkit.WIKI['alpha/first.md'] + '\n' + 'Added source detail. ' * 40)
        a = kw.parser().parse_args(['put','--agent','RESEARCHER','--kind','article','--slug','revise',
            '--supersedes','wiki:first','--confidence','moderate','--source-ref','raw:source-one.md','--body-file',str(self.body)])
        pid = kw.cmd_put(self.root, a)['id']
        kw.land_one(self.root, pid, False)
        row = kw.read_ledger(self.root)[-1]
        sha = row['prior']['KB/wiki/alpha/first.md']
        (self.root / kw.OBJECTS / sha).write_bytes(b'corrupt')
        self.assertTrue(wf.undo_health(self.root, kw.read_ledger(self.root))['missing_or_corrupt'])

    @unittest.skipUnless(shutil.which('ssh-keygen'), 'OpenSSH needed for optional signed approval')
    def test_signature_accepts_exact_land_rejects_drift_and_reuse(self):
        key = self.base / 'owner-key'
        subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(key)], check=True)
        allowed = self.base / 'allowed-signers'
        allowed.write_text('owner ' + key.with_suffix('.pub').read_text())
        config = self.root / 'KB/kb.json'
        config.write_text(json.dumps({'owner':'owner','agents':['RESEARCHER'],
                                     'require_signed_lands':True,'allowed_signers':str(allowed)}))
        pid = self.proposal()
        preview = kw.land_one(self.root, pid, True)
        payload = self.base / 'approval.json'; payload.write_text(preview['approval_payload'])
        subprocess.run(['ssh-keygen','-Y','sign','-f',str(key),'-n','kb-land',str(payload)], check=True, capture_output=True)
        a = kw.parser().parse_args(['land',pid,'--endorsed-by','owner','--signature',str(payload)+'.sig'])
        src = self.root / 'KB/RAW/source-one.md'; original = src.read_bytes(); src.write_bytes(original+b'\nchanged')
        with self.assertRaisesRegex(kw.Fail, 'signature invalid'):
            kw.cmd_land(self.root,a)
        src.write_bytes(original)
        kw.cmd_land(self.root,a)
        self.assertEqual(kw.read_ledger(self.root)[-1]['approval_mode'], 'ssh-signature')
        self.assertEqual(wf.signature_health(self.root), {'checked':1, 'signature_failures':[]})
        undo = kw.parser().parse_args(['unland',pid,'--endorsed-by','owner','--reason','test'])
        kw.cmd_unland(self.root,undo)
        self.assertEqual(wf.signature_health(self.root)['signature_failures'], [])
        with self.assertRaisesRegex(kw.Fail, 'signature invalid'):
            kw.cmd_land(self.root,a)
        ledger = self.root / kw.LEDGER
        rows = [json.loads(line) for line in ledger.read_text().splitlines()]
        signed = next(row for row in rows if row.get('approval_mode') == 'ssh-signature')
        signed['approval']['payload'] = signed['approval']['payload'].replace('fresh-note', 'forged-note')
        ledger.write_text(''.join(json.dumps(row, separators=(',', ':')) + '\n' for row in rows))
        self.assertTrue(wf.signature_health(self.root)['signature_failures'])

    def test_next_replay_judge_sequence_keeps_blind_packet(self):
        folder = self.root / kc.CORR / 'C-0001'; folder.mkdir(parents=True)
        rec = {'cid':'C-0001','stage':'reviewed','await':'replay', 'validate': {
            'base_overlay': str(self.root), 'runs': {'base': {'q':'question', 'overlay':'base', 'points':['SECRET GOLD']}}}}
        (folder / 'record.json').write_text(json.dumps(rec))
        a = argparse.Namespace(cid='C-0001', write_template=False)
        out = kc.cmd_next(self.root, a)
        self.assertEqual(out['next'], 'replay')
        self.assertNotIn('SECRET GOLD', json.dumps(out))
        (folder / 'results').mkdir()
        (folder / 'results/replay-base.md').write_text('answer')
        self.assertEqual(kc.cmd_next(self.root, a)['next'], 'judge')
        (folder / 'results/judge-base.json').write_text('{}')
        self.assertEqual(kc.cmd_next(self.root, a)['next'], 'validate')
        rec['validate']['binding'] = {'old':'binding'}
        (folder / 'record.json').write_text(json.dumps(rec))
        with mock.patch.object(kc, 'stale_keys', return_value=['tools']):
            self.assertEqual(kc.cmd_next(self.root, a)['next'], 'validate')

    def test_batch_review_reports_bad_proposal_without_mutation(self):
        self.body.write_text('# Too short\n\nA short note.')
        self.proposal()
        before = kb_testkit.tree_digest(self.root)
        result = kw.cmd_list(self.root, kw.parser().parse_args(['list','--diff']))
        self.assertIn('review_error', result['items'][0])
        self.assertEqual(before, kb_testkit.tree_digest(self.root))

    def test_bootstrap_preserves_existing_policy_and_discovers_souls(self):
        package = self.base / 'fresh'
        shutil.copytree(ROOT, package, ignore=shutil.ignore_patterns('.git','KB','evals','__pycache__'))
        cmd = ['bash', str(package / 'bootstrap.sh'), '--owner', 'tester', '--no-verify']
        subprocess.run(cmd, check=True, capture_output=True)
        config = package / 'KB/kb.json'; seeds = package / 'evals/regressions.jsonl'
        self.assertIn('GURU', kw.agent_names(package))
        self.assertIn('WIZARD', kw.agent_names(package))
        self.assertEqual([json.loads(x)['status'] for x in seeds.read_text().splitlines()], ['dormant'])
        data = json.loads(config.read_text()); data['agents_glob'] = 'agents/*/soul.md'
        config.write_text(json.dumps(data)); seeds.write_text(seeds.read_text() + '\n')
        before = (config.read_bytes(), seeds.read_bytes())
        subprocess.run(cmd, check=True, capture_output=True)
        self.assertEqual(before, (config.read_bytes(), seeds.read_bytes()))

    def test_signed_policy_refuses_missing_signature(self):
        p = self.root / 'KB/kb.json'
        p.write_text(json.dumps({'owner':'owner','agents':['RESEARCHER'],'require_signed_lands':True}))
        pid = self.proposal()
        a = kw.parser().parse_args(['land',pid,'--endorsed-by','owner'])
        with self.assertRaisesRegex(kw.Fail, 'signed land required'):
            kw.cmd_land(self.root,a)


if __name__ == '__main__':
    unittest.main()
