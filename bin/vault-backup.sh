#!/bin/bash
# Hourly vault backup: commit whatever LiveSync/agents changed and push to GitHub.
# Git is backup/history only — sync between machines is handled by LiveSync + livesync-bridge.
#
# Before the push, gitleaks scans exactly what the push sends: origin/main..main (all of
# main with no upstream), whatever branch HEAD is on. FAIL CLOSED: a hit, a missing binary
# or any other gitleaks error holds the push and sends a generic ntfy (never the finding).
# Notes: gitleaks also exits 1 on a bad config, so "hit" below means "hit or config error";
# fail-closed relies on the range being a valid ref (guarded by the rev-parse checks, a bad
# range would make gitleaks error out, which is held too). The config lives OUTSIDE the
# vault (an in-tree allowlist would be scanned content, editable by any agent) and inline
# `gitleaks:allow` comments are ignored. The binary is the exact mise pin, not a glob or
# `latest`: bump it here together with ~/.dotfiles/mise/config.toml.
# Test hooks (env): VAULT_DIR, GITLEAKS_BIN, NTFY_CMD (receives the message as $1).
set -euo pipefail
VAULT_DIR=${VAULT_DIR:-/home/dima/vault}
GITLEAKS_BIN=${GITLEAKS_BIN:-/home/dima/.local/share/mise/installs/aqua-gitleaks-gitleaks/8.30.1/gitleaks}
GITLEAKS_CONFIG=/home/dima/.dotfiles/vault/gitleaks.toml
cd "$VAULT_DIR"

notify() {
    echo "$(date '+%F %T') $1"
    if [ -n "${NTFY_CMD:-}" ]; then "$NTFY_CMD" "$1" || true; return; fi
    local topic; topic=$(cat /etc/osnova/ntfy-ci-topic 2>/dev/null || true)
    [ -n "$topic" ] && curl -fsS -m 20 -H "Title: vault backup" -d "$1" "https://ntfy.sh/$topic" >/dev/null || true
}

git pull --rebase --autostash origin main >/dev/null 2>&1 || true

if [ -n "$(git status --porcelain)" ]; then
    git add -A
    git commit -q -m "backup: vault snapshot $(date '+%Y-%m-%d %H:%M')"
fi

# Scan what `git push origin main` sends; with no upstream ref that is all of main.
if ! git rev-parse -q --verify refs/heads/main >/dev/null; then
    notify "vault-backup: push held, no local main branch, check the vault-backup log"
    exit 1
fi
if git rev-parse -q --verify refs/remotes/origin/main >/dev/null; then
    range="origin/main..main"
    ahead=$(git rev-list --count "$range")
else
    range="main"; ahead=1
fi

if [ "$ahead" -gt 0 ]; then
    rc=0
    if [ ! -x "$GITLEAKS_BIN" ] || [ ! -r "$GITLEAKS_CONFIG" ]; then
        rc=127
    else
        "$GITLEAKS_BIN" git --log-opts="$range" --redact --no-banner --exit-code 1 \
            --ignore-gitleaks-allow --config "$GITLEAKS_CONFIG" . >/dev/null 2>&1 || rc=$?
    fi
    if [ "$rc" -ne 0 ]; then
        if [ "$rc" -eq 1 ]; then
            notify "vault-backup: push held, gitleaks hit or config error, run gitleaks locally"
        else
            notify "vault-backup: push held, gitleaks could not run (exit $rc), check the vault-backup log"
        fi
        exit 1
    fi
fi

git push -q origin main
