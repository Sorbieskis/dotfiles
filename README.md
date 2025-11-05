# Dotfiles

Personal configuration files for my development environment.

## What's Inside

- **nvim/** - Neovim configuration (based on kickstart.nvim)
- **.gitconfig** - Git identity and settings
- **.wezterm.lua** - WezTerm terminal keybindings
- **fish/** - Fish shell configuration with vi mode, starship, mcfly, fzf, zoxide

## How It Works (Symlinks)

This repo uses **symlinks** (symbolic links) - think of them as "shortcuts" or "portals" to files.

```
~/.config/nvim/  →  ~/dotfiles/nvim/     (symlink → actual files)
~/.gitconfig     →  ~/dotfiles/.gitconfig
~/.wezterm.lua   →  ~/dotfiles/.wezterm.lua
~/.config/fish/  →  ~/dotfiles/fish/
```

When a program reads `~/.gitconfig`, it's automatically redirected to `~/dotfiles/.gitconfig`. Programs don't know they're using symlinks - it's transparent!

**Benefits:**
- Programs read from standard locations (`~/.config/`)
- Git tracks from one central location (`~/dotfiles/`)
- Edit once, changes appear everywhere
- Easy to set up on new machines

## Daily Workflow

### Editing Your Configs

Edit from **anywhere** - they all point to the same files:

```bash
# All of these edit the SAME file:
nvim ~/.gitconfig
nvim ~/dotfiles/.gitconfig

# Same with fish:
nvim ~/.config/fish/config.fish
nvim ~/dotfiles/fish/config.fish
```

### Committing Changes

**Always commit from `~/dotfiles/`** (where the git repo lives):

```bash
cd ~/dotfiles
git status              # See what changed
git add .               # Stage all changes
git commit -m "Update fish config"
git push
```

### Testing Symlinks

To verify your symlinks are working:

```bash
ls -la ~/.gitconfig
# Should show: .gitconfig -> /home/username/dotfiles/.gitconfig

readlink ~/.gitconfig
# Should show: /home/username/dotfiles/.gitconfig
```

## Setting Up on a New Machine

If you get a new computer or want to use these configs elsewhere:

### 1. Clone this repo

```bash
cd ~
git clone https://github.com/Sorbieskis/dotfiles.git
```

### 2. Backup existing configs (if any)

```bash
mv ~/.gitconfig ~/.gitconfig.backup
mv ~/.wezterm.lua ~/.wezterm.lua.backup
mv ~/.config/nvim ~/.config/nvim.backup
mv ~/.config/fish ~/.config/fish.backup
```

### 3. Create symlinks

```bash
ln -s ~/dotfiles/.gitconfig ~/.gitconfig
ln -s ~/dotfiles/.wezterm.lua ~/.wezterm.lua
ln -s ~/dotfiles/nvim ~/.config/nvim
ln -s ~/dotfiles/fish ~/.config/fish
```

### 4. Install dependencies

For the configs to work fully, you'll need:

- **Neovim** - Text editor
- **WezTerm** - Terminal emulator (optional)
- **Fish shell** - Modern shell
- **Starship** - Cross-shell prompt
- **fzf** - Fuzzy finder
- **zoxide** - Smarter cd command
- **mcfly** - Better shell history

## Understanding Symlinks

### Creating a symlink:

```bash
ln -s <source> <destination>
      ↑         ↑
   actual     shortcut
   file       location
```

**Example:**
```bash
ln -s ~/dotfiles/.gitconfig ~/.gitconfig
```
This creates a shortcut at `~/.gitconfig` that points to `~/dotfiles/.gitconfig`.

### Removing a symlink:

```bash
rm ~/.gitconfig  # Removes the symlink, NOT the actual file
```

The actual file in `~/dotfiles/.gitconfig` remains safe!

### Checking where a symlink points:

```bash
readlink ~/.gitconfig
# Output: /home/username/dotfiles/.gitconfig
```

## File Structure

```
~/dotfiles/
├── README.md              # This file
├── .gitconfig             # Git user settings
├── .wezterm.lua          # Terminal keybindings
├── fish/                  # Fish shell config
│   ├── .gitignore        # Ignore fish_variables
│   ├── config.fish       # Main config
│   ├── completions/      # Custom completions
│   ├── conf.d/           # Additional configs
│   └── functions/        # Custom functions
└── nvim/                  # Neovim config
    ├── .gitignore
    ├── init.lua          # Main config (44KB of customizations)
    ├── lazy-lock.json    # Plugin version locks
    └── lua/
        ├── custom/       # Your own plugins
        └── kickstart/    # Optional kickstart plugins
```

## Common Tasks

### Add a new dotfile

```bash
# 1. Copy to dotfiles repo
cp ~/.bashrc ~/dotfiles/.bashrc

# 2. Remove original
rm ~/.bashrc

# 3. Create symlink
ln -s ~/dotfiles/.bashrc ~/.bashrc

# 4. Commit to git
cd ~/dotfiles
git add .bashrc
git commit -m "Add bashrc"
git push
```

### Update a config

```bash
# 1. Edit the file (from anywhere)
nvim ~/.config/fish/config.fish

# 2. Commit from dotfiles
cd ~/dotfiles
git add .
git commit -m "Update fish config"
git push
```

### Restore a config from backup

```bash
cd ~/dotfiles
git log                    # Find the commit you want
git checkout <commit-hash> -- fish/config.fish
git commit -m "Restore fish config"
git push
```

## Notes

- **Never commit secrets!** - Don't add `.env` files, API keys, or credentials
- **Machine-specific files** - Some files (like `fish_variables`) are auto-generated and shouldn't be tracked
- **Git repo location** - The `.git/` directory is in `~/dotfiles/`, not in `~/.config/nvim/` or other locations

## Troubleshooting

### Symlink broken?

```bash
# Check if it exists
ls -la ~/.gitconfig

# If broken, recreate it
rm ~/.gitconfig
ln -s ~/dotfiles/.gitconfig ~/.gitconfig
```

### Changes not showing in git?

Make sure you're in the right directory:

```bash
cd ~/dotfiles  # Always commit from here!
git status
```

### Config not loading?

Verify the symlink points to the right place:

```bash
readlink -f ~/.config/nvim
# Should output: /home/username/dotfiles/nvim
```

---

**Repository:** [github.com/Sorbieskis/dotfiles](https://github.com/Sorbieskis/dotfiles)
