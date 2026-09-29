from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
import unittest
from unittest import mock

import test_runner as base

runtime = base.runtime


class ConcurrencyTests(unittest.TestCase):
    setUp = base.RuntimeTests.setUp
    tearDown = base.RuntimeTests.tearDown

    def reserve(self, cwd=None, mode='read'):
        return runtime.reserve_job(kind='task', mode=mode, cwd=str(cwd or self.root),
                                   model='sonnet', effort='low', permission_mode='auto')

    def checkout(self, name, worktree=False):
        path = self.root / name
        path.mkdir()
        if worktree:
            (path / '.git').write_text('gitdir: ../shared-git/worktrees/' + name)
        else:
            (path / '.git').mkdir()
        return path

    def test_four_independent_checkouts_can_all_write(self):
        jobs = [self.reserve(self.checkout(str(i), worktree=i > 0), 'write') for i in range(4)]
        self.assertEqual(len({j['write_scope'] for j in jobs}), 4)
        with self.assertRaisesRegex(runtime.RuntimeErrorWithHint, 'concurrency limit'):
            self.reserve(self.checkout('fifth'), 'write')

    def test_sibling_subdirectories_in_one_checkout_cannot_both_write(self):
        checkout = self.checkout('project')
        a, b = checkout / 'a', checkout / 'b'
        a.mkdir(); b.mkdir()
        self.reserve(a, 'write')
        with self.assertRaisesRegex(runtime.RuntimeErrorWithHint, 'Write workspace'):
            self.reserve(b, 'write')
        self.reserve(b, 'read')

    def test_overlapping_paths_and_symlink_aliases_are_exclusive(self):
        parent = self.root / 'plain'
        child = parent / 'nested'
        child.mkdir(parents=True)
        alias = self.root / 'alias'
        alias.symlink_to(child, target_is_directory=True)
        for first, second in ((parent, child), (child, parent), (child, alias)):
            with self.subTest(first=first, second=second):
                job = self.reserve(first, 'write')
                with self.assertRaisesRegex(runtime.RuntimeErrorWithHint, 'Write workspace'):
                    self.reserve(second, 'write')
                runtime.update_job(job['id'], state='completed')

    def test_non_git_project_context_defines_shared_write_scope(self):
        project = self.root / 'project'
        a, b = project / 'a', project / 'b'
        a.mkdir(parents=True); b.mkdir()
        (project / 'CONTEXT.md').write_text('Shared project context.')
        first = self.reserve(a, 'write')
        self.assertEqual(first['write_scope'], str(project.resolve()))
        with self.assertRaisesRegex(runtime.RuntimeErrorWithHint, 'Write workspace'):
            self.reserve(b, 'write')

    def test_active_legacy_writer_without_scope_is_not_ignored(self):
        checkout = self.checkout('legacy')
        a, b = checkout / 'a', checkout / 'b'
        a.mkdir(); b.mkdir()
        first = self.reserve(a, 'write')
        first.pop('write_scope')
        runtime.write_json_atomic(runtime.job_record_path(first['id']), first)
        with self.assertRaisesRegex(runtime.RuntimeErrorWithHint, 'Write workspace'):
            self.reserve(b, 'write')

    def test_scope_is_rechecked_before_spawning(self):
        # A new common checkout boundary between reserve and run must not
        # let both earlier independent reservations start writing.
        a, b = self.root / 'a', self.root / 'b'
        a.mkdir(); b.mkdir()
        first = self.reserve(a, 'write')
        second = self.reserve(b, 'write')
        (self.root / '.git').mkdir()
        prompt = self.root / 'prompt.txt'
        prompt.write_text('Do not run this conflicting writer.')
        with mock.patch.object(runtime.subprocess, 'Popen') as spawn:
            with self.assertRaisesRegex(runtime.RuntimeErrorWithHint, 'Write workspace'):
                runtime.run_job(second['id'], prompt_file=prompt, resume_from=None)
        spawn.assert_not_called()
        self.assertEqual(runtime.read_job(first['id'])['state'], 'queued')
        self.assertEqual(runtime.read_job(second['id'])['state'], 'failed')

    def test_config_changes_do_not_rewrite_or_cancel_existing_jobs(self):
        jobs = [self.reserve() for _ in range(4)]
        before = {j['id']: runtime.job_record_path(j['id']).read_bytes() for j in jobs}
        configured = runtime.configure_concurrency(2)
        self.assertEqual(configured['max_concurrency'], 2)
        self.assertFalse(configured['active_jobs_changed'])
        for job in jobs:
            self.assertEqual(runtime.job_record_path(job['id']).read_bytes(), before[job['id']])
        with self.assertRaisesRegex(runtime.RuntimeErrorWithHint, 'concurrency limit'):
            self.reserve()
        runtime.configure_concurrency(8)
        self.reserve()
        self.assertNotIn('max_write_concurrency', json.loads(runtime.config_path().read_text()))

    def test_invalid_limit_does_not_change_saved_configuration(self):
        before = runtime.config_path().read_bytes()
        for value in (0, -1, True, 4.5, '4'):
            with self.subTest(value=value), self.assertRaises(runtime.RuntimeErrorWithHint):
                runtime.configure_concurrency(value)
            self.assertEqual(runtime.config_path().read_bytes(), before)

    def test_parallel_admission_never_exceeds_total_limit(self):
        command = [sys.executable, '-B', str(base.SCRIPT), 'reserve', '--kind', 'task',
                   '--mode', 'read', '--cwd', str(self.root), '--effort', 'low']
        processes = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                     for _ in range(8)]
        try:
            outputs = [process.communicate(timeout=10) for process in processes]
            accepted = [out.strip() for process, (out, _) in zip(processes, outputs) if process.returncode == 0]
            refused = [err for process, (_, err) in zip(processes, outputs) if process.returncode != 0]
            self.assertEqual(len(set(accepted)), 4)
            self.assertEqual(len(refused), 4)
            self.assertTrue(all('concurrency limit' in err for err in refused))
            self.assertEqual(len(runtime.active_jobs()), 4)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill(); process.wait()

    def test_four_workers_really_overlap_and_finish_without_losing_receipts(self):
        jobs = [self.reserve() for _ in range(4)]
        prompt = self.root / 'prompt.txt'
        prompt.write_text('Parallel worker fixture; no model request.')
        processes = []
        try:
            with mock.patch.dict(os.environ, {'FAKE_CLAUDE_SLEEP': '2'}):
                for job in jobs:
                    processes.append(subprocess.Popen(
                        [sys.executable, '-B', str(base.SCRIPT), 'run', '--job', job['id'],
                         '--prompt-file', str(prompt), '--receipt-only'],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                current = [runtime.read_job(j['id']) for j in jobs]
                if all(j['state'] == 'running' and runtime.process_alive(j.get('pid')) for j in current):
                    break
                time.sleep(.02)
            else:
                self.fail('Four live fixture workers never overlapped')
            with self.assertRaisesRegex(runtime.RuntimeErrorWithHint, 'concurrency limit'):
                self.reserve()
            for job, process in zip(jobs, processes):
                out, err = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0, err)
                self.assertEqual(json.loads(out)['state'], 'completed')
                self.assertEqual(runtime.read_job(job['id'])['state'], 'completed')
                self.assertTrue((runtime.job_dir(job['id']) / 'completion.json').is_file())
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    with contextlib.suppress(subprocess.TimeoutExpired):
                        process.communicate(timeout=6)
                    if process.poll() is None:
                        process.kill(); process.communicate()
