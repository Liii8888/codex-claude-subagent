# Remote session retention

Feature ID: `claude-remote-session-retention`
Introduced: 2026-09-27
Status: active only for explicitly requested Remote Control; local execution is default
Baseline: official Claude Code CLI 2.1.283 on macOS

The former interactive PTY worker exited after each task, which archived its
Remote Control view and hid it from the normal sidebar. The current worker is
one official CLI process using stdin/stdout stream-json control. It does not
call private HTTP endpoints, copy credentials, modify App indexes, import a
duplicate local view, or stay alive after the task.

## Contract

1. Preserve existing workspace, tool, sandbox, model, effort and concurrency
   restrictions. Require CLI 2.1.283 or newer before starting the worker.
2. Send `initialize`, then `remote_control` with `enabled=true` and
   `keep_session_on_exit=true`. A native follow-up supplies the saved remote
   session ID and requires the returned URL to match. Require both the URL
   response and the CLI's `bridge_state=connected` before submitting anything;
   registration/`ready` alone is not an online connection. No task is sent on a
   failed handshake, unexpected URL or unsupported version.
   New sessions receive the chosen readable title. Native resumes omit both
   CLI `--name` and a remote reattach name so App title edits are not overwritten.
3. Submit exactly one UUID-tagged user message using a `content` array with a
   text block. In the tested CLI/App path, a string was accepted by the model
   and persisted locally but the App omitted its user bubble; the text-block
   form displayed both sides. Put the task before the supplied context so the
   task is visible above the App's long-message fold. Require its exact replay, the
   expected native session ID and verified cwd before accepting a response.
   Competing input fails the job. Additional permission requests are denied.
4. Require an assistant response and a successful structured result carrying
   `stop_reason=end_turn` and the submitted user-message UUID. The assistant
   event itself may have a null stop reason in CLI 2.1.283.
   Save the result before sending `end_session`; require its acknowledgement
   and process exit 0 for job success. A shutdown failure keeps the saved result
   but reports failure. Cancellation still validates process identity and
   terminates its process group.

The input is limited to 1 MiB, stream records to 4 MiB, the captured stream to
32 MiB and stderr to its existing 1 MiB tail. Startup, task and model-turn limits
remain enforced. Shutdown is bounded to 15 seconds, followed by process cleanup.
History and results remain under the existing permission and retention policy.

## Connection health

Feature ID: `claude-remote-connection-health`
Introduced: 2026-09-28. Recheck when CLI bridge state/failure semantics change.

The runner records every bridge state change and its observation time. Ordinary
`reconnecting` is handled by the official CLI in the same process. An explicit
`failed` with `failure_kind=network` can re-enable Remote Control at most twice,
using the original remote ID without renaming it. Each reattach must return the
same URL. No prompt is resent, no second worker is started, and permissions stay
unchanged. Authentication, policy, takeover/ended-elsewhere and unclassified
failures are not automatically reclaimed.

Recovery has a 90-second deadline (`live_reconnect_timeout_seconds`, configurable
5–300). A result received while reconnecting is saved immediately; normal shutdown
waits for recovery. Timeout or unrecoverable failure stops the managed worker and
reports failure, retaining any saved response and native history. This may stop
an unfinished task; it never silently runs without the requested live connection
or restarts work that might already have modified files.

`run --open-desktop` opens the exact remote link once after connection and before
task submission. Use it when the user chose Remote Control and expects to watch
the App during work. It requires a live reservation, does not enable Remote
Control by itself, and does not reopen the window on every reconnect.

`remote_connection` is the latest observed CLI state, not an independent end-to-end
heartbeat or an acknowledgement from the App. `remote_last_state`, observation
timestamps and `remote_recovery_attempts` remain available after exit. A successful
OS open request does not prove device verification or App rendering. Verify the
actual running state/content for App acceptance; never describe a completed
worker's normal `closed` state as a failed live connection.

## Compatibility and acceptance

`keep_session_on_exit` and `end_session` were verified in the installed official
CLI implementation and in real no-tools probes. They are not promised here as
a stable public API. Recheck new-task execution, native resume, cancellation,
write permissions, graceful exit and Desktop visibility when upgrading the CLI.
Protocol failure is explicit; never silently retry the task using another mode.

`keep_session_on_exit` in a job records a requested policy. It does not prove
workspace grouping, Desktop device authentication, or indefinite server-side
retention. Verify the actual sidebar entry and body when those are acceptance
criteria. Older archived jobs can be recovered with the result Skill; no old
job records are rewritten just to advertise this feature.

Retention preserves a view, not a live execution process. Desktop's
`Remote Control disconnected` banner is expected after the worker exits.
Viewing history requires no restart; the next explicitly requested live native follow-up
reconnects. See the [official lifecycle documentation](https://code.claude.com/docs/en/remote-control#resume-sessions-after-stopping-the-server).
Do not add a persistent idle worker or silently import a second view to hide
the banner. Regression checks include preserving a title edited in Desktop
across a follow-up and keeping the same session URL.

If the CLI changes this protocol, keep the previous installed plugin available
for rollback and stop installation until compatibility is established. Local
headless execution is the default and does not enable Remote Control retention.
