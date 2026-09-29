from __future__ import annotations

import contextlib
import io
import json
import os
import signal
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

import test_runner as fixtures

SCRIPT = fixtures.SCRIPT
runtime = fixtures.runtime


class SupervisionTests(unittest.TestCase):
    setUp = fixtures.RuntimeTests.setUp
    tearDown = fixtures.RuntimeTests.tearDown
    reserve = fixtures.RuntimeTests.reserve

    def test_receipt_is_durable_bounded_and_excludes_model_output(self):
        job = self.reserve()
        prompt = self.root / 'prompt.txt'
        prompt.write_text('PRIVATE_TASK_BODY_' + 'x' * 50000)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = runtime.run_job(job['id'], prompt_file=prompt, resume_from=None, receipt_only=True)
        receipt = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(receipt['state'], 'completed')
        self.assertLess(len(output.getvalue()), 4096)
        self.assertNotIn('PRIVATE_TASK_BODY', output.getvalue())
        directory = runtime.job_dir(job['id'])
        self.assertEqual(json.loads((directory / 'completion.json').read_text()), receipt)
        self.assertIn('PRIVATE_TASK_BODY', (directory / 'result.txt').read_text())
        self.assertEqual((directory / 'completion.json').stat().st_mode & 0o777, 0o600)

    def test_start_failure_emits_terminal_receipt_and_releases_lease(self):
        job = self.reserve()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(runtime.RuntimeErrorWithHint):
                runtime.run_job(job['id'], prompt_file=self.root / 'missing', resume_from=None, receipt_only=True)
        receipt = json.loads(output.getvalue())
        self.assertEqual(receipt['state'], 'failed')
        self.assertTrue(receipt['terminal'])
        self.assertFalse(runtime.runner_active(runtime.read_job(job['id'])))
        self.assertEqual(runtime.active_jobs(), [])

    def test_live_supervisor_prevents_premature_interrupted_status(self):
        job = self.reserve()
        job = runtime.update_job(job['id'], state='running', pid=999999999, supervision='runner-lease-v1')
        with runtime.runner_lease(job['id']):
            self.assertEqual(runtime.reconcile_job(job)['state'], 'running')
        self.assertEqual(runtime.reconcile_job(job)['state'], 'interrupted')

    def test_stale_running_snapshot_preserves_terminal_record_and_receipt(self):
        for terminal in sorted(runtime.TERMINAL_STATES):
            with self.subTest(terminal=terminal):
                job = self.reserve()
                stale = runtime.update_job(job['id'], state='running', pid=999999999,
                                           supervision='runner-lease-v1')
                current = runtime.update_job(job['id'], state=terminal, pid=None,
                                             detail='authoritative terminal result', exit_code=0)
                runtime.save_completion(current)
                paths = [runtime.job_record_path(job['id']), runtime.job_dir(job['id'])/'completion.json']
                before = [p.read_bytes() for p in paths]
                self.assertEqual(runtime.reconcile_job(stale), current)
                self.assertEqual([p.read_bytes() for p in paths], before)

    def test_finish_while_reconciler_waits_for_registry_lock(self):
        job = self.reserve()
        stale = runtime.update_job(job['id'], state='running', pid=999999999,
                                   supervision='runner-lease-v1')
        entered = threading.Event()
        output = []
        errors = []
        def reconcile():
            entered.set()
            try:
                output.append(runtime.reconcile_job(stale))
            except BaseException as exc:
                errors.append(exc)
        worker = threading.Thread(target=reconcile, daemon=True)
        with runtime.registry_lock():
            worker.start()
            self.assertTrue(entered.wait(2))
            current = dict(stale, state='completed', pid=None, exit_code=0,
                           finished_at=runtime.now_iso())
            runtime.write_json_atomic(runtime.job_record_path(job['id']), current)
            runtime.save_completion(current)
        worker.join(3)
        self.assertFalse(worker.is_alive(), 'reconciliation deadlocked')
        self.assertEqual(errors, [])
        self.assertEqual(output, [current])
        self.assertEqual(runtime.read_job(job['id'])['state'], 'completed')
        self.assertEqual(json.loads((runtime.job_dir(job['id'])/'completion.json').read_text())['state'], 'completed')

    def test_expired_queue_snapshot_cannot_overwrite_started_or_finished_job(self):
        for state in ['running', 'completed']:
            with self.subTest(current=state):
                job = self.reserve()
                stale = runtime.update_job(job['id'], created_at='2000-01-01T00:00:00+00:00')
                current = runtime.update_job(job['id'], state=state,
                                             pid=os.getpid() if state == 'running' else None)
                with mock.patch.object(runtime, 'all_jobs', return_value=[stale]):
                    active = runtime.active_jobs()
                self.assertEqual(runtime.read_job(job['id']), current)
                self.assertEqual(active, [current] if state == 'running' else [])
                runtime.update_job(job['id'], state='completed', pid=None)

    def test_expired_queue_reconciles_only_after_owner_releases_lease(self):
        job = self.reserve()
        current = runtime.update_job(job['id'], created_at='2000-01-01T00:00:00+00:00',
                                     supervision='runner-lease-v1')
        with runtime.runner_lease(job['id']):
            self.assertEqual(runtime.active_jobs(), [current])
        self.assertEqual(runtime.active_jobs(), [])
        receipt = json.loads((runtime.job_dir(job['id'])/'completion.json').read_text())
        self.assertEqual(receipt['state'], 'interrupted')

    def test_headless_cancel_uses_owner_even_when_ps_is_unavailable(self):
        job = runtime.reserve_job(kind='task', mode='read', cwd=str(self.root),
                                  model='sonnet', effort='low', permission_mode='auto',
                                  title='项目 · 自定义名称')
        prompt = self.root / 'prompt.txt'
        prompt.write_text('wait')
        environment = dict(os.environ, FAKE_CLAUDE_SLEEP='30')
        process = subprocess.Popen([sys.executable, '-B', str(SCRIPT), 'run', '--job', job['id'],
                                    '--prompt-file', str(prompt), '--receipt-only'],
                                   env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        child_pid = None
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                saved = runtime.read_job(job['id'])
                if saved.get('pid'):
                    child_pid = saved['pid']
                    break
                time.sleep(.02)
            self.assertIsNotNone(child_pid)
            with mock.patch.object(runtime, 'process_command', side_effect=AssertionError('must not use ps')), \
                 mock.patch.object(runtime, 'process_start', side_effect=AssertionError('must not use ps')):
                runtime.cancel_job(job['id'])
            stdout, stderr = process.communicate(timeout=6)
            self.assertNotEqual(process.returncode, 0)
            self.assertEqual(json.loads(stdout)['state'], 'cancelled', stderr)
            self.assertFalse(runtime.process_alive(child_pid))
            self.assertEqual(runtime.active_jobs(), [])
        finally:
            if process.poll() is None:
                process.terminate()
                process.communicate(timeout=6)

    def test_orphan_cancel_recognizes_native_session_and_resume_without_job_title(self):
        for flag in ['--session-id', '--resume']:
            with self.subTest(flag=flag):
                job = self.reserve()
                session_id = '11111111-2222-4333-8444-555555555555'
                runtime.update_job(job['id'], state='running', pid=123, pid_start='original', session_id=session_id)
                with mock.patch.object(runtime, 'process_alive', side_effect=[True, False, False]), \
                     mock.patch.object(runtime, 'process_start', return_value='original'), \
                     mock.patch.object(runtime, 'process_command', return_value=f'claude --name Custom {flag} {session_id}'), \
                     mock.patch.object(runtime.os, 'getpgid', return_value=123), \
                     mock.patch.object(runtime.os, 'killpg') as terminate:
                    runtime.cancel_job(job['id'])
                terminate.assert_called_once_with(123, signal.SIGTERM)
                self.assertEqual(runtime.read_job(job['id'])['state'], 'cancelled')

    def test_orphan_cancel_refuses_reused_pid_or_wrong_session(self):
        job = self.reserve()
        runtime.update_job(job['id'], state='running', pid=123, pid_start='original', session_id='right-session')
        for start, command in [('reused', 'claude --resume right-session'), ('original', 'claude --resume other-session')]:
            with self.subTest(start=start, command=command), \
                 mock.patch.object(runtime, 'process_alive', return_value=True), \
                 mock.patch.object(runtime, 'process_start', return_value=start), \
                 mock.patch.object(runtime, 'process_command', return_value=command), \
                 mock.patch.object(runtime.os, 'killpg') as terminate:
                with self.assertRaisesRegex(runtime.RuntimeErrorWithHint, 'Refusing'):
                    runtime.cancel_job(job['id'])
                terminate.assert_not_called()

    def test_cancel_before_start_creates_receipt_and_never_spawns(self):
        job = self.reserve()
        runtime.cancel_job(job['id'])
        with mock.patch.object(runtime.subprocess, 'Popen') as spawn:
            with self.assertRaises(runtime.RuntimeErrorWithHint):
                runtime.run_job(job['id'], prompt_file=self.root/'irrelevant', resume_from=None)
        spawn.assert_not_called()
        receipt = json.loads((runtime.job_dir(job['id'])/'completion.json').read_text())
        self.assertEqual(receipt['state'], 'cancelled')


if __name__ == '__main__':
    unittest.main()
