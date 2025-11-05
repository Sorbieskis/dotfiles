 # Set nvim as the default editor system-wide
  set -x EDITOR nvim

# Enable vi mode in fish
fish_vi_key_bindings

  # Automatically start or attach to a Zellij session

  starship init fish | source
  mcfly init fish | source
  fzf --fish | source
  zoxide init fish | source

  # Created by `pipx` on 2025-09-01 06:32:55
  set PATH $PATH /home/sorbieskis/.local/bin

  # Claude Code Functions

  function zai
      set -lx ANTHROPIC_BASE_URL https://api.z.ai/api/anthropic
      set -lx ANTHROPIC_AUTH_TOKEN $Z_API_KEY
      set -lx ANTHROPIC_DEFAULT_OPUS_MODEL GLM-4.6
      set -lx ANTHROPIC_DEFAULT_SONNET_MODEL GLM-4.6
      set -lx ANTHROPIC_DEFAULT_HAIKU_MODEL GLM-4.6
      claude $argv
  end
