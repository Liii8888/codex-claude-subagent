# Task-aware effort selection

- Feature ID: `claude-effort-selection`
- Status: active
- Introduced / last reviewed: 2026-09-27
- Scope: Codex's selection of Claude effort before each job, including follow-ups.
  This file is the policy source; the runner validates and records the selection.

## Choose before dispatch

Honor an explicit user choice. Otherwise assess the actual prompt, available
context, reasoning difficulty, verification burden, cost of mistakes, and how
closely the user or Codex will review intermediate work. State the chosen level
and one short task-specific reason when dispatching, then pass `--effort`.

| Level | Useful starting point, adjusted for the selected model |
| --- | --- |
| `low` | A small, clear task with little judgment or a quick draft for immediate feedback |
| `medium` | Bounded implementation with a clear specification and straightforward checks |
| `high` | Uncertain root causes, interacting components, substantial verification, or consequential edge cases |
| `xhigh` | Especially difficult reasoning or correctness work that warrants more computation |
| `max` | Exceptional autonomous work where the expected benefit justifies the highest spend |

These are decision aids, not fixed mappings from Skill names or prompt length.
For Sonnet 5, `high` is the provider's coding default; `medium` is a deliberate
tradeoff, and a short coding prompt can still require high effort. Reassess on
follow-up; keep the previous level when the needs have not changed.

Resolve material gaps in the brief before delegating, using available context
first and asking only when needed. If a failure reflects a wrong requirement or
approach, correct that first. Raise effort when evidence points to insufficient
reasoning or verification. A separate verification job is useful when warranted,
but this policy does not automatically add review rounds or expand authority.

## Execution and cache boundaries

Every new reservation or direct run requires an explicit level. `run --job`
uses the recorded selection and rejects a conflicting override. To change level
for a continuation, reserve a new job with the selected effort, then use native
resume. Legacy `default_effort` configuration is ignored. The worker environment
does not inherit `CLAUDE_CODE_EFFORT_LEVEL`; the user's global settings are not
rewritten. Job records show the requested level; model or organization limits
can reduce the applied level.

Effort is not a token budget or a guarantee of quality or savings. Cache-preserving
mid-conversation changes depend on the model and CLI. Do not promise that benefit
for Sonnet 5 or repeatedly switch a long session merely to follow a preset cycle.
Use the official CLI flag; no API replacement or nested delegation is introduced.

## Sources and lifecycle

- [Thariq Shihipar, Using Claude Code: Spending your effort](https://claude.dev/blog/spending-your-effort/),
  2026-09-25: task-dependent allocation and verification. Its examples chiefly
  concern Opus 5.5 and Fable 5.1; this plugin has not benchmarked those results
  or a cost saving for its Sonnet worker.
- [Claude Code model configuration](https://code.claude.com/docs/en/model-config#adjust-effort-level)
  and [Claude effort documentation](https://platform.claude.com/docs/en/build-with-claude/effort),
  checked 2026-09-27: model-specific levels, overrides and cache behavior.

Revisit this feature when the chosen model or effort/cache semantics change,
when the official CLI gains task-aware automatic selection that could replace
it, or when observed outcomes contradict this guidance. These are review triggers,
not scheduled monitoring. When replacing or retiring the policy, update this
same Feature ID with status, date, reason and replacement; update the linked
Skills, runner requirements, tests and README together. Do not leave an obsolete
explicit-effort requirement after its policy has been retired.
