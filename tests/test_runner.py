from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "plugins" / "claude-subagent" / "scripts" / "claude_subagent.py"
SPEC = importlib.util.spec_from_file_location("claude_subagent", SCRIPT)
assert SPEC and SPEC.loader
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


FAKE_CLAUDE = """#!/usr/bin/env python3
import json
import os
import sys
import time
from pathlib import Path

args = sys.argv[1:]
if args == ["--version"]:
    print("2.1.212 (Claude Code)")
    raise SystemExit(0)
if args[:3] == ["auth", "status", "--json"]:
    print(json.dumps({"authenticated": True, "authMethod": "claude.ai"}))
    raise SystemExit(0)
capture = os.environ.get("FAKE_CLAUDE_ARGS_FILE")
if capture:
    Path(capture).write_text(json.dumps(args), encoding="utf-8")
effort_capture = os.environ.get("FAKE_CLAUDE_EFFORT_ENV_FILE")
if effort_capture:
    Path(effort_capture).write_text(json.dumps(os.environ.get("CLAUDE_CODE_EFFORT_LEVEL")), encoding="utf-8")
if "--safe-mode" in args:
    pid_file = os.environ.get("FAKE_CLAUDE_PID_FILE")
    if pid_file:
        Path(pid_file).write_text(str(os.getpid()), encoding="utf-8")
    print("Claude Code ready for secret@example.com in Secret Organization", flush=True)
    print("> ", end="", flush=True)
    for command in sys.stdin:
        command = command.replace("\\x1b", "").strip()
        if command == "/exit":
            raise SystemExit(0)
        if command != "/usage":
            continue
        if os.environ.get("FAKE_CLAUDE_USAGE_HANG"):
            while True:
                time.sleep(1)
        first = (
            "Current session\\r\\n"
            "6% used\\r\\n"
            "Resets 7:20am (Asia/Taipei)\\r\\n\\r\\n"
            "Current week (all models)\\r\\n"
            "2% used\\r\\n"
            "Resets Aug 1 at 12am (Asia/Taipei)\\r\\n\\r\\n"
            "Usage credits\\r\\nUnlimited"
        )
        final = first.replace("6% used", "7% used").replace("2% used", "3% used")
        sys.stdout.write("\\x1b[?1049h\\x1b[2J\\x1b[H" + first)
        sys.stdout.flush()
        time.sleep(0.05)
        sys.stdout.write("\\x1b[H" + final)
        sys.stdout.flush()
    raise SystemExit(0)
prompt = sys.stdin.read()
session_flag = "--resume" if "--resume" in args else "--session-id"
session_id = args[args.index(session_flag) + 1]
transcript = Path(os.environ["FAKE_CLAUDE_PROJECTS_ROOT"]) / "-fixture-project" / (session_id + ".jsonl")
transcript.parent.mkdir(parents=True, exist_ok=True)
with transcript.open("a") as history:
    history.write(json.dumps({"type": "user", "message": {"content": prompt}}) + "\\n")
print(json.dumps({"type": "system", "subtype": "init", "session_id": session_id, "cwd": os.getcwd()}), flush=True)
if os.environ.get("FAKE_CLAUDE_SLEEP"):
    time.sleep(float(os.environ["FAKE_CLAUDE_SLEEP"]))
print(json.dumps({
    "type": "assistant",
    "message": {
        "content": [{
            "type": "tool_use",
            "name": "Edit",
            "input": {"file_path": "demo.txt"}
        }]
    }
}))
print(json.dumps({
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "result": "FAKE_OK:" + prompt,
    "session_id": session_id
}))
"""


class RuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.runtime_root = self.root / "runtime"
        self.fake_claude = self.root / "claude"
        self.fake_claude.write_text(FAKE_CLAUDE, encoding="utf-8")
        self.fake_claude.chmod(self.fake_claude.stat().st_mode | stat.S_IXUSR)
        self.environment = mock.patch.dict(
            os.environ,
            {
                "CLAUDE_SUBAGENT_RUNTIME_ROOT": str(self.runtime_root),
                "PATH": f"{self.root}:{os.environ.get('PATH', '')}",
                "FAKE_CLAUDE_PROJECTS_ROOT": str(self.root / "native-projects"),
            },
            clear=False,
        )
        self.environment.start()
        self.native_projects = mock.patch.object(runtime, "CLAUDE_PROJECTS_ROOT", self.root / "native-projects")
        self.native_projects.start()
        for name in runtime.UNSAFE_PROVIDER_ENV:
            os.environ.pop(name, None)
        runtime.ensure_layout()
        config = runtime.load_config()
        config["allowed_workspace_roots"] = [str(self.root)]
        runtime.write_json_atomic(runtime.config_path(), config)

    def tearDown(self) -> None:
        self.native_projects.stop()
        self.environment.stop()
        self.temporary.cleanup()

    def reserve(self, mode: str = "read") -> dict:
        return runtime.reserve_job(
            kind="task",
            mode=mode,
            cwd=str(self.root),
            model="sonnet",
            effort="low",
            permission_mode="auto",
        )

    def write_app_session(
        self,
        *,
        app_root: Path,
        projects_root: Path,
        session_id: str,
        cli_session_id: str,
        title: str,
        records: list[dict],
        last_activity_at: int,
        archived: bool = False,
    ) -> Path:
        project = self.root / "project"
        project.mkdir(exist_ok=True)
        index_directory = app_root / "account" / "window"
        index_directory.mkdir(parents=True, exist_ok=True)
        (index_directory / f"{session_id}.json").write_text(
            json.dumps(
                {
                    "sessionId": session_id,
                    "cliSessionId": cli_session_id,
                    "title": title,
                    "cwd": str(project),
                    "model": "claude-opus-5",
                    "effort": "high",
                    "completedTurns": 999,
                    "isArchived": archived,
                    "createdAt": last_activity_at - 100,
                    "lastActivityAt": last_activity_at,
                    "lastFocusedAt": last_activity_at,
                }
            ),
            encoding="utf-8",
        )
        transcript_directory = projects_root / "-fixture-project"
        transcript_directory.mkdir(parents=True, exist_ok=True)
        transcript = transcript_directory / f"{cli_session_id}.jsonl"
        transcript.write_text(
            "\n".join(json.dumps(record) for record in records) + "\n",
            encoding="utf-8",
        )
        return transcript

    def sample_session_records(self) -> list[dict]:
        return [
            {
                "type": "user",
                "uuid": "user-old",
                "timestamp": "2026-07-30T08:00:00.000Z",
                "message": {"content": "older question"},
            },
            {
                "type": "assistant",
                "uuid": "assistant-old-thinking",
                "timestamp": "2026-07-30T08:00:01.000Z",
                "message": {
                    "id": "message-old",
                    "stop_reason": "end_turn",
                    "content": [{"type": "thinking", "thinking": "private reasoning"}],
                },
            },
            {
                "type": "assistant",
                "uuid": "assistant-old-text",
                "timestamp": "2026-07-30T08:00:02.000Z",
                "message": {
                    "id": "message-old",
                    "stop_reason": "end_turn",
                    "content": [{"type": "text", "text": "older answer"}],
                },
            },
            {
                "type": "user",
                "uuid": "user-new",
                "timestamp": "2026-07-30T09:00:00.000Z",
                "message": {"content": "new question"},
            },
            {
                "type": "user",
                "uuid": "user-steer",
                "timestamp": "2026-07-30T09:00:00.500Z",
                "message": {"content": "additional direction"},
            },
            {
                "type": "assistant",
                "uuid": "assistant-tool",
                "timestamp": "2026-07-30T09:00:01.000Z",
                "message": {
                    "id": "message-tool",
                    "stop_reason": "tool_use",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "tool-1",
                            "name": "Read",
                            "input": {
                                "token": "technically-required-value",
                                "path": "demo.txt",
                            },
                        }
                    ],
                },
            },
            {
                "type": "user",
                "uuid": "tool-result",
                "timestamp": "2026-07-30T09:00:02.000Z",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "tool-1",
                            "content": "visible-output-" + "x" * 300,
                        }
                    ]
                },
            },
            {
                "type": "assistant",
                "uuid": "assistant-new",
                "timestamp": "2026-07-30T09:00:03.000Z",
                "message": {
                    "id": "message-new",
                    "stop_reason": "end_turn",
                    "content": [{"type": "text", "text": "newest answer"}],
                },
            },
        ]

    def test_setup_reports_official_ready_shape(self) -> None:
        self.assertEqual(runtime.setup_report(as_json=True), 0)

    def test_claude_session_list_is_metadata_only_and_cursor_paginated(self) -> None:
        app_root = self.root / "app-sessions"
        projects_root = self.root / "claude-projects"
        self.write_app_session(
            app_root=app_root,
            projects_root=projects_root,
            session_id="local_aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            cli_session_id="11111111-1111-4111-8111-111111111111",
            title="Older session",
            records=self.sample_session_records(),
            last_activity_at=1000,
        )
        self.write_app_session(
            app_root=app_root,
            projects_root=projects_root,
            session_id="local_bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            cli_session_id="22222222-2222-4222-8222-222222222222",
            title="Newest session",
            records=self.sample_session_records(),
            last_activity_at=2000,
        )
        first = runtime.list_claude_sessions(
            [self.root],
            limit=1,
            app_root=app_root,
            projects_root=projects_root,
        )
        self.assertEqual(first["sessions"][0]["title"], "Newest session")
        self.assertTrue(first["sessions"][0]["transcriptAvailable"])
        self.assertTrue(first["page"]["hasMore"])
        self.assertNotIn("newest answer", json.dumps(first))
        self.assertIn("untrusted", first["untrustedDataNotice"].lower())
        second = runtime.list_claude_sessions(
            [self.root],
            limit=1,
            cursor=first["page"]["nextCursor"],
            app_root=app_root,
            projects_root=projects_root,
        )
        self.assertEqual(second["sessions"][0]["title"], "Older session")
        self.assertFalse(second["page"]["hasMore"])

    def test_claude_session_read_matches_codex_progressive_disclosure(self) -> None:
        app_root = self.root / "app-sessions"
        projects_root = self.root / "claude-projects"
        self.write_app_session(
            app_root=app_root,
            projects_root=projects_root,
            session_id="local_aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            cli_session_id="11111111-1111-4111-8111-111111111111",
            title="Progressive session",
            records=self.sample_session_records(),
            last_activity_at=2000,
        )
        latest = runtime.read_claude_session(
            "Progressive session",
            [self.root],
            app_root=app_root,
            projects_root=projects_root,
        )
        self.assertEqual(latest["session"]["reconstructedTurnCount"], 2)
        self.assertEqual(len(latest["turns"]), 1)
        self.assertTrue(latest["page"]["hasMore"])
        serialized = json.dumps(latest, ensure_ascii=False)
        self.assertIn("new question", serialized)
        self.assertIn("additional direction", serialized)
        self.assertIn("newest answer", serialized)
        self.assertNotIn("technically-required-value", serialized)
        self.assertIn("[REDACTED]", serialized)
        self.assertNotIn("visible-output", serialized)
        self.assertNotIn("private reasoning", serialized)
        self.assertEqual(
            latest["readPolicy"]["contentRedaction"],
            "sensitiveStructuredFields",
        )
        older = runtime.read_claude_session(
            "local_aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            [self.root],
            cursor=latest["page"]["nextCursor"],
            app_root=app_root,
            projects_root=projects_root,
        )
        self.assertIn("older question", json.dumps(older))
        self.assertIn("older answer", json.dumps(older))
        self.assertFalse(older["page"]["hasMore"])

    def test_claude_session_explicit_no_redact_preserves_bounded_output(self) -> None:
        app_root = self.root / "app-sessions"
        projects_root = self.root / "claude-projects"
        self.write_app_session(
            app_root=app_root,
            projects_root=projects_root,
            session_id="local_aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            cli_session_id="11111111-1111-4111-8111-111111111111",
            title="Output session",
            records=self.sample_session_records(),
            last_activity_at=2000,
        )
        report = runtime.read_claude_session(
            "Output session",
            [self.root],
            include_outputs=True,
            max_output_chars_per_item=200,
            redact_sensitive=False,
            app_root=app_root,
            projects_root=projects_root,
        )
        items = report["turns"][0]["items"]
        tool_call = next(item for item in items if item["type"] == "toolCall")
        tool_result = next(item for item in items if item["type"] == "toolResult")
        self.assertEqual(
            tool_call["arguments"]["token"], "technically-required-value"
        )
        self.assertTrue(tool_result["truncated"])
        self.assertLessEqual(len(tool_result["output"]), 200)
        self.assertEqual(report["readPolicy"]["contentRedaction"], "none")

    def test_claude_session_title_must_be_unambiguous(self) -> None:
        app_root = self.root / "app-sessions"
        projects_root = self.root / "claude-projects"
        for session_id, cli_session_id, activity in (
            (
                "local_aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "11111111-1111-4111-8111-111111111111",
                1000,
            ),
            (
                "local_bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                "22222222-2222-4222-8222-222222222222",
                2000,
            ),
        ):
            self.write_app_session(
                app_root=app_root,
                projects_root=projects_root,
                session_id=session_id,
                cli_session_id=cli_session_id,
                title="Duplicate title",
                records=self.sample_session_records(),
                last_activity_at=activity,
            )
        with self.assertRaises(runtime.RuntimeErrorWithHint) as captured:
            runtime.read_claude_session(
                "Duplicate title",
                [self.root],
                app_root=app_root,
                projects_root=projects_root,
            )
        self.assertIn("ambiguous", str(captured.exception))

    def test_claude_session_cli_requires_explicit_no_redact_flag(self) -> None:
        default_args = runtime.build_parser().parse_args(
            ["sessions", "read", "session-id"]
        )
        explicit_args = runtime.build_parser().parse_args(
            ["sessions", "read", "session-id", "--no-redact"]
        )
        self.assertFalse(default_args.no_redact)
        self.assertTrue(explicit_args.no_redact)

    def test_claude_session_list_excludes_disallowed_workspaces(self) -> None:
        app_root = self.root / "app-sessions"
        projects_root = self.root / "claude-projects"
        self.write_app_session(
            app_root=app_root,
            projects_root=projects_root,
            session_id="local_aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            cli_session_id="11111111-1111-4111-8111-111111111111",
            title="Outside scope",
            records=self.sample_session_records(),
            last_activity_at=2000,
        )
        disallowed_root = self.root / "different-root"
        disallowed_root.mkdir()
        report = runtime.list_claude_sessions(
            [disallowed_root],
            app_root=app_root,
            projects_root=projects_root,
        )
        self.assertEqual(report["sessions"], [])

    def test_usage_args_are_safe_mode_and_never_prompt_a_model(self) -> None:
        args = runtime.usage_claude_args()
        self.assertIn("--safe-mode", args)
        self.assertEqual(args[args.index("--permission-mode") + 1], "dontAsk")
        self.assertEqual(args[args.index("--model") + 1], "haiku")
        self.assertEqual(args[args.index("--effort") + 1], "low")
        self.assertIn("--no-chrome", args)
        self.assertNotIn("-p", args)

    def test_terminal_renderer_keeps_refreshed_usage_values(self) -> None:
        first = (
            b"\x1b[2J\x1b[HCurrent session\r\n6% used\r\n"
            b"Resets 7:20am (Asia/Taipei)\r\n\r\n"
            b"Current week (all models)\r\n2% used\r\n"
            b"Resets Aug 1 at 12am (Asia/Taipei)"
        )
        final = first.replace(b"6% used", b"7% used").replace(
            b"2% used", b"3% used"
        )
        screen = runtime.render_terminal(first + b"\x1b[H" + final)
        parsed = runtime.parse_usage_screen(screen)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(
            [item["used_percent"] for item in parsed["limits"]], [7, 3]
        )

    def test_usage_capture_is_structured_private_and_jobless(self) -> None:
        args_capture = self.root / "usage-args.json"
        os.environ["FAKE_CLAUDE_ARGS_FILE"] = str(args_capture)
        report = runtime.capture_plan_usage(
            timeout_seconds=3,
            settle_seconds=0.05,
            minimum_wait_seconds=0.2,
        )
        self.assertTrue(report["ready"])
        self.assertEqual(report["source"], "official Claude Code /usage")
        self.assertEqual(
            [item["used_percent"] for item in report["limits"]], [7, 3]
        )
        self.assertEqual(report["usage_credits"], "Unlimited")
        serialized = json.dumps(report)
        self.assertNotIn("secret@example.com", serialized)
        self.assertNotIn("Secret Organization", serialized)
        self.assertEqual(runtime.all_jobs(), [])
        captured_args = json.loads(args_capture.read_text())
        self.assertIn("--safe-mode", captured_args)

    def test_usage_timeout_stops_exact_child_and_fails_closed(self) -> None:
        pid_file = self.root / "usage.pid"
        os.environ["FAKE_CLAUDE_USAGE_HANG"] = "1"
        os.environ["FAKE_CLAUDE_PID_FILE"] = str(pid_file)
        with self.assertRaises(runtime.RuntimeErrorWithHint) as captured:
            runtime.capture_plan_usage(
                timeout_seconds=0.5,
                settle_seconds=0.05,
                minimum_wait_seconds=0.1,
            )
        self.assertIn("will not fall back", str(captured.exception))
        self.assertTrue(pid_file.exists())
        self.assertFalse(runtime.process_alive(int(pid_file.read_text())))
        self.assertEqual(runtime.all_jobs(), [])

    def test_workspace_sandbox_runtime_error_has_narrow_retry_hint(self) -> None:
        with mock.patch.object(
            runtime.os,
            "chmod",
            side_effect=PermissionError("sandbox denied runtime"),
        ):
            with self.assertRaises(runtime.RuntimeErrorWithHint) as captured:
                runtime.ensure_layout()
        message = str(captured.exception)
        self.assertIn("exact installed executable", message)
        self.assertIn(str(SCRIPT), message)

    def test_write_args_are_autonomous_and_deny_nested_agents(self) -> None:
        job = self.reserve("write")
        args = runtime.build_claude_args(job)
        self.assertIn("auto", args)
        denied = args[args.index("--disallowedTools") + 1]
        self.assertIn("Agent", denied)
        self.assertIn("TeamCreate", denied)
        self.assertIn("Monitor", denied)
        self.assertIn("WebSearch", denied)
        self.assertIn("ListMcpResourcesTool", denied)
        self.assertNotIn("--bg", args)
        self.assertNotIn("--no-session-persistence", args)
        self.assertIn("--strict-mcp-config", args)
        settings = json.loads(args[args.index("--settings") + 1])
        self.assertTrue(settings["disableAllHooks"])
        self.assertTrue(settings["disableWorkflows"])
        self.assertTrue(settings["sandbox"]["enabled"])
        self.assertTrue(settings["sandbox"]["failIfUnavailable"])
        self.assertFalse(settings["sandbox"]["allowUnsandboxedCommands"])
        self.assertIn("Read(~/.claude/**)", settings["permissions"]["deny"])
        self.assertIn("Write(~/.claude/**)", settings["permissions"]["deny"])
        self.assertIn("Grep(~/.claude/**)", settings["permissions"]["deny"])
        self.assertIn("Edit(./.git/**)", settings["permissions"]["deny"])
        self.assertIn("Never spawn or invoke Agent", " ".join(args))

    def test_read_args_use_locked_allowlist_without_shell_or_write_tools(self) -> None:
        job = self.reserve("read")
        args = runtime.build_claude_args(job)
        self.assertIn("dontAsk", args)
        tools = args[args.index("--tools") + 1]
        allowed = args[args.index("--allowedTools") + 1]
        denied = args[args.index("--disallowedTools") + 1]
        self.assertIn("Read", tools)
        self.assertIn(f"Read(//{str(job['cwd']).lstrip('/')}/**)", allowed)
        self.assertNotIn("WebSearch", tools)
        self.assertNotIn("Bash", tools)
        self.assertNotIn("LSP", tools)
        self.assertIn("Bash", denied)
        self.assertIn("Write", denied)
        self.assertIn("Agent", denied)

    def test_review_kinds_cannot_reserve_write_mode(self) -> None:
        for kind in ("review", "adversarial-review"):
            with self.subTest(kind=kind):
                with self.assertRaises(runtime.RuntimeErrorWithHint):
                    runtime.reserve_job(
                        kind=kind,
                        mode="write",
                        cwd=str(self.root),
                        model="sonnet",
                        effort="low",
                        permission_mode="auto",
                    )

    def test_unverified_model_cannot_silently_use_auto_write(self) -> None:
        with self.assertRaises(runtime.RuntimeErrorWithHint):
            runtime.reserve_job(
                kind="task",
                mode="write",
                cwd=str(self.root),
                model="haiku",
                effort="low",
                permission_mode="auto",
            )
        allowed = runtime.reserve_job(
            kind="task",
            mode="write",
            cwd=str(self.root),
            model="haiku",
            effort="low",
            permission_mode="bypassPermissions",
        )
        self.assertEqual(allowed["permission_mode"], "bypassPermissions")

    def test_empty_verified_model_pattern_does_not_match_every_model(self) -> None:
        config = runtime.load_config()
        config["verified_auto_write_model_patterns"] = ["", "   "]
        runtime.write_json_atomic(runtime.config_path(), config)
        with self.assertRaises(runtime.RuntimeErrorWithHint):
            self.reserve("write")

    def test_working_directory_must_be_inside_configured_workspace(self) -> None:
        with self.assertRaises(runtime.RuntimeErrorWithHint):
            runtime.reserve_job(
                kind="task",
                mode="read",
                cwd=str(self.root.parent),
                model="sonnet",
                effort="low",
                permission_mode="auto",
            )

    def test_runtime_root_rejects_filesystem_or_home_root(self) -> None:
        for unsafe_root in ("/", str(Path.home())):
            with self.subTest(unsafe_root=unsafe_root):
                with mock.patch.dict(
                    os.environ,
                    {"CLAUDE_SUBAGENT_RUNTIME_ROOT": unsafe_root},
                    clear=False,
                ):
                    with self.assertRaises(runtime.RuntimeErrorWithHint):
                        runtime.runtime_root()

    def test_concurrency_limit_is_configurable_without_a_hard_two_job_cap(self) -> None:
        config = runtime.load_config()
        config["max_concurrency"] = 8
        config["max_write_concurrency"] = 1  # legacy field no longer caps all writers
        runtime.write_json_atomic(runtime.config_path(), config)
        self.assertEqual(runtime.load_config()['max_concurrency'], 8)
        self.assertNotIn('max_write_concurrency', runtime.load_config())

    def test_latest_job_cwd_filter_uses_workspace_validation(self) -> None:
        job = self.reserve("read")
        self.assertEqual(runtime.latest_job(str(self.root))["id"], job["id"])

    def test_concurrency_caps_total_jobs(self) -> None:
        for _ in range(runtime.load_config()['max_concurrency']):
            self.reserve("read")
        with self.assertRaises(runtime.RuntimeErrorWithHint):
            self.reserve("read")

    def test_same_workspace_still_allows_only_one_writer(self) -> None:
        self.reserve("write")
        with self.assertRaises(runtime.RuntimeErrorWithHint):
            self.reserve("write")

    def test_provider_override_is_rejected(self) -> None:
        os.environ["ANTHROPIC_BASE_URL"] = "https://proxy.invalid"
        with self.assertRaises(runtime.RuntimeErrorWithHint):
            runtime.claude_environment()

    def test_worker_environment_disables_parallel_side_channels(self) -> None:
        os.environ["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] = "1"
        os.environ["CLAUDE_CODE_ENABLE_TASKS"] = "1"
        child = runtime.claude_environment()
        self.assertNotIn("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", child)
        self.assertNotIn("CLAUDE_CODE_ENABLE_TASKS", child)
        self.assertEqual(child["CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS"], "1")
        self.assertEqual(child["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"], "1")
        self.assertEqual(child["CLAUDE_CODE_DISABLE_CRON"], "1")

    def test_process_inspection_denial_is_nonfatal(self) -> None:
        with mock.patch.object(
            runtime.subprocess,
            "run",
            side_effect=PermissionError("sandbox denied ps"),
        ):
            self.assertIsNone(runtime.process_start(123))
            self.assertEqual(runtime.process_command(123), "")

    def test_run_persists_prompt_result_progress_and_session(self) -> None:
        job = self.reserve("write")
        prompt = self.root / "prompt.txt"
        prompt.write_text("make it work", encoding="utf-8")
        args_capture = self.root / "args.json"
        os.environ["FAKE_CLAUDE_ARGS_FILE"] = str(args_capture)
        self.assertEqual(
            runtime.run_job(
                job["id"],
                prompt_file=prompt,
                resume_from=None,
            ),
            0,
        )
        stored = runtime.read_job(job["id"])
        self.assertEqual(stored["state"], "completed")
        self.assertEqual(stored["session_persistence"], "native")
        self.assertTrue(runtime.native_transcript(stored).is_file())
        self.assertIn("demo.txt", stored["touched_files"])
        self.assertEqual((runtime.job_dir(job["id"]) / "prompt.txt").read_text(), "make it work")
        self.assertIn("FAKE_OK:make it work", (runtime.job_dir(job["id"]) / "result.txt").read_text())
        captured = json.loads(args_capture.read_text())
        self.assertEqual(captured[captured.index("--session-id") + 1], stored["session_id"])
        self.assertIn("--disallowedTools", captured)
        self.assertIn("Agent", captured[captured.index("--disallowedTools") + 1])

    def test_follow_up_replays_durable_task_and_result_not_hidden_session(self) -> None:
        first = self.reserve("read")
        runtime.update_job(
            first["id"],
            state="completed",
            session_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
            finished_at=runtime.now_iso(),
        )
        prior_directory = runtime.job_dir(first["id"])
        (prior_directory / "prompt.txt").write_text("original task", encoding="utf-8")
        (prior_directory / "result.txt").write_text("original result", encoding="utf-8")
        second = self.reserve("read")
        prompt = self.root / "resume.txt"
        prompt.write_text("continue", encoding="utf-8")
        args_capture = self.root / "resume-args.json"
        os.environ["FAKE_CLAUDE_ARGS_FILE"] = str(args_capture)
        self.assertEqual(
            runtime.run_job(
                second["id"],
                prompt_file=prompt,
                resume_from=first["id"],
            ),
            0,
        )
        captured = json.loads(args_capture.read_text())
        self.assertNotIn("--resume", captured)
        stored_prompt = (runtime.job_dir(second["id"]) / "prompt.txt").read_text()
        self.assertIn("original task", stored_prompt)
        self.assertIn("original result", stored_prompt)
        self.assertIn("<follow_up>\ncontinue", stored_prompt)
        self.assertEqual(
            (runtime.job_dir(second["id"]) / "followup.txt").read_text(),
            "continue",
        )
        stored = runtime.read_job(second["id"])
        self.assertEqual(stored["resume_from"], first["id"])
        self.assertEqual(stored["resume_mode"], "logical")

    def test_native_follow_up_reuses_session_and_sends_only_delta(self) -> None:
        first = self.reserve("read")
        prompt = self.root / "task.txt"
        prompt.write_text("original task", encoding="utf-8")
        runtime.run_job(first["id"], prompt_file=prompt, resume_from=None)
        first = runtime.read_job(first["id"])
        transcript = runtime.native_transcript(first)
        with transcript.open("a") as history:
            history.write('{"type":"user","message":{"content":"Desktop follow-up"}}\n')
        second = self.reserve("read")
        prompt.write_text("continue", encoding="utf-8")
        capture = self.root / "native-args.json"
        os.environ["FAKE_CLAUDE_ARGS_FILE"] = str(capture)
        runtime.run_job(second["id"], prompt_file=prompt, resume_from=first["id"])
        second = runtime.read_job(second["id"])
        args = json.loads(capture.read_text())
        self.assertEqual(args[args.index("--resume") + 1], first["session_id"])
        self.assertNotIn("--session-id", args)
        self.assertEqual(second["session_id"], first["session_id"])
        self.assertEqual(second["resume_mode"], "native")
        self.assertEqual((runtime.job_dir(second["id"]) / "prompt.txt").read_text(), "continue")
        self.assertIn("Desktop follow-up", transcript.read_text())

    def test_missing_native_transcript_does_not_fall_back_to_new_context(self) -> None:
        first = self.reserve("read")
        runtime.update_job(first["id"], state="completed", session_persistence="native",
                           session_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
        second = self.reserve("read")
        prompt = self.root / "task.txt"
        prompt.write_text("continue", encoding="utf-8")
        with mock.patch.object(runtime.subprocess, "Popen") as spawn:
            with self.assertRaises(runtime.RuntimeErrorWithHint):
                runtime.run_job(second["id"], prompt_file=prompt, resume_from=first["id"])
            spawn.assert_not_called()
        self.assertEqual(runtime.read_job(second["id"])["state"], "failed")

    def test_desktop_handoff_uses_same_file_without_copy_or_second_claude(self) -> None:
        job = self.reserve("read")
        prompt = self.root / "task.txt"
        prompt.write_text("visible in Desktop", encoding="utf-8")
        runtime.run_job(job["id"], prompt_file=prompt, resume_from=None)
        job = runtime.read_job(job["id"])
        transcript = runtime.native_transcript(job)
        before = transcript.read_bytes()
        with mock.patch.object(runtime.subprocess, "run") as launch:
            report = runtime.desktop_session(job)
            launch.assert_not_called()
        self.assertEqual(report["transcript"], str(transcript))
        self.assertEqual(report["desktop_url"], f"claude://resume?session={job['session_id']}")
        self.assertFalse(report["open_requested"])
        self.assertEqual(transcript.read_bytes(), before)

    def test_desktop_handoff_and_resume_refuse_session_in_another_active_job(self) -> None:
        first = self.reserve("read")
        prompt = self.root / "task.txt"
        prompt.write_text("original", encoding="utf-8")
        runtime.run_job(first["id"], prompt_file=prompt, resume_from=None)
        first = runtime.read_job(first["id"])
        active = self.reserve("read")
        runtime.update_job(active["id"], session_id=first["session_id"])
        with self.assertRaises(runtime.RuntimeErrorWithHint):
            runtime.desktop_session(first)
        second = self.reserve("read")
        with self.assertRaises(runtime.RuntimeErrorWithHint):
            runtime.run_job(second["id"], prompt_file=prompt, resume_from=first["id"])

    def test_desktop_handoff_does_not_open_legacy_or_active_jobs(self) -> None:
        job = self.reserve("read")
        with mock.patch.object(runtime.subprocess, "run") as launch:
            with self.assertRaises(runtime.RuntimeErrorWithHint):
                runtime.desktop_session(job, open_app=True)
            job = runtime.update_job(job["id"], state="completed")
            with self.assertRaises(runtime.RuntimeErrorWithHint):
                runtime.desktop_session(job, open_app=True)
            launch.assert_not_called()

    def test_follow_up_cannot_cross_working_directories(self) -> None:
        first = self.reserve("read")
        runtime.update_job(
            first["id"],
            state="completed",
            finished_at=runtime.now_iso(),
        )
        (runtime.job_dir(first["id"]) / "prompt.txt").write_text(
            "private project context",
            encoding="utf-8",
        )
        other_workspace = self.root / "other-project"
        other_workspace.mkdir()
        second = runtime.reserve_job(
            kind="task",
            mode="read",
            cwd=str(other_workspace),
            model="sonnet",
            effort="low",
            permission_mode="auto",
        )
        prompt = self.root / "cross-project-followup.txt"
        prompt.write_text("continue", encoding="utf-8")
        with self.assertRaises(runtime.RuntimeErrorWithHint):
            runtime.run_job(
                second["id"],
                prompt_file=prompt,
                resume_from=first["id"],
            )
        self.assertEqual(runtime.read_job(second["id"])["state"], "failed")

    def test_cancel_queued_job(self) -> None:
        job = self.reserve("read")
        runtime.cancel_job(job["id"])
        self.assertEqual(runtime.read_job(job["id"])["state"], "cancelled")

    def test_cancel_running_job_that_already_exited(self) -> None:
        job = self.reserve("read")
        runtime.update_job(
            job["id"],
            state="running",
            pid=999_999_999,
            started_at=runtime.now_iso(),
        )
        runtime.cancel_job(job["id"])
        self.assertEqual(runtime.read_job(job["id"])["state"], "cancelled")

    def test_same_reserved_job_can_only_start_once(self) -> None:
        job = self.reserve("read")
        prompt = self.root / "duplicate.txt"
        prompt.write_text("one worker only", encoding="utf-8")
        environment = os.environ.copy()
        environment["FAKE_CLAUDE_SLEEP"] = "0.4"
        command = [
            sys.executable,
            str(SCRIPT),
            "run",
            "--job",
            job["id"],
            "--prompt-file",
            str(prompt),
        ]
        first = subprocess.Popen(
            command,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        second = subprocess.Popen(
            command,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        first.communicate(timeout=5)
        second.communicate(timeout=5)
        self.assertEqual(sorted((first.returncode, second.returncode)), [0, 2])
        self.assertEqual(runtime.read_job(job["id"])["state"], "completed")


if __name__ == "__main__":
    unittest.main()
