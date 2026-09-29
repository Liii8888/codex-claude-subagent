---
name: setup
description: Check Claude Subagent installation, official CLI login status, runtime configuration, and execution boundaries. Use for readiness questions or diagnosing a worker that cannot start.
---

# Claude Subagent Setup

Resolve `<plugin-root>` two directories above this file and run:

`"<plugin-root>/scripts/claude_subagent.py" setup`

Use `--json` when structured checks are needed; do not run both formats merely
to repeat the same information. Execute outside the Codex workspace sandbox
using that exact installed executable as the narrow approval prefix.

Setup checks saved login status and local configuration without making a model
request. `ready` and `authenticated` do not verify OAuth refresh, model access,
or a live Remote Control connection. Report those as verified only after a
successful real job.
The Skills default to local headless execution (omit `--live`). Remote Control
is an explicit user opt-in, including for follow-ups and view recovery.

When the user asks to change parallelism, use
`"<plugin-root>/scripts/claude_subagent.py" configure --max-concurrency <count>`.
This sets one shared total limit, preserves other settings, and leaves existing
jobs alone. New installations default to four; existing saved limits are kept
until explicitly configured. Independent checkouts can each have a writer;
same-checkout or overlapping writers conflict. A configured limit is a local
admission policy, not a verified provider capacity. Do not change it for a
readiness check or work around it by launching unmanaged workers.

Diagnose the failed boundary:

- Dispatch: waiting tasks call the runner directly and retain the parent turn.
  An idle-thread automatic callback is unverified/failed on the tested host;
  only explicitly requested background work uses the compatibility relay.
  See [program dispatch](../../references/program-dispatch.md) before changing
  this boundary. Do not create a service or private IPC workaround.
- CLI version: headless requires `2.1.203+`; live retention requires `2.1.283+`.
  Each live job checks the installed version and the Remote Control handshake
  before sending its task. The control field is implementation-specific; see
  [session retention](../../references/remote-session-retention.md) when the CLI changes.
- Login: if the official CLI has no login or cannot refresh expired OAuth,
  ask the user to run `claude auth login --claudeai`. App login alone does not
  authenticate the CLI. Desktop device verification is separate; see
  [result](../result/SKILL.md) for App sign-in and archived views.
- Sandbox visibility: a CLI that works in Terminal but appears unauthenticated
  only inside Codex's workspace sandbox should be retried outside that sandbox
  through the exact runner, not through another login or copied credentials.
- Workspace trust: a live session can stop at the official first-use folder
  confirmation. Check `stream.jsonl` and `stderr.log`; confirm only the exact workspace already
  authorized by the user, through the official CLI with hooks, MCP and model
  tools disabled. Exit that initialization session before retrying the job.
  Do not edit trust flags directly or treat the workspace allowlist as proof
  that Claude's own confirmation has been completed.
- Effort selection: new jobs require a controller-selected `--effort`; use the
  shared [task/prompt selection policy](../../references/effort-selection.md).
  Existing reservations retain their selected level. An old `default_effort`
  config entry no longer supplies a fallback.
- Configuration: explicit workspace roots, writable private runtime, a configured
  total limit (default four), one writer per checkout or overlapping workspace,
  official provider only, and required Claude sandbox.
  Read jobs have no shell or write tools; write jobs default to `auto` with a
  verified Sonnet model. Delegation, hooks/workflows, Web, and MCP stay disabled.

Live and headless workers share these boundaries and native session persistence.
`native_agents_md_supported` is a version check, not a claim about the active
built-in plugin or instruction-file setting. Official native AGENTS.md loading
requires 2.1.277+ and depends on that setting; older CLIs still auto-load CLAUDE.md.
This runtime explicitly supplies scoped shared rules and the project overview
for every task, so it does not require new CLAUDE.md files for each project.
The live runner has startup, task, model-turn and capture limits. A connection
failure does not trigger an automatic headless retry. Live startup requires the
actual `connected` bridge event as well as the session URL. Running jobs expose
reconnecting/failure instead of keeping a stale connected label; only classified
network failure gets bounded same-process reattach. Check
`remote_connection_updated_at`, `remote_last_state`, and `remote_recovery_attempts`
before diagnosing a stale App. Normal completed/closed and print-mode jobs do
not have an active Remote Control connection.

Report the specific failure. Do not install Claude, copy credentials, create a
second configuration, configure a proxy, or change VPN/time-zone settings as
part of this diagnostic. Never request broad `python3`, `claude`, shell or home
approval, or select `--unsafe-bypass` to make a check pass.
