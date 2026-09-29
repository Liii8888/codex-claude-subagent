---
name: cancel
description: Safely stop a queued or running Claude worker through its owning runtime. Use only when the user explicitly asks to cancel, stop, or abort a selected Claude job.
---

# Cancel Claude Job

Resolve `<plugin-root>` two directories above this file.
Require an unambiguous job id. If absent, show active jobs and ask which one to
stop rather than guessing.

1. Run the exact installed executable outside the workspace sandbox:

   `"<plugin-root>/scripts/claude_subagent.py" cancel <job-id>`

   Queued jobs are cancelled before launch. For a supervised job, the owning
   runner receives a durable cancellation request and stops its process group.
   This normal path uses a kernel lease, without `ps` or title matching.
2. Verify terminal `cancelled` state with `status <job-id> --json`. Pending
   cancellation is not completed cancellation. Keep the record and result.
3. Only for a known background compatibility job, collect the exact
   `claude_<job-id-suffix>` child; interrupt it if it stays active after the
   worker stops. Normal direct jobs have no Codex child.

For a legacy job or crashed runner, recovery validates PID start time, process
group and native session arguments, including `--resume`. If verification is
unavailable, report the limitation. Never use broad `pkill`, title-only matching,
or an unverified PID to work around it.

The same cancellation path handles live stream-json workers. Retaining the
Remote Control view does not mean the worker is still running. Keep saved
history and any completed result, and verify the process has stopped. A crash
or forced kill is not proof of sidebar retention. Do not delete or unarchive
a session to simulate process cancellation.
