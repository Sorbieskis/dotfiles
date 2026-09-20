set -x EDITOR nvim

# PATH — cargo/bin MUST be before mcfly init
fish_add_path $HOME/.cargo/bin
fish_add_path $HOME/.local/bin

# mise is THE manager for user-level runtimes and CLI tools (node, python, zellij, starship, …):
# ~/.config/mise/config.toml → ~/.dotfiles/mise/config.toml. Activate before starship/mcfly/zoxide init.
if type -q mise
    mise activate fish | source
end

# Podman socket — only set if podman is installed
if command -q podman
    set -gx DOCKER_HOST "unix://$XDG_RUNTIME_DIR/podman/podman.sock"
end

# Enable vi mode in fish
fish_vi_key_bindings

starship init fish | source
mcfly init fish | source
fzf --fish | source
zoxide init fish | source

# Secrets (API keys etc.) — kept in a separate untracked file
if test -f ~/.config/fish/secrets.fish
    source ~/.config/fish/secrets.fish
end

# Claude Code Functions

function claudeglm
    if not set -q ZAI_API_KEY; or test -z "$ZAI_API_KEY"
        echo "Error: ZAI_API_KEY not set. Add it to ~/.config/fish/secrets.fish"
        return 1
    end

    set -lx ANTHROPIC_API_KEY ""
    set -lx ANTHROPIC_BASE_URL "https://api.z.ai/api/anthropic"
    set -lx ANTHROPIC_AUTH_TOKEN $ZAI_API_KEY
    set -lx ANTHROPIC_DEFAULT_OPUS_MODEL "glm-4.7"
    set -lx ANTHROPIC_DEFAULT_SONNET_MODEL "glm-4.7"
    set -lx ANTHROPIC_DEFAULT_HAIKU_MODEL "glm-4.6"

    claude $argv
end

alias zai="claudeglm"

function claudekimi
    if not set -q KIMI_API_KEY; or test -z "$KIMI_API_KEY"
        echo "Error: KIMI_API_KEY not set. Add it to ~/.config/fish/secrets.fish"
        return 1
    end

    set -lx ANTHROPIC_API_KEY $KIMI_API_KEY
    set -lx ANTHROPIC_BASE_URL "https://api.kimi.com/coding/"
    set -lx ANTHROPIC_DEFAULT_OPUS_MODEL "kimi-for-coding"
    set -lx ANTHROPIC_DEFAULT_SONNET_MODEL "kimi-for-coding"
    set -lx ANTHROPIC_DEFAULT_HAIKU_MODEL "kimi-for-coding"

    claude $argv
end

alias kimi="claudekimi"

# gh as the work account (dsuchank), scoped to this one command.
# `gh auth switch` would do it globally instead — and osnova-product's ./bin/ci
# probes a repo the work account cannot see, so a left-over switch makes CI report
# "API unreachable" rather than anything true. set -lx keeps it from leaking.
function ghw
    set -l tok (gh auth token --user dsuchank 2>/dev/null)
    if test -z "$tok"
        echo "Error: no gh token for dsuchank. Run: gh auth login"
        return 1
    end

    set -lx GH_TOKEN $tok
    gh $argv
end

# ── o — the osnova-product toolbelt, typed by hand ────────────────────────────────────
# `o board next` · `o ci --check` · `o help` (the whole page) · `o help ci` (one tool's docs).
# The repo is resolved from $PWD, so inside a worktree slot (~/wt/osnova-N) `o check` checks
# THAT tree; hard-coding ~/dev/osnova-product would quietly check a different one.
#
# ⚠ The marker is `bin/board`, which every branch has — NOT `bin/help`. Keying the fallback on
# the newest tool means a slot on a branch that predates it resolves to the MAIN checkout, so
# `o check` / `o gate` would run against a tree the operator is not looking at. The one thing
# that does fall back is the help page itself: `o help` must answer everywhere.
function o --description 'osnova-product bin/ tools (o help)'
    set -l canon $HOME/dev/osnova-product
    set -l root (git rev-parse --show-toplevel 2>/dev/null)
    if test -z "$root"; or not test -x "$root/bin/board"
        set root $canon
    end
    if test (count $argv) -eq 0
        $root/bin/help 2>/dev/null; or $canon/bin/help
        return $status
    end
    set -l tool $root/bin/$argv[1]
    if not test -x $tool
        if test "$argv[1]" = help
            $canon/bin/help $argv[2..]
            return $status
        end
        echo "o: $argv[1] is not in "(string replace $HOME '~' $root)"/bin — try `o help`" >&2
        return 127
    end
    # env --chdir, not cd: these tools want the repo root as cwd (cargo walks up from it), and
    # a ctrl-C must not leave the interactive shell parked in another directory.
    env --chdir=$root $tool $argv[2..]
end

# Tool names + blurbs come from bin/help itself, so the completion cannot drift from the page.
# The canonical checkout is fine here even inside a slot: the names are the same in every clone.
complete -c o -f -n __fish_is_first_arg -a '($HOME/dev/osnova-product/bin/help --complete)'
complete -c o -f -n '__fish_seen_subcommand_from board' -a 'next prod loop product deps'
complete -c o -f -n '__fish_seen_subcommand_from lane' -a 'status score prep dispatch land exec clean install selftest'
complete -c o -f -n '__fish_seen_subcommand_from wt' -a 'ls holders claim release gc new rm'
complete -c o -f -n '__fish_seen_subcommand_from mq' -a 'status land'
complete -c o -f -n '__fish_seen_subcommand_from seat' -a 'routes build chores round evaluate shadow'
complete -c o -f -n '__fish_seen_subcommand_from psi-watch' -a 'report sample watch'
