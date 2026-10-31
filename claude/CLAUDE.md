# This machine: osnova-vps (PRODUCTION + personal dev)

netcup RS 4000 G12 (12 dedicated EPYC cores / 32 GB ECC / 1 TB NVMe), Debian 13,
hostname `osnova-vps`, public IPv4 159.195.252.239. Runs BOTH live production
services and dima's personal dev environment (decided 2026-09-07: a separate prod
host or VM only once colleagues depend on it daily). Unlike a disposable devbox,
mistakes here take down services people use.

Tailscale: this box is `osnova-vps` at 100.93.13.127 (pinned 2026-09-07, same address as
the old box), so box-hub (http://100.93.13.127:8123, ex photo-drop) and dockge (http://100.93.13.127:5001)
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
- Forgejo API calls (create/archive a repo, …): a temporary token minted with the
  Forgejo CLI and deleted right after, nothing kept on the box (decided 2026-10-31).
  Recipe: osnova-infra CLAUDE.md, "Common workflows".

## Dev workflow

- Projects live in `~/dev/<project>`: flat, one dir per repo, NEVER moved
  (Claude Code history and memory are keyed by path). One Claude conversation
  per project (new tab, by hand from an attached terminal: `zellij action new-tab --name <p> --cwd ~/dev/<p>`).
  Agents never add a tab while no client is attached: on zellij 0.45.1 that makes the next attach
  panic the whole session (osnova died this way 2026-10-14 and -15); the hook
  (`claude/hooks/zellij-no-new-tab.py`) allows new-tab only while `list-clients` shows a client.
  A successor orchestrator opens as a new tab in its predecessor's own zellij session (founder 2026-10-31):
  `zellij -s <s> action new-tab --name <seat> --cwd <dir>`, only while `action list-clients` shows a client; start it
  by pane id (`action list-panes -t -c` → `action write-chars -p terminal_N …` + `action write -p terminal_N 13`),
  with the prompt in a file and a launch script (fish reads `(…)` in an inline prompt as a command). No client
  attached: reuse an idle tab there by pane id, else `zj-spawn <new-session> <cwd> <cmd…>`. Unattended, plain
  `rename-tab`, `go-to-tab-name` and `write-chars` without `-p` silently do nothing (tested 2026-10-15).
  Persistent session `main`: `zellij attach main`, never bare `zellij` (creates
  strays). Recreated at boot by the user unit `zellij-main.service`.
- RAM: 32 GB. EVERY zellij session runs inside the user slice `zellij.slice`
  (MemoryHigh=24G, MemoryMax=26G since 2026-10-17; 18/20 thrashed), so everything started in them (Claude Code, cargo,
  node) shares one 26 GB cap; production keeps a guaranteed 4 GB (system.slice MemoryLow, osnova-infra). Starting from SSH is fine: the fish
  `zellij` function wraps it in `systemd-run --user --scope --slice=zellij.slice`, and zj-spawn and
  zellij-main.service join the same slice (since 2026-10-15; before that, SSH-started sessions were
  uncapped). Check: `systemctl --user status zellij.slice`. earlyoom prefers killing
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
- box-hub (since 2026-10-26): ONE tailnet page every session uses, tabs **Drop · Models · Pictures**,
  each grouped by PROJECT (the repo a thing came from), then folder, newest first, with search; Drop is
  the phone inbox, Unsorted what has no known origin. http://100.93.13.127:8123/ (8125 is the same server,
  opening on Models; all old 8123/8125 links work). `box-hub.service`, always up. Source: `~/dev/box-hub`
  (`SPEC.md` has the routes and rules). A `~/lab` folder's project is inferred from which repo's sessions
  used it first (no list of repos: a new `~/dev/<repo>` becomes a group by itself); when you make a lab
  folder for a repo, also write its name into `~/lab/<slug>/.origin` (one line, e.g. `osnova-product`),
  which beats the guess. A repo that keeps its own models or pictures in its tree gets a root in the unit
  (`--root NAME=PATH --project NAME=<repo>`); never `~/dev/asml`.
  photo-drop.service and model-view.service are disabled, kept until box-hub has had a day of use.
- Sending images or files (zip, pdf, …) to an agent from the phone: box-hub's Drop tab
  (http://100.93.13.127:8123). One pick ("photos" or "files" button) = one numbered batch in
  `~/drop/<n>/` plus an optional note. Then "look at the newest" or "batch 7": read `note.md`
  and the shots (the `/photos` skill).
- Showing dima a 3D model (any project, decided 2026-09-26): a box-hub model link, never a
  screenshot, an artifact or a file; he opens it on the phone. Put the `.glb` under
  `~/lab/YYYY-MM-slug/` and send `http://100.93.13.127:8125/?glb=/r/lab/YYYY-MM-slug/<file>.glb`
  (`&lines=1` for a `<file>_lines.glb` drawing twin; other roots: `/r/NAME/...`, the SCHK site's is `schk`).
  The marketing laser cutter is the built-in root (`?size=6025&view=door&door=1`); its viewer page stays in
  `~/dev/osnova-marketing-model` (`tools/glbview.html`), box-hub only serves it. He answers with its Send
  view button: picture, note and a link to that exact view land in `~/drop` as a batch.
- Showing dima a picture (PNG/JPG/WebP/GIF, any project, decided 2026-10-26): a box-hub Pictures link,
  not an artifact, not a file path. Put it under `~/lab/YYYY-MM-slug/` (or a root's folder) and send
  `http://100.93.13.127:8123/p/lab/YYYY-MM-slug/<file>.png` (one picture, swipe for the rest of the
  folder) or `http://100.93.13.127:8123/#pictures/<repo>/lab/YYYY-MM-slug` (the folder's gallery). Names:
  letters, digits, `._-` only (a name with a space or other character is not listed), at most 5 folders deep.
- Two GitHub accounts (unchanged): `Sorbieskis` (personal) and `dsuchank`
  (`~/dev/asml`, own key + noreply email via an `includeIf`). Keep `Sorbieskis`
  the ACTIVE gh account and use `ghw <cmd>` for work: `gh auth switch` is
  global, and osnova-product's `./bin/ci` then 404s on a repo the work account
  can't see and reports "API unreachable", which looks like CI being down.

## What lives where

```
~/dev/<repo>            code, flat, one dir per repo, NEVER moved (CC history/memory keyed by path)
~/dev/osnova-marketing-model  exception 1: a second clone of osnova-marketing for its model session (repo decision 34); its CC memory dir links to the main clone's
~/dev/schk-software-model     exception 2: the same for schk-software (repo decision 18); its models/ is the model viewer's root `schk` (/r/schk/...)
~/dev/asml/             work account (dsuchank)
~/dev/osnova-infra      source of /opt/stacks (deploy.sh) and host config (bootstrap.sh); never edit /opt/stacks by hand
~/lab/YYYY-MM-slug      experiments + lab-* containers, expire 60 days after last change (in use since 2026-09, expiry not automated yet; its GLBs and pictures show in box-hub)
~/drop/<n>/             phone batches from box-hub's Drop tab (http://100.93.13.127:8123)
~/wt/osnova-<n>         osnova-product `bin/wt` slots: warm git worktrees with build caches (~260 GB for 6, by design); manage with bin/wt, never rm by hand
~/dsh-play/             the dsh seat + build lane's home (lane scratch clones, relay, replays; ~110 GB, mostly build output)
~/git/<name>.git        local bare remotes (locator.git is ~/dev/asml/locator's remote)
~/vault/                Obsidian; livesync bridge writes here; hourly git push via crontab (bin/vault-backup.sh)
~/.dotfiles/            fish/nvim/yazi/zellij/git config, mise manifest, user units, bin/ scripts, claude/ tracked parts, install.sh
  ~/.claude/{CLAUDE.md,settings.json,skills} are symlinks INTO it; everything else in ~/.claude is state, never tracked
~/.local/bin/           mise binary + symlinks to .dotfiles/bin (work, dsh, photo-drop, osnova-pull, vault-backup.sh, zellij-main-boot.sh)
~/.local/share/mise     every mise-managed tool (node, python, uv, zellij, ...); nothing hand-placed in ~/.local/bin or /usr/local/bin
~/.local/opt/           hand-installed trees not on PATH by themselves: verapdf (moved here 2026-09-27)
~/.venvs/pw             Playwright venv (uv). ~/.cache ~/.cargo ~/.rustup ~/.npm ~/.venvs are rebuildable: not backed up, not migrated
~/.config/systemd/user  box-hub.service (drop + 3D models + pictures for the phone, http://100.93.13.127:8123/ and :8125),
                        zellij-main.{service,timer}; photo-drop + model-view disabled (all in .dotfiles/systemd/user)
/opt/stacks/<svc>       running prod compose + decrypted .env (generated by deploy.sh, root-deployed)
/opt/scripts            pg-backup, uptime-check, box-cleanup, stack-drift (from osnova-infra/scripts)
/var/backups/postgres   daily pg-backup dumps (03:30); restic ships them + the rest offsite to Cloudflare R2 at 03:40
/etc/systemd/system     forgejo-runner, minecraft (both in osnova-infra/host/systemd)
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
  `mise install`, rustup, fish as login shell, user units box-hub +
  zellij-main, hourly vault-backup crontab. The old Void-only bootstrap.sh is
  superseded.
- Rule: nothing hand-placed in `/usr/local/bin` or `~/.local/bin` any more.
  Add it to the mise manifest. `~/bin` is retired; scripts live in
  `~/.dotfiles/bin`, linked into `~/.local/bin` by install.sh.
- Docker: compose project = prod stack name | `osnova-dev` (dev postgres
  `osnova-pg-dev`, 127.0.0.1:5433, label tier=dev, 2 GB cap) | `lab-*` for
  experiments (named YYYY-MM-slug under `~/lab`, expire after 60 days). An
  unlabeled container is a leak. Networks: web, db (prod only) | lab.

## Before building anything (dima, 2026-10-24)

- Check first whether an established tool, mod, library or service already does it; search before
  designing. Build only the gap it leaves, and say what was checked.
- A question or decision that turns on a number about the box, infra, CI or the loop: run `obs` first, cite it, or say it is unmeasured.

## Don'ts

- Don't reconfigure ufw, sshd, tailscale, or the zellij-main service/timer
  unless explicitly asked.
- Don't restart Docker or production containers as a debugging reflex.
- Don't put secrets in repos: SOPS for infra, `.env` (gitignored) for dev.
- Don't hand-install tools; add them to `~/.dotfiles/mise/config.toml`.
- Don't start containers without a compose project name or tier label.
