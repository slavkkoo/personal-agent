#!/bin/bash
# Еженедельная PM-менторская сессия (personal-agent-mentor.timer, по умолчанию пятница).
# Материал: брифинги недели + календарь на неделю + задачи → наблюдение, фокус, 2 вопроса.
set -uo pipefail
source "$(dirname "$0")/lib.sh"

{ echo "=== Брифинги недели ==="
  for f in $(ls -t "$A"/memory/briefing-*.txt 2>/dev/null | head -7); do
    echo "--- $(basename "$f") ---"; cat "$f"
  done
  echo; echo "=== Календарь на неделю вперёд ==="
  python3 "$A/bin/read_calendar.py" 7 2>&1
  echo; echo "=== Открытые задачи ==="
  "$A/bin/tasks" list all 2>&1
} > "$RUN/mentor_input.txt"

PROMPT=$(render mentor "RUN=$RUN") || {
  send "⚠️ ${ASSISTANT_NAME}: не собрал промпт ментора — проверьте prompts/mentor.md"; exit 1; }

cd "$A"
duty_claude "$PROMPT" > "$RUN/mentor.txt" 2> "$RUN/mentor_err.log"

OUT=$(cat "$RUN/mentor.txt")
if [ -z "$OUT" ]; then
  send "⚠️ ${ASSISTANT_NAME}: менторская сессия не собралась — $(tail -c 300 "$RUN/mentor_err.log")"
  exit 1
fi
CLEAN=$(printf '%s\n' "$OUT" | awk '/^🧭/{f=1} f')
if [ -z "$CLEAN" ]; then
  send "⚠️ ${ASSISTANT_NAME}: менторская сессия не собралась — ответ без «🧭». Начало: $(printf '%s' "$OUT" | head -c 300)"
  exit 1
fi
printf '%s\n' "$CLEAN" > "$A/memory/mentor-$(date +%Y-%m-%d).txt"
if ! send "$CLEAN"; then
  echo "mentor: Telegram не подтвердил доставку" >&2
  exit 1
fi
echo "mentor ok"
