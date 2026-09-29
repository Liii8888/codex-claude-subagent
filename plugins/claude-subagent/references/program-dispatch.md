# Program dispatch

- Feature ID: `claude-program-dispatch`
- Introduced and checked: 2026-09-27.
- Status: active for waiting tasks; idle-thread automatic wake-up not supported
  by the tested native tool callback. Explicit background work keeps the relay.
- Recheck when Codex adds a supported external-job completion/wake-up interface.
  Remove the relay only after a completion received while the parent is idle
  actually starts a new parent turn, including failure/cancellation cases.

## Direct execution

The main Codex reserves a job with the selected cwd, model, effort, permissions
and transport, then executes the exact installed runner outside the sandbox.
No second model is needed to execute or wait. Keep the parent turn active until
the result is collected. A pure JavaScript loop can own the command handle:

```javascript
// @exec: {"yield_time_ms": 1000, "max_output_tokens": 1000}
// Fill these from the verified installation, reservation and prompt file.
const runner = "/absolute/installed/scripts/claude_subagent.py";
const job = "cs-YYYYMMDD-HHMMSS-abcdef";
const prompt = "/absolute/temporary/prompt.txt";
const quote = s => "'" + s.replaceAll("'", "'\\''") + "'";
let r = await tools.exec_command({
  cmd: [runner, "run", "--job", job, "--prompt-file", prompt,
        "--receipt-only"].map(quote).join(" "),
  sandbox_permissions: "require_escalated",
  justification: "Run the authorized Claude task through its installed runner.",
  prefix_rule: [runner], yield_time_ms: 1000, max_output_tokens: 1600
});
// For a continuation add --resume-from and its validated prior job id above.
// For explicitly requested live App viewing, add --open-desktop to run.
let output = r.output || "";
while (r.session_id) {
  r = await tools.write_stdin({session_id: r.session_id, chars: "",
                              yield_time_ms: 1000, max_output_tokens: 1600});
  output = (output + (r.output || "")).slice(-12000);
}
text({job_id: job, process_exit_code: r.exit_code, receipt: output});
```

Use `functions.wait` on the yielded cell in bounded waits (at most 60 seconds),
or do independent work while it runs. Do not end the parent turn with the
promise that this cell will wake it later. Do not send repeated messages to
your own thread to emulate a completion event. If code mode is unavailable,
use the same direct command and its native wait handle.

The runtime writes `completion.json` after terminal state is saved. It contains
a stable `event_id`, state, CLI exit code, cwd, native session and result path;
it also includes transport/last connection state and recovery count, without the
full model reply. `result JOB --json` reads current
bounded metadata. Check `terminal` and `state`; exit code zero alone is not
acceptance. Read `result JOB` once for the actual answer. The controller still
verifies changes and tests. Duplicate receipts must not cause another task.

After an interrupted wait, query status/result; never restart the job just to
recover its output. Cancellation writes `cancel.requested`; the runner holding
the kernel lease stops the process group it owns. Orphan recovery validates
PID start time, group and native session arguments, so custom titles and native
resume do not invalidate identity. A surviving orphan keeps its concurrency
slot until recovered. No global hook, timer or resident service is installed.

## Explicit background compatibility

For a user-requested background task with automatic return, reserve first and
spawn exactly one `claude_<job-id-suffix>` forwarding subagent, no inherited
turns, no model override, low reasoning. It only executes the same blocking
`run --job ... --receipt-only` command, waits, and returns the receipt faithfully.
It must not inspect the repository, solve the task, alter permissions, or spawn
another agent. Return the job id and agent name; collect the result on its
completion notification. Cancel through the runner first.

This preserves the existing background route; the update makes no new claim
about a cheaper relay model. If the user forbids any relay, use direct execution
and explain that reliable automatic return after ending the parent turn is not
available in this tested host. Do not silently promise that capability.

## Evidence and retirement

Codex CLI 0.158.0-alpha.2.1, native App Tools 0.1.5: a no-model 12-second command
completed after the parent response ended, and `send_message_to_thread` returned
success for that same thread. It did not start a parent turn; the queued message
arrived with the user's next message. Active-turn message delivery alone had
succeeded earlier. The default App Server control socket was absent; launching
an independent official App Tools MCP process could not connect. These are
local compatibility findings, not a claim that all future Codex clients behave
the same. Do not replace this with private IPC, database edits, another Codex
process resuming the same thread, or a model-backed periodic watcher.
