#!/bin/bash
# Hourly vault backup: commit whatever LiveSync/agents changed and push to GitHub.
# Git is backup/history only — sync between machines is handled by LiveSync + livesync-bridge.
#
# Before the push, gitleaks scans the unpushed range. FAIL CLOSED: a hit, a missing
# binary or any other gitleaks error holds the push and sends a generic ntfy (never the
# finding). Cron's PATH is minimal, so the mise-installed binary is called by full path.
# Test hooks (env): VAULT_DIR, GITLEAKS_BIN, NTFY_CMD (receives the message as $1).
set -euo pipefail
VAULT_DIR=${VAULT_DIR:-/home/dima/vault}
GITLEAKS_BIN=${GITLEAKS_BIN:-$(ls -d /home/dima/.local/share/mise/installs/aqua-gitleaks-gitleaks/*/gitleaks 2>/dev/null | sort -V | tail -1)}
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

# Scan only what is about to leave the box; with no upstream ref, scan everything.
if git rev-parse -q --verify refs/remotes/origin/main >/dev/null; then
    range="origin/main..HEAD"
    ahead=$(git rev-list --count "$range")
else
    range="HEAD"; ahead=1
fi

if [ "$ahead" -gt 0 ]; then
    rc=0
    if [ -z "$GITLEAKS_BIN" ] || [ ! -x "$GITLEAKS_BIN" ]; then
        rc=127
    else
        "$GITLEAKS_BIN" git --log-opts="$range" --redact --no-banner --exit-code 1 \
            --config "$VAULT_DIR/.gitleaks.toml" . >/dev/null 2>&1 || rc=$?
    fi
    if [ "$rc" -ne 0 ]; then
        if [ "$rc" -eq 1 ]; then
            notify "vault-backup: push held, gitleaks hit, run gitleaks locally"
        else
            notify "vault-backup: push held, gitleaks could not run (exit $rc), check the vault-backup log"
        fi
        exit 1
    fi
fi

git push -q origin main
