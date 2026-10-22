#!/usr/bin/env bash
# print weekly and session utilization, e.g. "week=94 session=68"
T=$(python3 -c "import json;print(json.load(open('/home/dima/.claude/.credentials.json'))['claudeAiOauth']['accessToken'])")
curl -s -m 15 https://api.anthropic.com/api/oauth/usage -H "Authorization: Bearer $T" -H "anthropic-beta: oauth-2025-04-20" \
 | python3 -c "import json,sys; d=json.load(sys.stdin); print('week=%g session=%g' % (d['seven_day']['utilization'], d['five_hour']['utilization']))" 2>/dev/null || echo "week=? (usage API failed)"
