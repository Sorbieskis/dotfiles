# Dotfiles

Personal configuration for dima's boxes. Lives at `~/.dotfiles`; everything
else is a symlink into it. Applied by `install.sh` (2026-09-07; the old
Void-only `bootstrap.sh` is superseded and kept only for reference).

## What's Inside

- **install.sh** - applies the whole dima layer idempotently (see below)
- **mise/config.toml** - THE list of user-level runtimes and CLI tools (see below)
- **fish/** - Fish shell config: vi mode, mise activation, starship, mcfly, fzf, zoxide, `ghw`
- **nvim/** - Neovim configuration (based on kickstart.nvim)
- **yazi/** - yazi file manager config
- **zellij/** - Zellij config + `layouts/main.kdl` (persistent Claude Code session)
- **claude/** - the tracked parts of `~/.claude` (CLAUDE.md, settings.json, skills/); see `claude/README.md`
- **systemd/user/** - `photo-drop.service`, `zellij-main.{service,timer}`
- **bin/** - scripts, linked into `~/.local/bin`: `work`, `dsh`, `photo-drop`, `osnova-pull`, `vault-backup.sh`, `zellij-main-boot.sh`
- **.gitconfig** - Git identity and settings (two GitHub accounts via `includeIf`)
- **.wezterm.lua** - WezTerm terminal keybindings

## How It Works (Symlinks)

Programs read from their standard locations; those are symlinks into this repo:

```
~/.config/fish/config.fish   →  ~/.dotfiles/fish/config.fish
~/.config/nvim/              →  ~/.dotfiles/nvim/
~/.config/yazi/yazi.toml     →  ~/.dotfiles/yazi/yazi.toml
~/.config/mise/config.toml   →  ~/.dotfiles/mise/config.toml
~/.config/zellij/layouts/main.kdl  →  ~/.dotfiles/zellij/layouts/main.kdl
~/.config/systemd/user/*     →  ~/.dotfiles/systemd/user/*
~/.local/bin/<script>        →  ~/.dotfiles/bin/<script>
~/.claude/{CLAUDE.md,settings.json,skills}  →  ~/.dotfiles/claude/...
~/.gitconfig                 →  ~/.dotfiles/.gitconfig
```

Exception: `~/.config/zellij/config.kdl` is a COPY, not a link, so the
per-platform clipboard command can be edited without dirtying the repo.

Edit from anywhere (`nvim ~/.gitconfig` and `nvim ~/.dotfiles/.gitconfig` are
the same file); commit from `~/.dotfiles`.

## Setting Up a New Machine

Prerequisites (root):

1. System packages, daemons and host config come from `osnova-infra`'s
   `scripts/bootstrap.sh` (apt). fish must be in `/etc/shells` before step 3
   (the Debian package registers it; verify).
2. `sudo loginctl enable-linger dima` so user units start at boot without a login.

Then, as dima:

```bash
git clone https://github.com/Sorbieskis/dotfiles.git ~/.dotfiles
~/.dotfiles/install.sh
```

`install.sh` is idempotent and has no package manager in it. It:

- creates the symlinks listed above (and copies `zellij/config.kdl` if absent)
- links `bin/*` into `~/.local/bin` and `systemd/user/*` into `~/.config/systemd/user`
- installs mise if missing, then `mise install` for everything in `mise/config.toml`
- installs rustup (minimal profile, Rust only; each repo pins its version in `rust-toolchain.toml`)
- sets fish as the login shell
- enables `photo-drop.service`, `zellij-main.service` and `zellij-main.timer`
- installs the hourly `vault-backup.sh` crontab (minute 17, log in `~/.vault-backup.log`)

Manual afterwards: `~/.config/fish/secrets.fish` (API keys, untracked), SSH
keys, `gh auth login` for both accounts, `:Lazy sync` in nvim.

## Tools: one way of doing everything

| layer | owns | where declared |
|---|---|---|
| apt | daemons, system libraries, Debian-packaged CLI tools | `osnova-infra/scripts/bootstrap.sh` |
| mise | every user-level runtime and CLI tool | `mise/config.toml` here |
| rustup | Rust only | each repo's `rust-toolchain.toml` |
| uv | Python project environments (uv itself comes from mise) | per project |

`mise/config.toml` is the single tool list: node, python, uv, zellij, yazi,
lazygit, lazydocker, starship, zoxide, mcfly, typst, dbmate. To add a tool, add
it there and run `mise install`; do not hand-place binaries in `~/.local/bin`
or `/usr/local/bin`. `fish/config.fish` runs `mise activate fish` before the
starship/mcfly/zoxide init lines, so the tools are on PATH in every shell.

## Persistent zellij + Claude Code session (systemd)

The box reboots periodically (unattended-upgrades ~04:00), which kills every
process including zellij and the Claude Code inside it. These bring it back:

| File | Role |
|---|---|
| `zellij/layouts/main.kdl` | Layout: a `claude` tab that runs `claude --continue` in `~/dev/osnova-product`, plus a shell tab |
| `bin/zellij-main-boot.sh` | Recreates the `main` session detached from that layout (flock single-instance; no-op if a live session exists) |
| `systemd/user/zellij-main.service` | Runs the boot script at startup with `RemainAfterExit=yes` and `MemoryMax=20G` |
| `systemd/user/zellij-main.timer` | Self-heal: re-runs the script 2 min after boot and every 15 min |

`RemainAfterExit=yes` keeps the unit's cgroup alive for as long as the session
lives, so the zellij server and every pane in it (Claude Code, cargo, node)
share the 20 GB cap and cannot evict the production stacks. `KillMode=process`
means `systemctl --user stop` does not tear down a session you are using.
Consequence: the timer only heals a session whose unit is inactive; a dead
session under a live unit needs `systemctl --user restart zellij-main`.

After a reboot: SSH in and `zellij attach main` (never bare `zellij`, it
creates stray sessions). The conversation itself persists via Claude Code's own
history (`claude --continue`), independent of zellij.

`work <project>` (in `bin/`, linked to `~/.local/bin`) attaches to or creates a
per-project zellij session in `~/dev/<project>`; with no argument it lists
`~/dev`.

## Notes

- **Never commit secrets.** No `.env`, API keys or credentials; `secrets.fish` stays untracked.
- **Only the tracked parts of `~/.claude`** are here; `.credentials.json` and the ~GB of runtime state are not, and must never be (see `claude/README.md`).
- `fish_variables` and other generated files are ignored.
- The `.git/` directory is in `~/.dotfiles/`, not in `~/.config/nvim/` or elsewhere.

## Troubleshooting

- Symlink broken or a config not loading: `readlink -f <path>` should point into
  `~/.dotfiles`; re-run `~/.dotfiles/install.sh` to recreate all links.
- Changes not showing in git: `cd ~/.dotfiles && git status`.
- `settings.json` stopped tracking after a `/config` change: the CLI may have
  replaced the symlink with a file; see `claude/README.md` for the re-link.
- `main` session gone but `zellij-main.service` active: `systemctl --user restart zellij-main`.

---

**Repository:** [github.com/Sorbieskis/dotfiles](https://github.com/Sorbieskis/dotfiles)
