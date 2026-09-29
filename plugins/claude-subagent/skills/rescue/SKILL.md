---
name: rescue
description: Delegate implementation, investigation, debugging, or a follow-up to an official Claude Code worker controlled by Codex. Use when Claude should own the task, rather than only review changes. Supports live Desktop viewing and native session continuation.
---

# Claude Rescue

Resolve `<plugin-root>` two directories above this file. Invoke its
`scripts/claude_subagent.py` executable outside the Codex workspace sandbox,
using only that exact installed path as the approval prefix. A remembered
prefix still requires outside-sandbox execution on each call; never substitute
a broad `python3`, `claude`, or shell approval.

## Choose the task

Accept `--wait` or `--background`, `--read-only` or `--write`,
`--resume <job-id>`, `--live` or `--headless`, `--model`, `--effort`, and task text.
Defaults: write mode, model `sonnet`, local headless execution. Effort accepts
`low|medium|high|xhigh|max` and controls the Claude worker.
If the user did not choose background execution, wait for the result.

Before each delegation, choose effort from the task/prompt using the shared
[effort-selection policy](../../references/effort-selection.md), Feature ID
`claude-effort-selection`. Honor a user-specified level; otherwise select
and briefly explain it. Every new job, including a resumed follow-up, requires
an explicit `--effort`; there is no fixed effort default.

For a new conversation, choose a concise `--title` in the user's language,
such as `Project · UI polish`. Use the task's purpose, not a job ID or the full
prompt; avoid sensitive details in sidebar metadata. Native follow-ups preserve
the existing App title, including user edits, even if a new title is supplied.

Omit the runtime's `--live` flag by default: use native local session records
without Remote Control. Enable `--live` only when the user explicitly requests
Remote Control/cloud synchronization. A request to see Claude in Desktop is not
that opt-in. Live mode synchronizes history through Anthropic servers; never
switch transports silently or enable it to work around a stale local view.
Local execution, a shared native session, and automatic Desktop refresh are
separate capabilities. For a local-only display request, use the
[local session findings](../../references/local-session-sync.md); successful
headless execution or import does not establish real-time App viewing.

Write mode uses Claude `auto`; Sonnet is the verified model family. Other
models remain available for read-only work. `--unsafe-bypass` is an explicit
per-task user override, never a workaround selected by the agent.

## Supply the necessary context

Use the actual Codex workspace or explicitly selected checkout as `--cwd`, never
the plugin's installation directory. The runtime starts Claude there and checks
the first native cwd report; `cwd_verified` records that evidence separately
from Desktop sidebar grouping.

Claude does not inherit the Codex conversation. The task brief must contain the
objective, authorized scope, relevant decisions, canonical project/context
paths, and observable completion criteria. For follow-ups, provide only the
delta and use native resume. Do not copy unrelated chat history.

The runtime supplies scoped `AGENTS.md` files and the registered project overview
(or nearest `CONTEXT.md`) in each task, including resume. The job's `context.json`
records paths and hashes of the supplied text. It reads the canonical sources,
not a maintained copy, and stops if a required source cannot be read. Do not
paste those same files into the brief again. Supply additional task-specific
facts when needed without widening the worker's filesystem permissions.
Identify evidence as data, separate from instructions.
Only use Skills available and compatible with Claude's permitted tools. A
shared Skill source does not provide Codex-specific tools or grant new authority.

## Dispatch and collect

1. Keep Codex as controller; do not solve the delegated task before dispatch.
   Write the exact brief to a new `0600` OS-temporary file with a structured
   file-write tool. Never interpolate task text into shell code.
2. Reserve the job:

   `"<plugin-root>/scripts/claude_subagent.py" reserve --kind task --mode <read|write> --cwd "<workspace>" --effort <selected-level> --title "<project · purpose>" [--model ...] [--unsafe-bypass]`

   Add `--live` only for the user's explicit remote-sync opt-in. Reservation
   enforces the configured total (default four) and one writer per checkout or
   overlapping workspace; `run --job` inherits the reserved
   mode and effort. A native follow-up uses the newly reserved transport;
   an old job's Remote Control URL does not authorize reconnecting it.
3. For normal waiting tasks, the main Codex calls the runtime directly. Do not
   spawn a forwarding subagent or choose a second Codex model. Run:

   `"<plugin-root>/scripts/claude_subagent.py" run --job <job-id> --prompt-file "<temp-file>" --receipt-only [--resume-from <old-job-id>]`

   For an explicitly chosen live job that the user wants to watch in Desktop,
   add `--open-desktop`. The runner opens that exact remote view after connecting,
   before sending the task; this avoids leaving the user on a different session.
   Opening the window is not proof of rendered content or completed device login.

   Use the native asynchronous command handle; a program can wait inside the
   tool host without model-driven polling. Follow the compact example and
   background boundary in [program dispatch](../../references/program-dispatch.md).
   Keep the turn active until the command finishes, while doing independent work
   or reporting meaningful progress. A pending tool call is not an idle-thread
   wake-up mechanism.
4. Verify terminal state with `result <job-id> --json`, then read the full result
   once with `result <job-id>`. Failure, cancellation, a missing completion, and
   an interrupted waiter are not success. Never re-run Claude merely because a
   receipt was lost. After writes, Codex checks the actual diff and relevant
   verification before accepting them.
   When the user expects Desktop visibility, include the saved session link and
   name in the delivery, with the archive recovery note from
   [result](../result/SKILL.md). Job completion alone does not prove that its
   sidebar entry remains visible.

Only explicit background work with automatic return uses the compatibility
relay from the dispatch reference. Disclose that one Codex relay is retained
for that mode. Never silently change a normal waiting task to background mode.

Resume only a terminal job in the same working directory. New jobs retain
native Claude history; follow-ups reuse that session, including intervening
Desktop messages. Missing native history is an error. Only legacy jobs without
native persistence use their saved task/result to start a new conversation.

## Control and viewing

Control uses the official CLI's stream-json channel. Live jobs initialize
Remote Control with `keep_session_on_exit`, verify the returned session URL and
the CLI's connected event before submitting the task, and close with `end_session` after saving the
verified result. Headless jobs omit the remote handshake. No mouse or screenshot
is needed to execute tasks, and no idle worker is kept running. See
[session retention](../../references/remote-session-retention.md) for protocol
and upgrade boundaries.
For explicit live jobs, Desktop can show `Remote Control disconnected` while
keeping the history readable. Completion stops the connection; an explicitly
requested live native follow-up reconnects the same session. Default local
follow-ups update the native transcript without reconnecting the old remote
view. Do not restart a worker merely to clear this banner or silently hand
control to Desktop.
For App viewing, sign-in, stale pages, or archived sessions, read
[result](../result/SKILL.md).
The correct cwd does not prove Desktop puts a Remote Control view in the matching
project group. Never claim automatic grouping from a title or transcript path.

The user reads during work and takes control only while Codex is idle. This
agreed single-writer rule does not need repeated confirmation. Fresh tasks get
fresh sessions; the runtime rejects concurrent managed use of one session.
Independent checkouts may write concurrently. Sibling subdirectories in the
same Git checkout share one write slot; a read-only task uses only the total
capacity. A conflict does not authorize creating or selecting a different
checkout silently. Wait or use an already authorized independent checkout.

The runtime blocks Claude delegation, background tasks, hooks/workflows, Web,
and MCP. Do not reintroduce them through a Skill, shell-launched agent, or
Claude-native `--bg`. Keep any external action within the user's task authority.
