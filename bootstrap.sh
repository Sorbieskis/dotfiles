#!/bin/sh
# Bootstrap script for Void Linux
# Works on OrbStack VM and Hetzner VPS
#
# Usage:
#   VPS:      bash <(curl -s https://raw.githubusercontent.com/Sorbieskis/dotfiles/main/bootstrap.sh)
#   OrbStack: bash <(curl -s https://raw.githubusercontent.com/Sorbieskis/dotfiles/main/bootstrap.sh) --orbstack

set -e

DOTFILES_REPO="https://github.com/Sorbieskis/dotfiles.git"
DOTFILES_DIR="$HOME/.dotfiles"
ORBSTACK=0

for arg in "$@"; do
    case "$arg" in
        --orbstack) ORBSTACK=1 ;;
    esac
done

# Handle root vs regular user
if [ "$(id -u)" = "0" ]; then
    SUDO=""
else
    SUDO="sudo"
fi

echo "==> Updating xbps..."
$SUDO xbps-install -Syu xbps
$SUDO xbps-install -Su

echo "==> Installing packages..."
$SUDO xbps-install -Sy \
    fish-shell \
    starship \
    fzf \
    zoxide \
    zellij \
    neovim \
    yazi \
    ffmpegthumbnailer poppler imagemagick \
    eza fd bat \
    ripgrep jq tokei \
    git lazygit \
    btop fastfetch \
    nodejs uv \
    tealdeer wget curl openssh \
    shadow \
    gcc make

# mcfly not in Void repos — install via cargo
if ! command -v cargo > /dev/null 2>&1; then
    echo "==> Installing Rust (needed for mcfly)..."
    $SUDO xbps-install -Sy rust cargo
fi

if ! command -v mcfly > /dev/null 2>&1; then
    echo "==> Installing mcfly via cargo..."
    export PATH="$HOME/.cargo/bin:$PATH"
    cargo install mcfly
fi

# Claude Code
if ! command -v claude > /dev/null 2>&1; then
    echo "==> Installing Claude Code..."
    npm install -g @anthropic-ai/claude-code
fi

# Clone dotfiles
if [ ! -d "$DOTFILES_DIR" ]; then
    echo "==> Cloning dotfiles..."
    git clone "$DOTFILES_REPO" "$DOTFILES_DIR"
else
    echo "==> Dotfiles already cloned, pulling latest..."
    git -C "$DOTFILES_DIR" pull
fi

# Symlink configs
echo "==> Linking configs..."
mkdir -p "$HOME/.config/fish"
mkdir -p "$HOME/.config/zellij"
mkdir -p "$HOME/.config/yazi"

ln -sf  "$DOTFILES_DIR/fish/config.fish"  "$HOME/.config/fish/config.fish"
ln -sfn "$DOTFILES_DIR/nvim"              "$HOME/.config/nvim"
ln -sf  "$DOTFILES_DIR/yazi/yazi.toml"   "$HOME/.config/yazi/yazi.toml"
ln -sf  "$DOTFILES_DIR/.gitconfig"        "$HOME/.gitconfig"

# Zellij: copy (not symlink) so we can set the platform clipboard without
# dirtying the dotfiles repo
cp "$DOTFILES_DIR/zellij/config.kdl" "$HOME/.config/zellij/config.kdl"

if [ "$ORBSTACK" = "1" ]; then
    echo "==> OrbStack detected — setting pbcopy as clipboard command..."
    sed -i 's|// copy_command "pbcopy".*|copy_command "pbcopy"              // osx|' \
        "$HOME/.config/zellij/config.kdl"
fi

# Set fish as default shell
FISH_PATH="$(command -v fish)"
if ! grep -qF "$FISH_PATH" /etc/shells 2>/dev/null; then
    echo "==> Adding fish to /etc/shells..."
    echo "$FISH_PATH" | $SUDO tee -a /etc/shells
fi
echo "==> Setting fish as default shell..."
chsh -s "$FISH_PATH"

# Cargo bin in PATH permanently — add to fish config if not already there
if ! grep -q "cargo/bin" "$HOME/.config/fish/config.fish" 2>/dev/null; then
    echo 'set PATH $PATH $HOME/.cargo/bin' >> "$HOME/.config/fish/config.fish"
fi

# Update tldr cache
tldr --update || true

echo ""
echo "Done! A few manual steps remaining:"
echo "  1. Create ~/.config/fish/secrets.fish with your API keys"
echo "  2. Log out and back in (or 'exec fish') for fish shell to take effect"
echo "  3. Open nvim and run :Lazy sync"
if [ "$ORBSTACK" != "1" ]; then
    echo "  4. Set up SSH keys: ssh-keygen -t ed25519"
fi
