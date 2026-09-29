# Local session viewing

- Feature ID: `claude-local-session-sync`
- Checked: 2026-09-27, macOS, Claude CLI 2.1.283, Claude App 2.9939.2.
- Status: native persistence and local import verified; automatic App refresh
  failed in the tested build. Local headless execution became the Skill default
  on 2026-09-28 at the user's explicit request; this does not resolve App refresh.
- Recheck when Desktop enables local transcript watching or provides a
  supported refresh interface for an imported session.

Pure local viewing is architecturally possible: the CLI writes its native
transcript and a viewer can read or watch that same file. Model inference is
separate and still uses Claude's service. The controller reads current local
progress/results directly, so a stale Desktop view does not hide the result
from Codex. Remote Control remains an explicit opt-in for live App viewing;
never enable it just because the user asks to see a session or its local view
is stale. It is not a theoretical requirement for displaying local data.

## Observed boundary

A fresh headless job saved native history without a Remote Control handshake
or URL. The official `claude://resume?session=<uuid>` link displayed that history
under the expected local project. A second CLI turn natively resumed the same
session, recalled the previous marker, and appended its complete reply without
tool use. Desktop continued showing only the first turn, including after
reopening the same link, normal View > Reload, scrolling to the end, and
switching away and back. This was an automatic-display failure, not lost history.
The project placement observation covers this one workspace only.

The installed App contains local transcript reading and file-watch code, but
its public-facing `listCliSessions` and `openCliTail` wrappers are gated off in
this build. Its discovery code also excludes SDK entrypoints; the print-mode
test records used `sdk-cli`. These are version-specific implementation findings,
not settings to bypass or proof that future clients cannot support local viewing.

For acceptance, keep one writer, verify the native session and cwd, and check
an actual later prompt/reply in the App without a reload or another model turn.
Then check completion and continuation. Import success, a matching ID, or a
reader finding the new text on disk is not enough. Do not replace the requested
native App view with a custom viewer and call that equivalent.

The [official Desktop documentation](https://code.claude.com/docs/en/desktop#coming-from-the-cli)
describes CLI-to-Desktop handoff: `/desktop` saves the session and exits the CLI.
It does not establish simultaneous live mirroring of an independently running
headless worker. Keep local handoff and Remote Control viewing distinct.
