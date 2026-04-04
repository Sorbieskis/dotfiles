#!/bin/sh
# Bootstrap script for Void Linux
# Works on OrbStack VM and Hetzner VPS
# Usage: bash <(curl -s https://raw.githubusercontent.com/Sorbieskis/dotfiles/main/bootstrap.sh)

set -e

DOTFILES_REPO="https://github.com/Sorbieskis/dotfiles.git"
DOTFILES_DIR="$HOME/.dotfiles"

# Detect environment
is_vps() {
    [ -z "$DISPLAY" ] && [ -z "$WAYLAND_DISPLAY" ] && ! pgrep -x "orbstack" > /dev/null 2>&1
}

echo "==> Updating xbps..."
sudo xbps-install -Syu xbps
sudo xbps-install -Su

echo "==> Installing packages..."
sudo xbps-install -Sy \
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
    btop \
    nodejs uv \
    tealdeer wget curl openssh \
    gcc make

# mcfly not in Void repos — install via cargo
if ! command -v cargo > /dev/null 2>&1; then
    echo "==> Installing Rust (needed for mcfly)..."
    sudo xbps-install -Sy rust cargo
fi

if ! command -v mcfly > /dev/null 2>&1; then
    echo "==> Installing mcfly via cargo..."
    cargo install mcfly
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

ln -sf "$DOTFILES_DIR/fish/config.fish"   "$HOME/.config/fish/config.fish"
ln -sf "$DOTFILES_DIR/nvim"               "$HOME/.config/nvim"
ln -sf "$DOTFILES_DIR/zellij/config.kdl"  "$HOME/.config/zellij/config.kdl"
ln -sf "$DOTFILES_DIR/yazi/yazi.toml"     "$HOME/.config/yazi/yazi.toml"

# Fix zellij copy command for platform
if is_vps; then
    echo "==> VPS detected — skipping clipboard config"
else
    # Mac via OrbStack: uncomment pbcopy in zellij config
    sed -i 's|// copy_command "pbcopy".*|copy_command "pbcopy"|' "$HOME/.config/zellij/config.kdl"
fi

# Set fish as default shell
if ! grep -q "$(which fish)" /etc/shells 2>/dev/null; then
    echo "==> Adding fish to /etc/shells..."
    which fish | sudo tee -a /etc/shells
fi
echo "==> Setting fish as default shell..."
chsh -s "$(which fish)"

# Update tldr cache
tealdeer --update

echo ""
echo "Done! A few manual steps remaining:"
echo "  1. Create ~/.config/fish/secrets.fish with your API keys"
echo "  2. Log out and back in for fish shell to take effect"
echo "  3. Open nvim and run :Lazy sync"
if is_vps; then
    echo "  4. Set up SSH keys: ssh-keygen -t ed25519"
fi
