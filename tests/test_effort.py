from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import unittest
from unittest import mock

import test_runner as base

# Feature: claude-effort-selection.
runtime = base.runtime


class EffortTests(unittest.TestCase):
    def setUp(self):
        base.RuntimeTests.setUp(self)
        self.prompt = self.root / 'effort-prompt.txt'
        self.prompt.write_text('Synthetic test task.')
        self.args_capture = self.root / 'effort-args.json'
        os.environ['FAKE_CLAUDE_ARGS_FILE'] = str(self.args_capture)

    def tearDown(self):
        base.RuntimeTests.tearDown(self)

    def invoke(self, *arguments):
        with mock.patch.object(sys, 'argv', ['claude-subagent', *arguments]), \
             contextlib.redirect_stdout(io.StringIO()):
            return runtime.main()

    def test_new_jobs_require_effort_before_reservation_or_execution(self):
        commands = [
            ['reserve', '--kind', kind, '--mode', 'read', '--cwd', str(self.root)]
            for kind in ('task', 'review', 'adversarial-review')
        ] + [['run', '--mode', 'read', '--cwd', str(self.root),
              '--prompt-file', str(self.prompt)]]
        with mock.patch.object(runtime, 'reserve_job') as reserve, \
             mock.patch.object(runtime, 'run_job') as run:
            for command in commands:
                with self.subTest(command=command), self.assertRaisesRegex(
                    runtime.RuntimeErrorWithHint, 'explicit --effort'
                ):
                    self.invoke(*command)
            reserve.assert_not_called()
            run.assert_not_called()
        self.assertEqual(runtime.all_jobs(), [])

    def test_selected_effort_reaches_worker_despite_legacy_default_and_environment(self):
        config = runtime.load_config()
        config['default_effort'] = 'max'
        runtime.write_json_atomic(runtime.config_path(), config)
        env_capture = self.root / 'effort-env.json'
        with mock.patch.dict(os.environ, {
            'CLAUDE_CODE_EFFORT_LEVEL': 'max',
            'FAKE_CLAUDE_EFFORT_ENV_FILE': str(env_capture),
        }):
            for effort in ('low', 'medium', 'high', 'xhigh', 'max'):
                with self.subTest(effort=effort):
                    prior = {job['id'] for job in runtime.all_jobs()}
                    self.assertEqual(self.invoke(
                        'run', '--mode', 'read', '--cwd', str(self.root),
                        '--effort', effort, '--prompt-file', str(self.prompt),
                    ), 0)
                    job, = [job for job in runtime.all_jobs() if job['id'] not in prior]
                    self.assertEqual(job['state'], 'completed')
                    self.assertEqual(job['effort'], effort)
                    args = json.loads(self.args_capture.read_text())
                    self.assertEqual(args[args.index('--effort') + 1], effort)
                    self.assertIsNone(json.loads(env_capture.read_text()))
                    self.assertEqual(os.environ['CLAUDE_CODE_EFFORT_LEVEL'], 'max')
        self.assertNotIn('default_effort', runtime.load_config())
        self.assertEqual(json.loads(runtime.config_path().read_text())['default_effort'], 'max')

    def test_reserved_job_keeps_its_effort_and_rejects_conflicting_override(self):
        job = base.RuntimeTests.reserve(self)
        with self.assertRaisesRegex(runtime.RuntimeErrorWithHint, 'reserved effort'):
            self.invoke('run', '--job', job['id'], '--effort', 'high',
                        '--prompt-file', str(self.prompt))
        self.assertEqual(runtime.read_job(job['id'])['state'], 'queued')
        self.assertFalse(self.args_capture.exists())
        self.assertEqual(self.invoke('run', '--job', job['id'],
                                     '--prompt-file', str(self.prompt)), 0)
        args = json.loads(self.args_capture.read_text())
        self.assertEqual(args[args.index('--effort') + 1], 'low')


if __name__ == '__main__':
    unittest.main()
