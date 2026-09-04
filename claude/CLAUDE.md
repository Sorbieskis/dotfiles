# This machine: osnova-vps (PRODUCTION + personal dev)

Hetzner CPX32 (4 vCPU / 8 GB) running BOTH live production services and dima's
personal dev environment. Unlike a disposable devbox, mistakes here take down
services people use.

**A move to a netcup root server is planned (prep done 2026-09-04, box not ordered yet).**
Runbook: `~/dev/osnova-infra/MIGRATION.md`; data mover: `scripts/migrate-pull.sh` there.
Until the cutover nothing about this box changes — the Tailscale IP below is meant to be
pinned onto the new node so these notes stay true.

## Production on this box (Docker — do not disturb casually)

- Caddy (:80/:443), Outline wiki (wiki.osnovasystems.com), Forgejo
  (git.osnovasystems.com, SSH :222), Postgres, Dockge, diun, Minecraft.
- **Minecraft is STOPPED AND DISABLED (2026-08-11)** to free RAM for dev work —
  `mc_fabric` + `mc_backup`, stack at `/root/minecraft-server`, idle since
  2026-05-03. World data (`mc-data`, 907M) + backups (`mc-backups`, 696M) are
  bind mounts on disk and were untouched by the teardown.
  **Restart: `sudo systemctl enable --now minecraft.service`** (drop `enable` for
  a one-off that dies at the next reboot).
  ⚠ **`docker stop` DOES NOT HOLD, and the old note here claiming
  `restart: unless-stopped` made it survive reboots was WRONG** — that policy only
  stops the *daemon* restarting it. `minecraft.service` (systemd, `WantedBy=multi-user.target`)
  ran `docker compose up -d` on every boot, and compose starts stopped containers.
  With the ~04:00 auto-reboot, every `docker stop` was undone by the next morning:
  that is why this note kept going stale. Disabling the unit is what makes it stick.
  ⚠ **Second resurrection, independent of the first:** `PAUSE_WHEN_EMPTY_SECONDS: 60`
  + `restart: unless-stopped` is a LOOP on an idle server — the server stops itself
  when empty, the container exits 0, Docker restarts it, a fresh JVM allocates 5 GB,
  and 60 s later it does it again (`RestartCount` was **43** in 3 days). If it ever
  comes back, fix that pairing or it churns RAM while nobody is playing.
  **Treat the stop as reversible** — the RAM note below flips back the moment it returns.
- Infra-as-code lives in `~/dev/osnova-infra` — read its CLAUDE.md before
  touching anything host- or stack-related. Never edit `/opt/stacks` directly:
  edit the repo, push, deploy via `./scripts/deploy.sh <service>`.

## Dev workflow

- Projects live in `~/dev/<project>`; prefer one Claude conversation per
  project (new tab: `zellij action new-tab --name <p> --cwd ~/dev/<p>`).
  Persistent session: `main`
  — attach with `zellij attach main`, never bare `zellij` (creates strays).
- sudo is passwordless. Docker available. Python via `uv`; node from apt.
- RAM is tight (8 GB shared with the stack): earlyoom kills build tools first
  under pressure. **While Minecraft is stopped (see above, 2026-07-24) there is
  ~4.8 GB available** instead of ~2.3 GB — ⚠ **measured 1.3 GB on 2026-09-02** with 4 GB in swap: `osnova-product-staging`, `dsh-play`, `pocket-id` and the livesync pair have joined since — so a single cargo build or a language
  server is comfortable — still avoid *parallel* builds. If Minecraft is
  restarted, the JVM takes ~2.4 GB resident (heap cap 5 GB, no container memory
  limit) and the old "avoid anything heavy" rule applies again. Check with
  `free -m` rather than assuming.
- The box may auto-reboot ~04:00 for security updates; the `main` session
  recreates itself and Claude resumes, but dev servers need restarting.
- SSH is Tailscale-only (public 22 closed). The Forgejo git remote uses port 222.
  ⚠ **The "break-glass = Hetzner console" line here was WRONG and was removed
  2026-08-13.** Measured: `passwd -S root` and `passwd -S dima` both return `L`
  (locked), so the Cloud Console offers a login prompt no password satisfies.
  Losing Tailscale = losing every admin path; real recovery is GRUB
  `init=/bin/bash` or the Hetzner rescue system, neither tested. Carded in the
  vault Founder queue `<#13>`; `osnova-infra/CLAUDE.md` still carries the old
  claim. Also unsettled there: its README says UFW allows 22, its CLAUDE.md says
  it does not, and nobody has read the live rules.
- **Sending images to an agent from the phone: `photo-drop`** (2026-08-13). A
  terminal session can't take an attachment, so photos go through
  http://100.93.13.127:8123 (tailnet-only, `photo-drop.service`, always up).
  One pick = one numbered batch in `~/drop/<n>/`, plus an optional note typed on
  the phone keyboard. Then "look at the newest" or "batch 7" — read `note.md`
  and the shots. Source: `~/.dotfiles/bin/photo-drop`.
- **Two GitHub accounts** (2026-08-13): `Sorbieskis` (personal) and `dsuchank`
  (`~/dev/asml`, own key + noreply email via an `includeIf`). Keep `Sorbieskis`
  the ACTIVE gh account and use `ghw <cmd>` for work — `gh auth switch` is
  global, and osnova-product's `./bin/ci` then 404s on a repo the work account
  can't see and reports "API unreachable", which looks like CI being down.

## Don'ts

- Don't reconfigure ufw, sshd, tailscale, or the zellij-main service/timer
  unless explicitly asked.
- Don't restart Docker or production containers as a debugging reflex.
- Don't put secrets in repos — SOPS for infra, `.env` (gitignored) for dev.
