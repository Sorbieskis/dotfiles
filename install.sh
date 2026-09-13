#!/usr/bin/env bash
# install.sh — apply the dima layer of a box: symlinks, mise tools, rustup, user units, shell, crontab.
# Idempotent and distro-agnostic (no package manager here: system packages are osnova-infra's
# bootstrap.sh). Run as dima. Root prerequisites: `loginctl enable-linger dima`, fish in /etc/shells.
#
# One way of doing everything:
#   apt    daemons, system libraries, Debian-packaged CLI tools      (osnova-infra bootstrap.sh)
#   mise   every user-level runtime and CLI tool                     (mise/config.toml, here)
#   rustup Rust only, version pinned by each repo's rust-toolchain.toml
#   uv     Python project environments (uv itself comes from mise)
set -euo pipefail
D="$HOME/.dotfiles"

echo "==> configs"
mkdir -p ~/.config/fish ~/.config/yazi ~/.config/zellij/layouts ~/.config/systemd/user ~/.config/mise ~/.local/bin ~/.claude
ln -sf  "$D/fish/config.fish"        ~/.config/fish/config.fish
ln -sfn "$D/nvim"                    ~/.config/nvim
ln -sf  "$D/yazi/yazi.toml"          ~/.config/yazi/yazi.toml
ln -sf  "$D/.gitconfig"              ~/.gitconfig
ln -sf  "$D/mise/config.toml"        ~/.config/mise/config.toml
ln -sf  "$D/zellij/layouts/main.kdl" ~/.config/zellij/layouts/main.kdl
[ -e ~/.config/zellij/config.kdl ] || cp "$D/zellij/config.kdl" ~/.config/zellij/config.kdl   # copy, not link: per-platform clipboard edits
ln -sf  "$D/claude/CLAUDE.md"        ~/.claude/CLAUDE.md
ln -sf  "$D/claude/settings.json"    ~/.claude/settings.json
ln -sfn "$D/claude/skills"           ~/.claude/skills

echo "==> scripts and user units"
for b in "$D"/bin/*; do [ -f "$b" ] || continue; chmod +x "$b"; ln -sf "$b" ~/.local/bin/"$(basename "$b")"; done
for u in "$D"/systemd/user/*; do ln -sf "$u" ~/.config/systemd/user/"$(basename "$u")"; done

echo "==> mise: runtimes and CLI tools"
command -v mise >/dev/null 2>&1 || curl -fsSL https://mise.run | sh     # lands in ~/.local/bin/mise
~/.local/bin/mise install --yes
~/.local/bin/mise reshim

echo "==> python libraries into mise's interpreter"
# osnova-product's `bin/lane login` imports PyYAML under `#!/usr/bin/env python3`, which resolves
# to mise's 3.12 here — the apt python3-yaml is installed but invisible to it. NOT declared in
# mise/config.toml: that manifest is tools and runtimes, not libraries. `mise which` because
# neither uv nor mise is on PATH in a login shell that has not activated mise (this script is
# what a from-zero box runs). Idempotent: uv audits and exits, ~0.1 s and no network, when the
# requirement is already satisfied.
"$(~/.local/bin/mise which uv)" pip install --python "$(~/.local/bin/mise which python)" pyyaml

echo "==> rustup (Rust only)"
[ -x ~/.cargo/bin/rustup ] || curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal --no-modify-path

echo "==> login shell"
fish=$(command -v fish || true)
if [ -n "$fish" ] && [ "$(getent passwd "$USER" | cut -d: -f7)" != "$fish" ]; then chsh -s "$fish"; fi

echo "==> user services (start at boot only with linger: sudo loginctl enable-linger $USER)"
if command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload
    systemctl --user enable --now photo-drop.service zellij-main.service zellij-main.timer || true
fi

echo "==> crontab: hourly vault push"
( crontab -l 2>/dev/null | grep -v 'vault-backup.sh' || true
  echo "17 * * * * $HOME/.local/bin/vault-backup.sh >> $HOME/.vault-backup.log 2>&1" ) | crontab -

command -v tldr >/dev/null 2>&1 && tldr --update >/dev/null 2>&1 || true
echo "done: mise $(~/.local/bin/mise --version 2>/dev/null) · $(fish --version 2>/dev/null || echo 'fish missing') · linger=$(loginctl show-user "$USER" -p Linger --value 2>/dev/null || echo '?')"
