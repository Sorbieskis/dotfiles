# This machine: osnova-vps (PRODUCTION + personal dev)

netcup RS 4000 G12 (12 dedicated EPYC cores / 32 GB ECC / 1 TB NVMe), Debian 13,
hostname `osnova-vps`, public IPv4 159.195.252.239. Runs BOTH live production
services and dima's personal dev environment (decided 2026-09-07: a separate prod
host or VM only once colleagues depend on it daily). Unlike a disposable devbox,
mistakes here take down services people use.

**Migrated from the Hetzner CPX32 on 2026-09-07.** Old box 178.104.79.134
(Tailscale `osnova-vps-old` after the rename): stacks stopped, kept as rollback
until ~2026-09-14. Runbook: `~/dev/osnova-infra/MIGRATION.md`.

Tailscale: this box is `osnova-vps` at 100.93.13.127 (pinned 2026-09-07, same address as
the old box), so photo-drop (http://100.93.13.127:8123) and dockge (http://100.93.13.127:5001)
kept their URLs. Admin SSH is Tailscale SSH only: `ssh dima@osnova-vps` / `ssh root@osnova-vps`.
Public 22 is closed (UFW) and filtered (netcup SCP policy `osnova-vps`, 2026-09-10).

## Production on this box (Docker, do not disturb casually)

- Caddy (:80/:443), Outline (wiki.osnovasystems.com), Forgejo
  (git.osnovasystems.com, +registry, SSH :222), Pocket-ID, osnova-product +
  staging, Postgres, Dockge, diun, livesync (CouchDB + bridge), forgejo-runner
  (host unit), nginx modpack site :8080.
- Minecraft: stopped and disabled, stack at `/opt/stacks/minecraft`, world +
  backups migrated, now a 7 GB cap and `restart: on-failure` (the old
  idle-restart churn is gone). Start: `sudo systemctl enable --now minecraft.service`.
- Infra-as-code: `~/dev/osnova-infra`. Read its CLAUDE.md before touching
  anything host- or stack-related. Never edit `/opt/stacks` directly: edit the
  repo, push, deploy via `./scripts/deploy.sh <service>`. A weekly drift check
  pings ntfy if `/opt/stacks` diverges from the repo.

## Dev workflow

- Projects live in `~/dev/<project>`: flat, one dir per repo, NEVER moved
  (Claude Code history and memory are keyed by path). One Claude conversation
  per project (new tab: `zellij action new-tab --name <p> --cwd ~/dev/<p>`).
  Persistent session `main`: `zellij attach main`, never bare `zellij` (creates
  strays). Recreated at boot by the user unit `zellij-main.service`.
- RAM: 32 GB. The `main` session runs inside `zellij-main.service` with
  MemoryMax=20G, so everything started in it (Claude Code, cargo, node) shares a
  20 GB cap and cannot evict the stacks. earlyoom prefers killing
  cargo/rustc/clippy/rust-analyzer/node/python3 and never
  claude/zellij/postgres/docker/sshd/tailscaled. Check with `free -m`. Truly
  huge builds go outside zellij: `systemd-run --user -p MemoryMax=8G --scope cargo …`.
- sudo is passwordless. Docker available. The box may auto-reboot ~04:00 for
  security updates; the `main` session recreates itself and Claude resumes, but
  dev servers need restarting.
- SSH is Tailscale-only; public 22 is closed. The Forgejo git remote uses
  port 222. Console break-glass: netcup SCP VNC console, log in as `dima`
  (password set 2026-09-10, in the password manager) and sudo up. Root is
  locked (`!`) and sshd is key-only, so `dima` is the ONLY way in if Tailscale
  breaks — verify with `sudo passwd -S dima` (must read `P`, not `L`).
- Sending images to an agent from the phone: `photo-drop` (unchanged).
  http://100.93.13.127:8123 (tailnet-only, `photo-drop.service`, always up).
  One pick = one numbered batch in `~/drop/<n>/` plus an optional note. Then
  "look at the newest" or "batch 7": read `note.md` and the shots. Source:
  `~/.dotfiles/bin/photo-drop`.
- Showing dima a 3D model (any project, decided 2026-09-26): a link to the model
  viewer, never a screenshot, an artifact or a file. http://100.93.13.127:8125/
  (tailnet-only, `model-view.service`, always up; he opens it on the phone). Put
  the `.glb` under `~/lab/YYYY-MM-slug/` and send
  `http://100.93.13.127:8125/?glb=/r/lab/YYYY-MM-slug/<file>.glb` (`&lines=1` for a
  `<file>_lines.glb` drawing twin). A project that keeps its own models gets its own
  folder in the unit (`--root NAME=PATH`, then `/r/NAME/...`); never `~/dev/asml`.
  The marketing laser cutter is the built-in root (`?size=6025&view=door&door=1`).
  He answers with its Send view button: picture, note and a link to that exact view
  land in `~/drop` like a photo-drop batch. Source:
  `~/dev/osnova-marketing-model/model/serve.py` + `tools/glbview.html`.
- Two GitHub accounts (unchanged): `Sorbieskis` (personal) and `dsuchank`
  (`~/dev/asml`, own key + noreply email via an `includeIf`). Keep `Sorbieskis`
  the ACTIVE gh account and use `ghw <cmd>` for work: `gh auth switch` is
  global, and osnova-product's `./bin/ci` then 404s on a repo the work account
  can't see and reports "API unreachable", which looks like CI being down.

## What lives where

```
~/dev/<repo>            code, flat, one dir per repo, NEVER moved (CC history/memory keyed by path)
~/dev/osnova-marketing-model  the one exception: a second clone of osnova-marketing for its model session (repo decision 34); its CC memory dir links to the main clone's
~/dev/asml/             work account (dsuchank)
~/dev/osnova-infra      source of /opt/stacks (deploy.sh) and host config (bootstrap.sh); never edit /opt/stacks by hand
~/lab/YYYY-MM-slug      experiments + lab-* containers, expire 60 days after last change (in use since 2026-09, expiry not automated yet; its GLBs show in the model viewer)
~/drop/<n>/             phone batches from photo-drop (http://100.93.13.127:8123)
~/vault/                Obsidian; livesync bridge writes here; hourly git push via crontab (bin/vault-backup.sh)
~/.dotfiles/            fish/nvim/yazi/zellij/git config, mise manifest, user units, bin/ scripts, claude/ tracked parts, install.sh
  ~/.claude/{CLAUDE.md,settings.json,skills} are symlinks INTO it; everything else in ~/.claude is state, never tracked
~/.local/bin/           mise binary + symlinks to .dotfiles/bin (work, dsh, photo-drop, osnova-pull, vault-backup.sh, zellij-main-boot.sh)
~/.local/share/mise     every mise-managed tool (node, python, uv, zellij, ...); nothing hand-placed in ~/.local/bin or /usr/local/bin
~/.local/opt/           hand-installed trees not on PATH by themselves, e.g. verapdf (planned, not done)
~/.venvs/pw             Playwright venv (uv). ~/.cache ~/.cargo ~/.rustup ~/.npm ~/.venvs are rebuildable: not backed up, not migrated
~/bin                   retired 2026-09-07; its scripts moved to ~/.dotfiles/bin
~/.config/systemd/user  photo-drop.service, model-view.service (3D model viewer for the phone, marketing models
                        + ~/lab, http://100.93.13.127:8125/), zellij-main.{service,timer} (all in .dotfiles/systemd/user)
/opt/stacks/<svc>       running prod compose + decrypted .env (generated by deploy.sh, root-deployed)
/opt/scripts            pg-backup, uptime-check, box-cleanup, stack-drift (from osnova-infra/scripts)
/var/backups/postgres   daily pg-backup dumps (03:30); restic ships them + the rest offsite to Cloudflare R2 at 03:40
/etc/systemd/system     forgejo-runner, minecraft (both in osnova-infra/host/systemd)
Docker: project = prod stack name | osnova-dev (dev pg 5433) | lab-*; anything unlabeled is a leak. Networks: web, db (prod only) | lab
Secrets: SOPS .env.enc in osnova-infra, age key /root/.config/sops/age (Bitwarden); API keys only in ~/.config/fish/secrets.fish (untracked)
```

## One way of doing everything (decided 2026-09-07)

- apt: daemons, system libraries, Debian-packaged CLI tools (osnova-infra
  bootstrap.sh). One Java: default-jre, pulled in by plantuml.
- mise: every user-level runtime and CLI tool (node, python, uv, zellij, yazi,
  lazygit, lazydocker, starship, zoxide, mcfly, typst, dbmate, blender 5.2 LTS
  and gltfpack for the 3D pipeline; Debian's blender is not used), declared in
  `~/.dotfiles/mise/config.toml` (→ `~/.config/mise/config.toml`). fish
  activates mise.
- rustup: Rust only, version pinned by each repo's `rust-toolchain.toml`.
- uv: Python project envs. The Playwright venv `~/.venvs/pw` is built by uv from
  `osnova-product/tests/ui-smoke/requirements.txt`.
- `~/.dotfiles/install.sh` applies the whole dima layer idempotently: symlinks,
  `mise install`, rustup, fish as login shell, user units photo-drop +
  zellij-main, hourly vault-backup crontab. The old Void-only bootstrap.sh is
  superseded.
- Rule: nothing hand-placed in `/usr/local/bin` or `~/.local/bin` any more.
  Add it to the mise manifest. `~/bin` is retired; scripts live in
  `~/.dotfiles/bin`, linked into `~/.local/bin` by install.sh.
- Docker: compose project = prod stack name | `osnova-dev` (dev postgres
  `osnova-pg-dev`, 127.0.0.1:5433, label tier=dev, 2 GB cap) | `lab-*` for
  experiments (named YYYY-MM-slug under `~/lab`, expire after 60 days). An
  unlabeled container is a leak. Networks: web, db (prod only) | lab.

## Don'ts

- Don't reconfigure ufw, sshd, tailscale, or the zellij-main service/timer
  unless explicitly asked.
- Don't restart Docker or production containers as a debugging reflex.
- Don't put secrets in repos: SOPS for infra, `.env` (gitignored) for dev.
- Don't hand-install tools; add them to `~/.dotfiles/mise/config.toml`.
- Don't start containers without a compose project name or tier label.
