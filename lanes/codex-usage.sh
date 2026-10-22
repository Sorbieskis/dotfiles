#!/usr/bin/env bash
# Codex (Sol/luna6) quota from the ChatGPT usage endpoint, using dsh's OAuth grant. Never prints the token.
python3 -I - ~/dsh-play/lane/dsh-home/.credentials.yaml <<'PY'
import sys,re,json,urllib.request,time
t=open(sys.argv[1]).read(); g=lambda k: re.search(r'^\s*'+k+r':\s*(\S+)',t,re.M).group(1).strip('"\'')
r=urllib.request.Request("https://chatgpt.com/backend-api/wham/usage",headers={"Authorization":"Bearer "+g('access'),"ChatGPT-Account-Id":g('accountId'),"User-Agent":"codex_cli_rs/0.50.0","originator":"codex_cli_rs"})
d=json.load(urllib.request.urlopen(r,timeout=20))["rate_limit"]
for n,k in (("5h","primary_window"),("week","secondary_window")):
  w=d[k]; print(f"{n}={w['used_percent']}% resets {time.strftime('%a %H:%M',time.localtime(w['reset_at']))}")
print("limit_reached=",d["limit_reached"])
PY
