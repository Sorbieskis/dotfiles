#!/usr/bin/env bash
# Bring up the persistent "main" zellij session (with Claude Code) at boot.
#
# Why this exists: the VPS reboots periodically (unattended-upgrades reboots at
# 04:00, provider kernel maintenance), which kills every process including
# zellij + Claude Code. This script, driven by zellij-main.service, recreates
# the session FROM THE LAYOUT right after boot (detached, no client attached)
# so Claude Code is waiting when you SSH in.
#
# Installed to ~/.local/bin/zellij-main-boot.sh by bootstrap.sh.
set -u

# Run from $HOME: the zellij server daemonizes with a chdir, which panics
# (EACCES) when launched from a directory the user can't access (e.g. via
# sudo from /root).
cd "$HOME" || exit 1

# Single instance: the service and the timer can fire in the same second
# (bootstrap enables both with --now); two concurrent runs both pass the
# liveness check, then their delete/create calls collide and the session
# ends up dead. Second comer exits quietly.
mkdir -p "$HOME/.cache"
exec 9>"$HOME/.cache/zellij-main-boot.lock"
flock -n 9 || exit 0

export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
SESSION=main

# If a *live* (non-exited) session already exists, do nothing.
if zellij list-sessions -n 2>/dev/null | grep -E "^${SESSION}\b" | grep -qv "EXITED"; then
    echo "session '$SESSION' already running; nothing to do"
    exit 0
fi

# Clear any stale EXITED/resurrectable session of the same name, otherwise
# --create-background would resurrect the OLD session instead of applying the
# layout (so Claude Code's `--continue` pane wouldn't be set up).
zellij delete-session "$SESSION" --force >/dev/null 2>&1 || true

# Create the session detached, in the background, from the `main` layout.
# No pseudo-terminal/client needed -- the server holds the panes (incl. Claude
# Code) with zero clients attached, so attaching later uses your full terminal.
zellij --layout "$SESSION" attach --create-background "$SESSION"
echo "session '$SESSION' created from layout"
