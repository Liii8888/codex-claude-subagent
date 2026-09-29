from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest import mock

import test_runner as base

runtime = base.runtime


class ContextTests(unittest.TestCase):
    def setUp(self):
        base.RuntimeTests.setUp(self)
        self.registry = mock.patch.object(runtime, 'PROJECT_CONTEXT_REGISTRY', self.root / 'registry.json')
        self.registry.start()

    def tearDown(self):
        self.registry.stop()
        base.RuntimeTests.tearDown(self)

    def project(self, name):
        p = self.root / name
        p.mkdir()
        (p / 'AGENTS.md').write_text(f'Project rule: {name}-RULE\n')
        (p / 'CONTEXT.md').write_text(
            f'# {name}\n\n## 项目概况\n\nCurrent marker: {name}-CURRENT\n'
            '<!-- /project-context -->\n\nHistorical marker: STALE-HISTORY\n'
        )
        return p

    def run_in(self, cwd, resume=None):
        job = runtime.reserve_job(kind='task', mode='read', cwd=str(cwd),
                                  model='sonnet', effort='low', permission_mode='auto')
        prompt = self.root / 'task.txt'
        prompt.write_text('Report the current project marker.')
        self.assertEqual(runtime.run_job(job['id'], prompt_file=prompt, resume_from=resume), 0)
        return runtime.read_job(job['id'])

    def test_two_workspaces_receive_their_own_rules_and_current_overview(self):
        a, b = self.project('alpha'), self.project('beta')
        (self.root / 'AGENTS.md').write_text('Shared workspace rule.')
        for selected, other in ((a, b), (b, a)):
            job = self.run_in(selected)
            d = runtime.job_dir(job['id'])
            prompt = (d / 'prompt.txt').read_text()
            self.assertIn(selected.name + '-RULE', prompt)
            self.assertIn(selected.name + '-CURRENT', prompt)
            self.assertIn('Shared workspace rule.', prompt)
            self.assertLess(prompt.index('Report the current project marker.'),
                            prompt.index('Workspace context loaded'))
            self.assertNotIn(other.name + '-RULE', prompt)
            self.assertNotIn('STALE-HISTORY', prompt)
            self.assertTrue(job['cwd_verified'])
            self.assertEqual(job['cwd'], str(selected.resolve()))
            self.assertEqual(len(job['context_sources']), 3)
            self.assertEqual((d / 'context.json').stat().st_mode & 0o777, 0o600)
            self.assertEqual(len(json.loads((d / 'context.json').read_text())['sources']), 3)

    def test_native_resume_gets_updated_context_in_the_new_turn(self):
        p = self.project('alpha')
        first = self.run_in(p)
        (p / 'CONTEXT.md').write_text('Updated project marker: alpha-CHANGED\n')
        second = self.run_in(p, first['id'])
        prompt = (runtime.job_dir(second['id']) / 'prompt.txt').read_text()
        self.assertIn('alpha-CHANGED', prompt)
        self.assertLess(prompt.index('Report the current project marker.'),
                        prompt.index('Workspace context loaded'))
        self.assertNotIn('alpha-CURRENT', prompt)
        self.assertEqual(first['session_id'], second['session_id'])
        self.assertNotEqual(first['context_sources'][-1]['sha256'], second['context_sources'][-1]['sha256'])

    def test_registered_overview_and_worktree_mapping_win_over_fallback(self):
        canonical = self.project('canonical')
        checkout = self.project('checkout')
        nested = checkout / 'src'
        nested.mkdir()
        (canonical / 'STATUS.md').write_text('Canonical registered facts.')
        runtime.PROJECT_CONTEXT_REGISTRY.write_text(json.dumps({'projects': [{
            'root': str(canonical), 'context': 'STATUS.md', 'worktrees': [str(checkout)],
        }]}))
        content, manifest, project = runtime.workspace_context(str(nested))
        self.assertIn('Canonical registered facts.', content)
        self.assertIn('checkout-RULE', content)
        self.assertNotIn('canonical-RULE', content)
        self.assertNotIn('checkout-CURRENT', content)
        self.assertEqual(project, str(checkout.resolve()))
        self.assertEqual(manifest[-1]['path'], str((canonical / 'STATUS.md').resolve()))

    def test_missing_registered_context_fails_before_claude_starts(self):
        p = self.project('alpha')
        runtime.PROJECT_CONTEXT_REGISTRY.write_text(json.dumps({'projects': [{
            'root': str(p), 'context': 'MISSING.md',
        }]}))
        job = runtime.reserve_job(kind='task', mode='read', cwd=str(p),
                                  model='sonnet', effort='low', permission_mode='auto')
        task = self.root / 'task.txt'
        task.write_text('work')
        with mock.patch.object(runtime.subprocess, 'Popen') as spawn:
            with self.assertRaisesRegex(runtime.RuntimeErrorWithHint, 'required workspace context'):
                runtime.run_job(job['id'], prompt_file=task, resume_from=None)
        spawn.assert_not_called()
        self.assertEqual(runtime.read_job(job['id'])['state'], 'failed')

    def test_context_requires_allowed_regular_bounded_sources(self):
        p = self.project('alpha')
        rule = p / 'AGENTS.md'
        rule.unlink()
        rule.symlink_to('/etc/hosts')
        with self.assertRaisesRegex(runtime.RuntimeErrorWithHint, 'outside'):
            runtime.workspace_context(str(p))
        rule.unlink()
        os.mkfifo(rule)
        with self.assertRaisesRegex(runtime.RuntimeErrorWithHint, 'regular file'):
            runtime.workspace_context(str(p))
        rule.unlink()
        rule.write_text('x' * (runtime.WORKSPACE_CONTEXT_MAX_BYTES + 1))
        with self.assertRaisesRegex(runtime.RuntimeErrorWithHint, '128 KiB'):
            runtime.workspace_context(str(p))

    def test_overview_with_missing_end_marker_is_not_silently_truncated(self):
        p = self.project('alpha')
        (p / 'CONTEXT.md').write_text('## 项目概况\nMissing end marker')
        with self.assertRaisesRegex(runtime.RuntimeErrorWithHint, 'end marker'):
            runtime.workspace_context(str(p))

    def test_wrong_native_start_directory_is_rejected(self):
        p = self.project('alpha')
        job = runtime.reserve_job(kind='task', mode='read', cwd=str(p),
                                  model='sonnet', effort='low', permission_mode='auto')
        with self.assertRaisesRegex(runtime.RuntimeErrorWithHint, 'different working directory'):
            runtime.verify_initial_cwd(job, str(self.root))
        self.assertFalse(runtime.read_job(job['id'])['cwd_verified'])


if __name__ == '__main__':
    unittest.main()
