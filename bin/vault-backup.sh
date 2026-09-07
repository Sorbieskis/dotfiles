#!/bin/bash
# Hourly vault backup: commit whatever LiveSync/agents changed and push to GitHub.
# Git is backup/history only — sync between machines is handled by LiveSync + livesync-bridge.
set -euo pipefail
cd /home/dima/vault

git pull --rebase --autostash origin main >/dev/null 2>&1 || true

if [ -n "$(git status --porcelain)" ]; then
    git add -A
    git commit -q -m "backup: vault snapshot $(date '+%Y-%m-%d %H:%M')"
fi

git push -q origin main
