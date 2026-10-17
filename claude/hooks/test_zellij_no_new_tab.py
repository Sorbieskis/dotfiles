"""Run: python3 ~/.dotfiles/claude/hooks/test_zellij_no_new_tab.py"""
import json, subprocess, sys, os
HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "zellij-no-new-tab.py")

def denied(cmd):
    out = subprocess.run([sys.executable, HOOK], input=json.dumps({"tool_input": {"command": cmd}}),
                         capture_output=True, text=True).stdout
    return bool(out.strip())

NT = "new" + "-tab"
BLOCK = [
    f"zellij -s lab-nobody-xyz action {NT} --name orch-22 && sleep 2 && zellij -s lab-nobody-xyz action write-chars 'x'",
    f"zellij action {NT} --name p --cwd ~/dev/p",
    f"~/.local/share/mise/installs/zellij/0.45.1/zellij -s lab-nobody-xyz action {NT}",
    f"timeout 5 zellij -s lab-nobody-xyz action {NT}",
    f"cd ~/dev; env -u CLAUDE_CODE_CHILD_SESSION zellij -s lab-nobody-xyz action {NT} --layout one.kdl",
    "zellij -s lab-nobody-xyz action go-to-tab-name --create orch-23",
    "zellij -s lab-nobody-xyz --layout x.kdl",
    "zellij -s lab-nobody-xyz action write-chars 'claude'",
]
ALLOW = [
    f"zellij -s osnova action write-chars -p terminal_1 'see {NT} docs'",
    "zellij -s osnova action query-tab-names",
    "zellij -s osnova action close-tab-by-id 7",
    "zellij -s lab-nobody-xyz action write-chars -p terminal_3 'claude'",
    "zellij -s osnova run --name x -- sleep 9",
    "zellij --layout l.kdl attach -b -c orch-23",
    "zj-spawn orch-23 ~/dev/osnova-product fish ~/lab/2026-10-m128-run/launch23.fish",
    f"grep -n {NT} HANDOFF.md",
    f"cat > f.md <<'EOF'\nuse zellij action {NT} only when attached\nEOF",
    f'echo "zellij -s osnova action {NT}"',
    "zellij list-sessions -n",
    f"python3 - <<EOF\nnew=\"NEVER `zellij action {NT}`, it crashed\"\nEOF",
]
fails = [c for c in BLOCK if not denied(c)] + [c for c in ALLOW if denied(c)]
for c in fails: print("FAIL:", c)
print("ok" if not fails else f"{len(fails)} failing"); sys.exit(1 if fails else 0)
