# Claude Subagent Development Rules

- This is a local Codex plugin. It may invoke only the installed official
  `claude` CLI; do not add proxies, custom API endpoints, token copying, or
  third-party orchestration services.
- Keep Codex as the controller. Claude processes are single sequential workers:
  always deny the `Agent` tool and disable nested/background delegation.
- Keep every job under an explicitly configured workspace root. Keep Claude Web
  and MCP tools outside the initial capability surface.
- Default autonomous writes to Claude permission mode `auto`.
  `bypassPermissions` must remain an explicit per-job override.
- Use the configured total Claude job limit (default four). Allow independent
  checkouts to write concurrently, but reject overlapping write scopes and
  concurrent managed use of the same native session.
- Keep full prompts, progress streams, and results permission-restricted and
  bounded by the configured retention period.
- Do not enable global lifecycle hooks or an automatic Review Gate without a
  separate explicit user decision.
- Keep the seven public Skills separated by responsibility: rescue, review,
  adversarial-review, status, result, cancel, and setup.
- Run the Python unit tests, every Skill validator, and the plugin validator
  before installation.
