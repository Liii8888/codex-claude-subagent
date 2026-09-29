---
name: adversarial-review
description: Ask a fresh read-only Claude Code session to challenge an implementation's design, assumptions, tradeoffs, rollback path, and hidden failure modes. Use for risky architecture, migrations, security-sensitive changes, or when the user explicitly wants stronger scrutiny than a normal review.
---

# Claude Adversarial Review

Use `<plugin-root>/scripts/claude_subagent.py`, resolved two directories above
this file.
Every runtime invocation must execute outside the Codex workspace sandbox using
that exact installed executable as the narrow approved command prefix.

Accept the same execution, scope, model, and effort arguments as
`$claude-subagent:review`, plus free-text focus that must be preserved.
Use the same Codex-collected diff/untracked evidence bundle; Claude must not
run Git or shell commands to reconstruct it.

Choose effort from the concrete failure modes and verification burden using the
[shared effort policy](../../references/effort-selection.md), Feature ID
`claude-effort-selection`. Honor the user's level; justify `xhigh` or `max`
from the task rather than automatically assigning it to adversarial review.

Construct a review prompt that asks Claude to:

- identify the strongest credible failure cases;
- challenge assumptions and rejected alternatives;
- inspect rollback, partial failure, concurrency, security, and data-loss paths;
- separate release blockers from optional improvements;
- cite concrete files and evidence rather than speculate.

Choose a concise title following the review Skill's naming guidance.
Run `--kind adversarial-review --mode read --effort <selected-level> --title "<title>"`.
Default to local headless execution; add `--live` only when the user explicitly
requests Remote Control/cloud synchronization, following the review Skill.
Use direct receipt-only execution from
[program dispatch](../../references/program-dispatch.md); only explicit
background work with automatic return uses its disclosed compatibility relay.

The runtime rejects write mode for this kind and removes shell/write tools.
Remain read-only. Do not turn adversarial review into automatic pessimism or
style commentary, and do not fix findings in this skill.
