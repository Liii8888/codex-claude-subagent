from __future__ import annotations

import contextlib
import json
import os
import signal
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import test_runner as base

runtime = base.runtime


FAKE_LIVE = r'''#!/usr/bin/env python3
import json, os, select, sys, time, uuid
from pathlib import Path
args=sys.argv[1:]
scenario=os.environ.get('FAKE_LIVE_SCENARIO','')
if '--version' in args:
 print('2.1.212' if scenario=='old_version' else '2.1.283')
 raise SystemExit(0)
flag='--resume' if '--resume' in args else '--session-id'
sid=args[args.index(flag)+1]
p=Path(os.environ['FAKE_CLAUDE_PROJECTS_ROOT'])/'-fixture-project'/(sid+'.jsonl')
Path(os.environ['FAKE_LIVE_PID']).write_text(str(os.getpid()))
log=Path(os.environ['FAKE_PROTOCOL_LOG'])
def record_input(event):
 with log.open('a') as f:f.write(json.dumps(event)+'\n')
def emit(event):
 if event['type'] not in ('control_response','control_request'):
  event.setdefault('session_id',sid)
  event.setdefault('uuid',str(uuid.uuid4()))
 raw=(json.dumps(event,ensure_ascii=False)+'\n').encode()
 if scenario=='fragmented':
  for i in range(0,len(raw),7):os.write(1,raw[i:i+7])
 else:os.write(1,raw)
def response(event,data=None,error=None):
 emit({'type':'control_response','response':{'subtype':'error' if error else 'success',
       'request_id':event['request_id'],**({'error':error} if error else {'response':data or {}})}})
for line in sys.stdin:
 event=json.loads(line);record_input(event)
 if event['type']=='control_request':
  r=event['request'];kind=r['subtype']
  if kind=='initialize':
   response(event,error='unsupported' if scenario=='reject_init' else None)
  elif kind=='remote_control':
   if os.environ.get('FAKE_LIVE_NO_BRIDGE'):
    while True:time.sleep(.1)
   if scenario=='reject_bridge':response(event,error='unavailable');continue
   if scenario=='invalid_json':os.write(1,b'not json\n');continue
   if scenario=='truncated':os.write(1,b'{"type":');raise SystemExit(0)
   if 'name' in r:Path(os.environ['FAKE_REMOTE_TITLE']).write_text(r['name'])
   url='https://claude.ai/code/'+r.get('reattach_session_id','session_'+sid.replace('-',''))
   if scenario=='wrong_remote':url='https://claude.ai/code/session_wrong'
   if scenario=='connected_before_response':
    emit({'type':'system','subtype':'bridge_state','state':'connected'})
   response(event,{'session_url':url})
   if scenario!='connected_before_response':
    emit({'type':'system','subtype':'bridge_state','state':'ready'})
    if scenario!='no_connected':emit({'type':'system','subtype':'bridge_state','state':'connected'})
  elif kind=='end_session':
   if scenario=='hang_shutdown':
    while True:time.sleep(.1)
   response(event,error='cannot close' if scenario=='reject_end' else None)
   raise SystemExit(9 if scenario=='bad_exit' else 0)
 elif event['type']=='user':
  prompt=event['message']['content']
  if isinstance(prompt,list):prompt='\n'.join(b['text'] for b in prompt if b.get('type')=='text')
  if scenario=='crash':raise SystemExit(7)
  if scenario=='hang':
   while True:time.sleep(.1)
  p.parent.mkdir(parents=True,exist_ok=True)
  with p.open('a') as f:f.write(json.dumps({'type':'user','sessionId':sid,'message':{'content':prompt}})+'\n')
  emit({'type':'system','subtype':'init','cwd':'/wrong' if scenario=='bad_cwd' else os.getcwd()})
  if scenario!='missing_ack':
   echo=dict(event)
   if scenario=='wrong_uuid':echo['uuid']=str(uuid.uuid4())
   emit(echo)
  if scenario in ('interleave','interleave_blocks'):
   emit({'type':'user','message':{'content':'someone else' if scenario=='interleave' else [{'type':'text','text':'someone else'}]}})
  if scenario=='reconnecting':
   emit({'type':'system','subtype':'bridge_state','state':'reconnecting','detail':'network interruption'})
   time.sleep(.05)
   emit({'type':'system','subtype':'bridge_state','state':'connected'})
  if scenario in ('network_recovery','network_wrong_url','network_retry_limit','auth_failure','ended_elsewhere','policy_disabled'):
   for attempt in range(4 if scenario=='network_retry_limit' else 1):
    emit({'type':'system','subtype':'bridge_state',
          'state':'policy_disabled' if scenario=='policy_disabled' else 'failed',
          'failure_kind':'network' if scenario.startswith('network_') else 'auth' if scenario=='auth_failure' else 'ended_elsewhere',
          'detail':'simulated connection failure'})
    if not select.select([sys.stdin],[],[],.5)[0]:raise SystemExit(8)
    retry=json.loads(sys.stdin.readline());record_input(retry)
    if retry.get('type')!='control_request' or retry['request'].get('subtype')!='remote_control':raise SystemExit(8)
    response(retry,{'session_url':'https://claude.ai/code/session_wrong' if scenario=='network_wrong_url' else url})
    emit({'type':'system','subtype':'bridge_state','state':'connected'})
  if scenario=='tool_result':emit({'type':'user','message':{'content':[{'type':'tool_result','content':'source text'}]}})
  if scenario=='permission':
   emit({'type':'control_request','request_id':'tool-approval','request':{'subtype':'can_use_tool','tool_name':'Bash','input':{'command':'bad'}}})
   decision=json.loads(sys.stdin.readline());record_input(decision)
   if decision['response'].get('response',{}).get('behavior')!='deny':raise SystemExit(6)
  if scenario=='limit':
   for i in range(3):emit({'type':'assistant','message':{'id':str(uuid.uuid4()),'stop_reason':'tool_use','content':[]}})
  mid=str(uuid.uuid4())
  emit({'type':'assistant','message':{'id':mid,'stop_reason':None,'content':[{'type':'thinking','thinking':'not a final result'}]}})
  emit({'type':'assistant','isApiErrorMessage':scenario=='api_error','message':{'id':mid,
       'stop_reason':'max_tokens' if scenario=='incomplete' else None,'content':[{'type':'text','text':'LIVE_OK:'+prompt}]}})
  if scenario=='snapshot':emit({'type':'system','subtype':'post_turn_summary'})
  if scenario=='missing_result':raise SystemExit(0)
  result={'type':'result','subtype':'error_max_turns' if scenario=='result_error' else 'success',
          'is_error':scenario=='result_error','result':'LIVE_OK:'+prompt,
          'stop_reason':'max_tokens' if scenario=='result_incomplete' else 'end_turn',
          'user_message_uuid':str(uuid.uuid4()) if scenario=='wrong_turn' else event['uuid']}
  if scenario=='wrong_session':result['session_id']=str(uuid.uuid4())
  if scenario in ('result_during_reconnect','reconnect_timeout'):
   emit({'type':'system','subtype':'bridge_state','state':'reconnecting'})
  emit(result)
  if scenario=='result_during_reconnect':
   if select.select([sys.stdin],[],[],.1)[0]:raise SystemExit(11)
   emit({'type':'system','subtype':'bridge_state','state':'connected'})
  if scenario=='duplicate_result':emit(result)
'''


class LiveTests(unittest.TestCase):
    def setUp(self):
        base.RuntimeTests.setUp(self)
        self.fake_claude.write_text(FAKE_LIVE)
        os.environ['FAKE_LIVE_PID'] = str(self.root / 'live.pid')
        os.environ['FAKE_PROTOCOL_LOG'] = str(self.root / 'protocol-input.jsonl')
        os.environ['FAKE_REMOTE_TITLE'] = str(self.root / 'remote-title.txt')

    def tearDown(self):
        base.RuntimeTests.tearDown(self)

    def reserve(self, mode='read'):
        return runtime.reserve_job(kind='task', mode=mode, cwd=str(self.root),
                                   model='sonnet', effort='low', permission_mode='auto', live=True)

    def run_job(self, job, text='test task', resume=None):
        p = self.root / 'prompt.txt'
        p.write_text(text)
        return runtime.run_job(job['id'], prompt_file=p, resume_from=resume)

    def assert_stopped(self):
        pid_file = self.root / 'live.pid'
        if pid_file.exists():
            self.assertFalse(runtime.process_alive(int(pid_file.read_text())))

    def protocol_input(self):
        p = self.root / 'protocol-input.jsonl'
        return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []

    def test_retention_handshake_precedes_task_and_shutdown_follows_result(self):
        job = self.reserve()
        self.assertEqual(self.run_job(job), 0)
        events = self.protocol_input()
        self.assertEqual([e['type'] for e in events],
                         ['control_request', 'control_request', 'user', 'control_request'])
        self.assertEqual(events[0]['request']['subtype'], 'initialize')
        self.assertTrue(events[1]['request']['keep_session_on_exit'])
        self.assertEqual(events[1]['request']['subtype'], 'remote_control')
        self.assertEqual(events[-1]['request']['subtype'], 'end_session')
        user = next(e for e in events if e['type'] == 'user')
        self.assertIsInstance(user['message']['content'], list)
        self.assertEqual(user['message']['content'][0]['type'], 'text')
        self.assert_stopped()

    def test_remote_url_alone_never_submits_a_task(self):
        config = runtime.load_config()
        config['live_startup_timeout_seconds'] = .2
        with mock.patch.dict(os.environ, {'FAKE_LIVE_SCENARIO': 'no_connected'}), \
             mock.patch.object(runtime, 'load_config', return_value=config):
            job = self.reserve()
            with self.assertRaisesRegex(runtime.RuntimeErrorWithHint, 'No task was submitted'):
                self.run_job(job)
        self.assertFalse(any(e['type'] == 'user' for e in self.protocol_input()))
        self.assert_stopped()

    def test_requested_desktop_view_opens_before_task_and_only_once_across_recovery(self):
        prompt = self.root / 'prompt.txt'
        prompt.write_text('view this task')
        def opened(job, *, open_app):
            self.assertTrue(open_app)
            self.assertEqual(job['remote_connection'], 'connected')
            self.assertTrue(job['remote_url'])
            self.assertFalse(any(e['type'] == 'user' for e in self.protocol_input()))
            return {'open_requested': True}
        with mock.patch.dict(os.environ, {'FAKE_LIVE_SCENARIO': 'network_recovery'}), \
             mock.patch.object(runtime, 'desktop_session', side_effect=opened) as desktop:
            job = self.reserve()
            self.assertEqual(runtime.run_job(job['id'], prompt_file=prompt, resume_from=None, open_desktop=True), 0)
        desktop.assert_called_once()
        self.assertTrue(runtime.read_job(job['id'])['desktop_open_requested'])
        self.assert_stopped()

    def test_open_desktop_does_not_silently_enable_remote_control(self):
        job = runtime.reserve_job(kind='task', mode='read', cwd=str(self.root), model='sonnet',
                                  effort='low', permission_mode='auto')
        with mock.patch.object(runtime.subprocess, 'Popen') as spawn:
            with self.assertRaisesRegex(runtime.RuntimeErrorWithHint, 'explicitly reserved --live'):
                runtime.run_job(job['id'], prompt_file=self.root / 'unused', resume_from=None, open_desktop=True)
        spawn.assert_not_called()
        self.assertEqual(runtime.read_job(job['id'])['transport'], 'print')
        self.assertEqual(runtime.read_job(job['id'])['state'], 'failed')

    def test_connected_event_may_arrive_before_control_response(self):
        with mock.patch.dict(os.environ, {'FAKE_LIVE_SCENARIO': 'connected_before_response'}):
            job = self.reserve()
            self.assertEqual(self.run_job(job), 0)
        self.assertTrue(runtime.read_job(job['id'])['remote_connected_at'])
        self.assert_stopped()

    def test_reconnecting_is_observable_and_cli_recovers_without_replaying_task(self):
        with mock.patch.dict(os.environ, {'FAKE_LIVE_SCENARIO': 'reconnecting'}), \
             mock.patch.object(runtime, 'update_job', wraps=runtime.update_job) as updates:
            job = self.reserve()
            self.assertEqual(self.run_job(job), 0)
        states = [call.kwargs.get('remote_connection') for call in updates.call_args_list]
        self.assertIn('reconnecting', states)
        self.assertGreater(states.index('connected', states.index('reconnecting')), states.index('reconnecting'))
        self.assertEqual(len([e for e in self.protocol_input() if e['type'] == 'user']), 1)
        self.assertEqual(len([e for e in self.protocol_input() if e.get('request', {}).get('subtype') == 'remote_control']), 1)
        self.assert_stopped()

    def test_network_failure_reattaches_same_view_without_repeating_user_turn(self):
        with mock.patch.dict(os.environ, {'FAKE_LIVE_SCENARIO': 'network_recovery'}):
            job = self.reserve()
            self.assertEqual(self.run_job(job), 0)
        saved = runtime.read_job(job['id'])
        events = self.protocol_input()
        connects = [e['request'] for e in events if e.get('request', {}).get('subtype') == 'remote_control']
        self.assertEqual(len(connects), 2)
        self.assertEqual(connects[1]['reattach_session_id'], saved['remote_url'].rsplit('/', 1)[1])
        self.assertNotIn('name', connects[1])
        self.assertTrue(connects[1]['keep_session_on_exit'])
        self.assertEqual(len([e for e in events if e['type'] == 'user']), 1)
        self.assertEqual(saved['remote_recovery_attempts'], 1)
        self.assert_stopped()

    def test_network_retries_are_bounded(self):
        with mock.patch.dict(os.environ, {'FAKE_LIVE_SCENARIO': 'network_retry_limit'}):
            job = self.reserve()
            with self.assertRaisesRegex(runtime.RuntimeErrorWithHint, 'recovery limit'):
                self.run_job(job)
        events = self.protocol_input()
        self.assertEqual(len([e for e in events if e.get('request', {}).get('subtype') == 'remote_control']), 3)
        self.assertEqual(len([e for e in events if e['type'] == 'user']), 1)
        self.assert_stopped()

    def test_recovery_cannot_change_session_or_replay_the_task(self):
        with mock.patch.dict(os.environ, {'FAKE_LIVE_SCENARIO': 'network_wrong_url'}):
            job = self.reserve()
            with self.assertRaisesRegex(runtime.RuntimeErrorWithHint, 'different remote session'):
                self.run_job(job)
        self.assertEqual(len([e for e in self.protocol_input() if e['type'] == 'user']), 1)
        self.assertNotEqual(runtime.read_job(job['id'])['remote_url'], 'https://claude.ai/code/session_wrong')
        self.assert_stopped()

    def test_auth_policy_and_takeover_failures_are_not_automatically_reclaimed(self):
        for scenario in ('auth_failure', 'ended_elsewhere', 'policy_disabled'):
            with self.subTest(scenario=scenario), mock.patch.dict(os.environ, {'FAKE_LIVE_SCENARIO': scenario}):
                (self.root / 'protocol-input.jsonl').unlink(missing_ok=True)
                with self.assertRaisesRegex(runtime.RuntimeErrorWithHint, 'Remote Control'):
                    self.run_job(self.reserve())
                self.assertEqual(len([e for e in self.protocol_input() if e.get('request', {}).get('subtype') == 'remote_control']), 1)
                self.assert_stopped()

    def test_result_is_saved_while_waiting_for_connection_recovery(self):
        observed = []
        original = runtime.update_job
        def observe(job_id, **changes):
            if changes.get('remote_connection') == 'reconnecting':
                observed.append(job_id)
            return original(job_id, **changes)
        with mock.patch.dict(os.environ, {'FAKE_LIVE_SCENARIO': 'result_during_reconnect'}), \
             mock.patch.object(runtime, 'update_job', side_effect=observe):
            job = self.reserve()
            self.assertEqual(self.run_job(job), 0)
        self.assertEqual(observed, [job['id']])
        self.assertTrue(runtime.read_job(job['id'])['response_completed'])
        self.assert_stopped()

    def test_unrecovered_connection_keeps_saved_result_but_does_not_claim_live_success(self):
        config = runtime.load_config()
        config['live_reconnect_timeout_seconds'] = .2
        with mock.patch.dict(os.environ, {'FAKE_LIVE_SCENARIO': 'reconnect_timeout'}), \
             mock.patch.object(runtime, 'load_config', return_value=config):
            job = self.reserve()
            with self.assertRaisesRegex(runtime.RuntimeErrorWithHint, 'connection did not recover'):
                self.run_job(job)
        self.assertTrue((runtime.job_dir(job['id']) / 'result.txt').read_text())
        self.assertEqual(runtime.read_job(job['id'])['state'], 'failed')
        self.assert_stopped()

    def test_bridge_and_version_rejections_never_submit_a_task(self):
        for scenario in ('reject_init', 'reject_bridge', 'old_version'):
            with self.subTest(scenario=scenario), mock.patch.dict(os.environ, {'FAKE_LIVE_SCENARIO': scenario}):
                (self.root / 'protocol-input.jsonl').unlink(missing_ok=True)
                job = self.reserve()
                with self.assertRaises(runtime.RuntimeErrorWithHint):
                    self.run_job(job)
                self.assertFalse(any(e['type'] == 'user' for e in self.protocol_input()))
                self.assertEqual(runtime.read_job(job['id'])['state'], 'failed')
                self.assert_stopped()

    def test_resume_rejects_changed_remote_before_submitting_followup(self):
        first = self.reserve()
        self.run_job(first)
        (self.root / 'protocol-input.jsonl').unlink()
        with mock.patch.dict(os.environ, {'FAKE_LIVE_SCENARIO': 'wrong_remote'}):
            second = self.reserve()
            with self.assertRaisesRegex(runtime.RuntimeErrorWithHint, 'different remote session'):
                self.run_job(second, 'must not run', first['id'])
        events = self.protocol_input()
        self.assertFalse(any(e['type'] == 'user' for e in events))
        self.assertEqual(events[1]['request']['reattach_session_id'],
                         runtime.read_job(first['id'])['remote_url'].rsplit('/', 1)[1])
        self.assert_stopped()

    def test_shutdown_failure_preserves_completed_result_without_success(self):
        with mock.patch.dict(os.environ, {'FAKE_LIVE_SCENARIO': 'hang_shutdown'}), \
             mock.patch.object(runtime, 'LIVE_SHUTDOWN_TIMEOUT_SECONDS', .3):
            job = self.reserve()
            with self.assertRaisesRegex(runtime.RuntimeErrorWithHint, 'did not close'):
                self.run_job(job, 'saved task')
        self.assertIn('saved task', (runtime.job_dir(job['id']) / 'result.txt').read_text())
        self.assertEqual(runtime.read_job(job['id'])['state'], 'failed')
        self.assert_stopped()

    def test_invalid_saved_remote_releases_reservation_without_spawning(self):
        first = self.reserve()
        self.run_job(first)
        runtime.update_job(first['id'], remote_url='https://example.com/session_bad')
        second = self.reserve()
        with mock.patch.object(runtime.subprocess, 'Popen') as spawn:
            with self.assertRaises(runtime.RuntimeErrorWithHint):
                self.run_job(second, 'must not run', first['id'])
        spawn.assert_not_called()
        self.assertEqual(runtime.read_job(second['id'])['state'], 'failed')
        self.assertEqual(runtime.active_jobs(), [])

    def test_nonzero_exit_after_result_is_not_success(self):
        with mock.patch.dict(os.environ, {'FAKE_LIVE_SCENARIO': 'bad_exit'}):
            job = self.reserve()
            self.assertEqual(self.run_job(job), 1)
        self.assertEqual(runtime.read_job(job['id'])['state'], 'failed')
        self.assert_stopped()

    def test_permission_request_does_not_expand_worker_authority(self):
        with mock.patch.dict(os.environ, {'FAKE_LIVE_SCENARIO': 'permission'}):
            job = self.reserve('write')
            self.assertEqual(self.run_job(job), 0)
        response = next(e['response'] for e in self.protocol_input() if e['type'] == 'control_response')
        self.assertEqual(response['response']['behavior'], 'deny')
        self.assertEqual(runtime.read_job(job['id'])['permission_mode'], 'auto')

    def test_prompt_larger_than_pipe_buffer_does_not_deadlock(self):
        job = self.reserve()
        text = '多行测试\n' * 20000
        self.assertEqual(self.run_job(job, text), 0)
        self.assertIn(text.rstrip(), (runtime.job_dir(job['id']) / 'result.txt').read_text())
        self.assert_stopped()

    def test_live_cli_preserves_tool_and_permission_boundaries(self):
        for mode in ('read', 'write'):
            job = self.reserve(mode)
            args = runtime.build_claude_args(job)
            self.assertNotIn('--remote-control', args)
            self.assertIn('-p', args)
            self.assertIn('--replay-user-messages', args)
            self.assertEqual(args[args.index('--input-format') + 1], 'stream-json')
            self.assertIn('--max-turns', args)
            self.assertIn('Agent', args[args.index('--disallowedTools') + 1])
            self.assertEqual(args[args.index('--permission-mode') + 1], 'dontAsk' if mode == 'read' else 'auto')
            self.assertIn('--strict-mcp-config', args)
            settings = json.loads(args[args.index('--settings') + 1])
            self.assertTrue(settings['sandbox']['failIfUnavailable'])
            self.assertFalse(settings['sandbox']['allowUnsandboxedCommands'])
            runtime.update_job(job['id'],state='completed')

    def test_live_completion_records_native_result_and_closes_process(self):
        job = self.reserve()
        self.assertEqual(self.run_job(job, '/exit\n多行任务'), 0)
        saved = runtime.read_job(job['id'])
        self.assertEqual(saved['state'], 'completed')
        self.assertEqual(saved['remote_connection'], 'closed')
        self.assertTrue(saved['remote_url'].startswith('https://claude.ai/code/session_'))
        directory = runtime.job_dir(job['id'])
        result = (directory / 'result.txt').read_text()
        self.assertIn('/exit\n多行任务', result)
        self.assertNotIn('not a final result', result)
        self.assertEqual((directory / 'stream.jsonl').stat().st_mode & 0o777, 0o600)
        self.assertTrue(saved['keep_session_on_exit'])
        self.assertTrue(saved['response_completed'])
        self.assert_stopped()

    def test_live_resume_ignores_old_completion_and_reuses_session(self):
        first = self.reserve()
        self.run_job(first, 'first task')
        second = self.reserve()
        self.run_job(second, 'second task', first['id'])
        a, b = runtime.read_job(first['id']), runtime.read_job(second['id'])
        self.assertEqual(a['session_id'], b['session_id'])
        self.assertEqual(a['remote_url'], b['remote_url'])
        self.assertEqual(b['resume_mode'], 'native')
        self.assertEqual(a['remote_session_name'], b['remote_session_name'])
        args = runtime.build_claude_args(b)
        self.assertEqual(b['resume_remote_url'], a['remote_url'])
        self.assertNotIn('--name', args)
        result = (runtime.job_dir(second['id']) / 'result.txt').read_text()
        self.assertIn('second task', result)
        self.assertNotIn('first task', result)
        self.assert_stopped()

    def test_new_title_reaches_native_and_remote_session(self):
        title = '项目 · 前端改写'
        job = runtime.reserve_job(kind='task', mode='read', cwd=str(self.root),
                                  model='sonnet', effort='low', permission_mode='auto',
                                  live=True, title=title)
        self.assertEqual(self.run_job(job), 0)
        saved = runtime.read_job(job['id'])
        args = runtime.build_claude_args(saved)
        self.assertEqual(args[args.index('--name') + 1], title)
        self.assertEqual((self.root / 'remote-title.txt').read_text(), title)
        self.assertEqual(runtime.desktop_session(saved)['desktop_session_name'], title)
        self.assert_stopped()

    def test_resume_preserves_title_edited_outside_runner(self):
        first = self.reserve()
        self.run_job(first)
        title = '项目 · 用户整理后的名称'
        (self.root / 'remote-title.txt').write_text(title)
        second = runtime.reserve_job(kind='task', mode='read', cwd=str(self.root),
                                     model='sonnet', effort='low', permission_mode='auto',
                                     live=True, title='This must not rename the existing session')
        self.assertEqual(self.run_job(second, 'follow-up', first['id']), 0)
        self.assertEqual((self.root / 'remote-title.txt').read_text(), title)
        self.assertNotIn('--name', runtime.build_claude_args(runtime.read_job(second['id'])))
        self.assertEqual(runtime.read_job(second['id'])['remote_url'], runtime.read_job(first['id'])['remote_url'])
        self.assert_stopped()

    def test_invalid_or_conflicting_title_does_not_start_or_mutate_job(self):
        for title in ('', '  ', 'x\ny', '\x1b[31m', 'x' * 121):
            with self.subTest(title=title), self.assertRaises(runtime.RuntimeErrorWithHint):
                runtime.reserve_job(kind='task', mode='read', cwd=str(self.root),
                                    model='sonnet', effort='low', permission_mode='auto', title=title)
        self.assertEqual(runtime.all_jobs(), [])
        job = self.reserve()
        with mock.patch.object(runtime.sys, 'argv', ['claude-subagent', 'run', '--job', job['id'],
                                                     '--prompt-file', 'unused', '--title', 'changed']), \
             mock.patch.object(runtime, 'run_job') as run:
            with self.assertRaisesRegex(runtime.RuntimeErrorWithHint, 'reserved title'):
                runtime.main()
        run.assert_not_called()
        self.assertEqual(runtime.read_job(job['id'])['state'], 'queued')

    def test_live_control_characters_rejected_before_spawn(self):
        job = self.reserve()
        with mock.patch.object(runtime.subprocess, 'Popen') as spawn:
            with self.assertRaises(runtime.RuntimeErrorWithHint):
                self.run_job(job, 'bad\x1b[201~\r/exit')
        spawn.assert_not_called()
        self.assertEqual(runtime.read_job(job['id'])['state'], 'failed')

    def test_live_fragmented_multiline_task_completes_and_verifies_cwd(self):
        with mock.patch.dict(os.environ, {'FAKE_LIVE_SCENARIO': 'fragmented'}):
            job = self.reserve()
            self.assertEqual(self.run_job(job, 'line one\nline two'), 0)
        self.assertTrue(runtime.read_job(job['id'])['cwd_verified'])
        self.assert_stopped()

    def test_live_failures_do_not_report_success_or_leave_children(self):
        for scenario in ('crash', 'interleave', 'interleave_blocks', 'api_error', 'incomplete', 'limit',
                         'bad_cwd', 'missing_ack', 'wrong_uuid', 'wrong_session', 'missing_result',
                         'result_error', 'result_incomplete', 'wrong_turn', 'duplicate_result', 'reject_end', 'invalid_json', 'truncated'):
            with self.subTest(scenario=scenario), mock.patch.dict(os.environ, {'FAKE_LIVE_SCENARIO':scenario}):
                config = runtime.load_config()
                config['max_turns'] = 2
                runtime.write_json_atomic(runtime.config_path(), config)
                job = self.reserve()
                with self.assertRaises(runtime.RuntimeErrorWithHint):
                    self.run_job(job)
                self.assertEqual(runtime.read_job(job['id'])['state'], 'failed')
                self.assert_stopped()

    def test_live_tool_result_is_not_a_competing_user_turn(self):
        with mock.patch.dict(os.environ, {'FAKE_LIVE_SCENARIO':'tool_result'}):
            self.assertEqual(self.run_job(self.reserve()), 0)
        self.assert_stopped()

    def test_duplicate_start_preserves_the_winning_job_and_prompt(self):
        job = self.reserve()
        original = runtime.job_dir(job['id']) / 'prompt.txt'
        original.write_text('the winning task')
        @contextlib.contextmanager
        def another_runner_claimed_first():
            claimed = runtime.read_job(job['id'])
            claimed.update(state='running', pid=os.getpid())
            runtime.write_json_atomic(runtime.job_record_path(job['id']), claimed)
            yield
        with mock.patch.object(runtime, 'registry_lock', another_runner_claimed_first), \
             mock.patch.object(runtime.subprocess, 'Popen') as spawn:
            with self.assertRaisesRegex(runtime.RuntimeErrorWithHint, 'only one runner'):
                self.run_job(job, 'the losing task')
        spawn.assert_not_called()
        self.assertEqual(runtime.read_job(job['id'])['state'], 'running')
        self.assertEqual(original.read_text(), 'the winning task')

    def test_legacy_native_followup_uses_original_remote_title(self):
        first = self.reserve()
        self.run_job(first)
        first = runtime.read_job(first['id'])
        first.pop('remote_session_name')
        first.pop('workspace_name')
        runtime.write_json_atomic(runtime.job_record_path(first['id']), first)
        second = self.reserve()
        second.pop('workspace_name')
        second.update(session_id=first['session_id'], resume_mode='native', resume_from=first['id'])
        self.assertEqual(runtime.remote_session_name(second), 'codex-claude-' + first['id'])

    def test_live_unavailable_connection_does_not_submit_or_fall_back(self):
        config = runtime.load_config()
        config['live_startup_timeout_seconds'] = 5
        runtime.write_json_atomic(runtime.config_path(), config)
        with mock.patch.dict(os.environ, {'FAKE_LIVE_NO_BRIDGE':'1'}):
            job = self.reserve()
            with self.assertRaisesRegex(runtime.RuntimeErrorWithHint, 'No task was submitted'):
                self.run_job(job)
        self.assert_stopped()
        self.assertEqual(list((self.root / 'native-projects').glob('*/*.jsonl')), [])

    def test_live_interrupt_cleans_up_process(self):
        with mock.patch.dict(os.environ, {'FAKE_LIVE_SCENARIO':'hang'}):
            job = self.reserve()
            def interrupt():
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if runtime.read_job(job['id']).get('remote_url'):
                        os.kill(os.getpid(), signal.SIGTERM)
                        return
                    time.sleep(.02)
            thread = threading.Thread(target=interrupt)
            thread.start()
            try:
                with self.assertRaises(KeyboardInterrupt):
                    self.run_job(job)
            finally:
                thread.join()
            self.assertEqual(runtime.read_job(job['id'])['state'], 'cancelled')
            self.assert_stopped()

    def test_live_cancel_command_stops_the_verified_child(self):
        with mock.patch.dict(os.environ, {'FAKE_LIVE_SCENARIO':'hang'}):
            config = runtime.load_config()
            config['live_timeout_seconds'] = 10
            runtime.write_json_atomic(runtime.config_path(), config)
            job = self.reserve()
            errors = []
            def cancel():
                try:
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        saved = runtime.read_job(job['id'])
                        if saved.get('remote_url'):
                            with mock.patch.object(runtime, 'process_start', side_effect=AssertionError('cancel must use the runner lease')), mock.patch.object(runtime, 'process_command', side_effect=AssertionError('cancel must not inspect a title')):
                                runtime.cancel_job(job['id'])
                            return
                        time.sleep(.02)
                    errors.append('job did not connect')
                except Exception as exc:
                    errors.append(str(exc))
            thread = threading.Thread(target=cancel)
            thread.start()
            try:
                self.assertEqual(self.run_job(job),1)
            finally:
                thread.join()
            self.assertEqual(errors,[])
            self.assertEqual(runtime.read_job(job['id'])['state'],'cancelled')
            self.assert_stopped()

    def test_live_start_failure_is_terminal_and_releases_the_reservation(self):
        job = self.reserve()
        with mock.patch.object(runtime.subprocess, 'Popen', side_effect=OSError('fixture failure')):
            with self.assertRaises(OSError):
                self.run_job(job)
        self.assertEqual(runtime.read_job(job['id'])['state'],'failed')
        self.assertEqual(runtime.active_jobs(),[])

    def test_live_desktop_access_does_not_start_second_session(self):
        job = self.reserve()
        job.update(state='running', remote_url='https://claude.ai/code/session_test', pid=os.getpid())
        runtime.write_json_atomic(runtime.job_record_path(job['id']), job)
        with mock.patch.object(runtime.subprocess, 'run') as command:
            report = runtime.desktop_session(job)
        command.assert_not_called()
        self.assertEqual(report['remote_url'],job['remote_url'])
        self.assertEqual(report['desktop_url'], 'claude://claude.ai/code/session_test')
        self.assertNotIn('claude://resume', json.dumps(report))
        with self.assertRaises(runtime.RuntimeErrorWithHint):
            runtime.remote_session_url('https://example.com/session_abc')

    def test_live_desktop_open_targets_same_session_during_and_after_work(self):
        job = self.reserve()
        job.update(remote_url='https://claude.ai/code/session_test', pid=os.getpid())
        for state in ('running', 'completed'):
            with self.subTest(state=state):
                job['state'] = state
                runtime.write_json_atomic(runtime.job_record_path(job['id']), job)
                with mock.patch.object(runtime.sys, 'platform', 'darwin'), \
                     mock.patch.object(runtime.Path, 'is_dir', return_value=True), \
                     mock.patch.object(runtime.subprocess, 'Popen') as worker, \
                     mock.patch.object(runtime.subprocess, 'run') as command:
                    command.return_value.returncode = 0
                    report = runtime.desktop_session(job, open_app=True)
                command.assert_called_once_with(
                    ['/usr/bin/open', '-a', '/Applications/Claude.app',
                     'claude://claude.ai/code/session_test'],
                    check=False, capture_output=True, text=True, timeout=10,
                )
                worker.assert_not_called()
                self.assertTrue(report['open_requested'])

    def test_live_desktop_open_rejects_untrusted_urls_before_launch(self):
        job = self.reserve()
        job['state'] = 'completed'
        for url in ('https://example.com/code/session_test',
                    'https://claude.ai/code/session_test?prompt=run',
                    'https://claude.ai/code/session_test/other',
                    'claude://resume?session=test'):
            with self.subTest(url=url), mock.patch.object(runtime.subprocess, 'run') as command:
                job['remote_url'] = url
                runtime.write_json_atomic(runtime.job_record_path(job['id']), job)
                with self.assertRaises(runtime.RuntimeErrorWithHint):
                    runtime.desktop_session(job, open_app=True)
                command.assert_not_called()

    def test_live_desktop_open_reports_launch_failure(self):
        job = self.reserve()
        job.update(state='completed', remote_url='https://claude.ai/code/session_test')
        runtime.write_json_atomic(runtime.job_record_path(job['id']), job)
        with mock.patch.object(runtime.sys, 'platform', 'darwin'), \
             mock.patch.object(runtime.Path, 'is_dir', return_value=True), \
             mock.patch.object(runtime.subprocess, 'run') as command:
            command.return_value.returncode = 1
            with self.assertRaisesRegex(runtime.RuntimeErrorWithHint, 'could not open'):
                runtime.desktop_session(job, open_app=True)


if __name__ == '__main__':
    unittest.main()
