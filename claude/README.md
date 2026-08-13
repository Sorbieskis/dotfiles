# ~/.claude — the tracked parts

Symlinked back into `~/.claude/`, same pattern as `fish/` and `systemd/user/`:

| tracked | what it is |
|---|---|
| `CLAUDE.md` | machine-wide instructions loaded into every agent session |
| `skills/` | user-level slash commands, available in every project |
| `settings.json` | permissions deny-list, model, effort, theme |

## Do NOT track the rest of ~/.claude

Not tidiness — two hard reasons:

- **`.credentials.json` is an auth token.** Symlinking the whole directory in,
  which is the obvious "simplification", commits it. The dotfiles repo mirrors to
  GitHub.
- **~1.2 GB of runtime state**: `projects/` (470M, conversation transcripts —
  every one of them is also a record of whatever was in context), `jobs/` (611M),
  `file-history/` (80M), plus caches and session dirs. Churns constantly and would
  make the repo unusable.

Only add a path here after checking it is configuration, not state or secrets.

## Caveat: settings.json can silently un-track itself

The CLI rewrites it when you change something via `/config`. If it writes
atomically (temp file + rename) it REPLACES the symlink with a regular file, and
the change stops reaching this repo — silently, with no error, looking exactly
like nothing happened. If `git status` here goes quiet after a settings change,
check with `ls -l ~/.claude/settings.json` and re-link:

    mv ~/.claude/settings.json ~/.dotfiles/claude/settings.json
    ln -s ~/.dotfiles/claude/settings.json ~/.claude/settings.json
