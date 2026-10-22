#!/usr/bin/env bash
# Run one headless gpt-6.1-sol task and stop it once it has written its answer file.
# dsh's headless profile prints its answer but never exits, so we watch for DONE_FILE.
#   sol61-run.sh <prompt-file> <done-file> [max-seconds=2400]
# Runs in the current directory (the model's workspace). Log goes to <done-file>.log.
set -u
PROMPT_FILE=$1; DONE=$2; MAX=${3:-2400}
HERE=/home/dima/.dotfiles/lanes
LANE=~/dsh-play/lane
rm -f "$DONE"
env DSH_HOME=$LANE/dsh-home PATH=$LANE/node/bin:$PATH \
  $LANE/dsh/node_modules/.bin/dsh --profile headless --patch "$HERE/sol61.patch.yml" \
  "$(cat "$PROMPT_FILE")" </dev/null >"$DONE.log" 2>&1 &
PID=$!
t=0
while kill -0 $PID 2>/dev/null && [ ! -s "$DONE" ] && [ $t -lt "$MAX" ]; do
  sleep 10; t=$((t+10))
done
sleep 5   # let the final write flush
kill $PID 2>/dev/null; wait $PID 2>/dev/null
if [ -s "$DONE" ]; then echo "sol61: done in ${t}s -> $DONE"; exit 0; fi
echo "sol61: NO answer file after ${t}s (log: $DONE.log)"; exit 1
