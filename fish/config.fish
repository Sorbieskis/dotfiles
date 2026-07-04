set -x EDITOR nvim

# PATH — cargo/bin MUST be before mcfly init
fish_add_path $HOME/.cargo/bin
fish_add_path $HOME/.local/bin

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

# proj            — list projects in ~/dev
# proj <name>     — open a zellij tab in ~/dev/<name>; outside zellij, cd there.
#                   Never creates anything: `mkdir ~/dev/<name>` to start a project.
function proj
    if test (count $argv) -eq 0
        ls -1 ~/dev
        return
    end
    set -l dir ~/dev/$argv[1]
    if not test -d $dir
        echo "proj: no project '$argv[1]' in ~/dev  (mkdir ~/dev/$argv[1] to start one)" >&2
        return 1
    end
    if set -q ZELLIJ
        zellij action new-tab --name $argv[1] --cwd $dir
    else
        cd $dir
    end
end
