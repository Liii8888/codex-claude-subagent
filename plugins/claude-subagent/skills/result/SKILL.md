---
name: result
description: Retrieve a Claude Subagent result or native session, open its Desktop view, or prepare a follow-up. Distinguishes live Remote Control viewing from an idle headless session handoff.
---

# Claude Result

Resolve `<plugin-root>` two directories above this file. Execute the exact
installed runtime outside the Codex workspace sandbox, with that path as the
narrow approval prefix:

`"<plugin-root>/scripts/claude_subagent.py" result [job-id] --cwd "<workspace>"`

Without an id, the runtime selects the latest terminal job in the workspace.
Use `result <job-id> --json` for bounded state/session/result-path metadata
before loading the full reply. `completion.json` preserves the terminal
receipt even if a tool wait is interrupted; recovering it never requires
re-running Claude. A receipt alone does not mean the result was accepted or
an idle Codex chat was automatically resumed.
Return the saved result faithfully; Codex evaluates it against the user's task.
For writes, inspect the actual diff and verification before claiming success.

A follow-up uses [rescue](../rescue/SKILL.md) with `--resume <job-id>` and a short
delta. Native jobs reuse their session; legacy jobs without native persistence
use logical continuation. Setup/prune removes terminal plugin records older
than the configured retention period (30 days by default);
Claude independently manages native history. Plugin pruning never deletes it.

## Open in Desktop

Only when requested:

`"<plugin-root>/scripts/claude_subagent.py" desktop <job-id> --open`

Without `--open`, this only returns access information. The meaning depends on
the job's transport:

- **Live:** valid during or after execution. Returns the Remote Control URL,
  `desktop_url`, and session name; `--open` opens that exact existing session in
  the App through `claude://claude.ai/code/session_<id>`, without importing a
  second local view. Follow-ups may keep the original
  session identity. The returned title is the last recorded title; later App
  renames may differ. Prefer the exact link when identifying a renamed view.
  Remote views need not appear in the local `sessions list` index.
  A human-readable title or workspace label does not assign a
  Desktop project group. Check actual sidebar placement when that is requested;
  correct execution cwd and project-group placement are separate claims.
  Current jobs request `keep_session_on_exit` through the CLI control channel
  so normal process exit retains the remote view. This is a retention request,
  not proof of actual sidebar placement or indefinite server-side storage.
- **Headless:** requires an idle native session. Uses the official
  `claude://resume?session=<uuid>` handoff without copying its transcript or
  sending a model request. It rejects an active worker or missing history.

`open_requested`, a URL, or an App index proves only that step. When verifying
display, check actual message text, preferably via accessibility text. No
routine App opening, refreshing, or screenshots are needed for worker control.

## Recover the view

Keep the selected local-only transport during recovery. Do not establish a
Remote Control connection or submit a refresh prompt merely to make local
history appear in Desktop. Remote synchronization requires explicit user opt-in.

For a missing managed conversation, first run `status --cwd "<workspace>"
--json` without `--active`, then `desktop <job-id>`. Match the saved job and
native session before opening it. An empty `sessions list` does not mean a
Remote Control conversation was deleted: that command only reads local App
indexes. If the Desktop link does not navigate, search its full returned name
in the App, including archived results, or open the saved HTTPS URL.

- **Sign in again / device_key_missing:** let the user complete Desktop's own
  device verification. A working CLI login need not be repeated. Do not copy
  credentials or confuse readable history with permission to send in the App.
- **Remote Control disconnected after completion:** check the managed job state
  and any active job using its session. A terminal job with no active worker is
  offline by design; its retained history remains readable. The next requested
  live task uses rescue's native `--resume` to reconnect. A default local
  continuation reads/writes the native transcript without updating that remote
  view. Do not start an idle worker,
  send a dummy prompt, or create a second local view just to hide the banner.
  If the user wants Desktop to take over, explain that change separately.
- **Archived:** older CLI jobs may archive the remote view and hide its sidebar
  entry while preserving history. Opening the link does not unarchive it.
  When restoring a requested conversation, use the App's normal Unarchive
  action on that verified session, then check its actual sidebar entry and
  expected message text. This does not imply task failure or deletion.
  Unarchive does not restart a local process. Continue through a new managed job
  resuming the native session. A previously archived page may need Unarchive
  after reconnection and reloading to recover missed messages.
- **Stale headless history:** use View > Reload and verify the latest expected
  text once. Reopening the local link or reloading may still leave cached
  content; do not promise either refreshes an already imported session.
  For local-only viewing, read the versioned
  [local session findings](../../references/local-session-sync.md).

Do not send a prompt just to refresh the page, alter App indexes/feature gates,
or treat an active connection as proof that Desktop has shown its contents.
Keep one session writer: the user takes control only when Codex is idle.
Live Remote Control synchronizes history through Anthropic servers; saving or
importing a local transcript alone does not provide live mirroring.
