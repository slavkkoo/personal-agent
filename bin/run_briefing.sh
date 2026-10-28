#!/bin/bash
# Утренний брифинг: личка Telegram + почта + календарь + задачи → владельцу в личку.
# Запускается personal-agent-briefing.timer (время — BRIEFING_TIME в .env, по TZ).
set -uo pipefail
source "$(dirname "$0")/lib.sh"

# Ретрай: RpcCallFailError у Telegram — временный серверный сбой, не роняем брифинг.
read_ok=0
for attempt in 1 2 3; do
  if "$A/.venv/bin/python3" "$A/bin/read_personal.py" 24 40 > "$RUN/personal.txt" 2> "$RUN/read_err.log"; then
    read_ok=1; break
  fi
  echo "read_personal: попытка $attempt не удалась, жду 45с" >&2
  sleep 45
done
if [ "$read_ok" -ne 1 ]; then
  send "⚠️ ${ASSISTANT_NAME}: не смог прочитать личку для брифинга (3 попытки) — $(tail -c 300 "$RUN/read_err.log")"
  exit 1
fi

# Почта, календарь, задачи — мягко: не настроено или упало — пометка в дампе.
# Ошибка источника печатается строкой «=== … ОШИБКА …» и ниже выносится первой строкой.
python3 "$A/bin/mail_triage.py" 24 --clean >> "$RUN/personal.txt" 2>&1 || true
python3 "$A/bin/read_calendar.py" 2 >> "$RUN/personal.txt" 2>&1 || true
{ echo; echo "=== ✅ Открытые задачи ==="; "$A/bin/tasks" list; } >> "$RUN/personal.txt" 2>&1 || true

if [ ! -s "$RUN/personal.txt" ]; then
  send "☀️ Доброе утро! За сутки тихо — новых сообщений нет."
  exit 0
fi

# Полный список задач — только по понедельникам; в будни — просроченные и срочные
# (иначе одни и те же задачи каждый день растягивают брифинг на несколько экранов).
if [ "$(date +%u)" = 1 ]; then
  TASKS_MODE="понедельник: перечисли ВСЕ задачи из секции «Открытые задачи» одним списком (по строке на задачу, с её номером)."
else
  TASKS_MODE="только просроченные и со сроком сегодня/завтра (по строке, с номером); остальные — одной строкой «ещё N открытых (полный список — по понедельникам)». Нет таких — секцию не выводи."
fi
PROMPT=$(render briefing "RUN=$RUN" "DATE=$(date +%d.%m)" "TASKS_MODE=$TASKS_MODE") || {
  send "⚠️ ${ASSISTANT_NAME}: не собрал промпт брифинга — проверьте prompts/briefing.md"; exit 1; }

cd "$A"
duty_claude "$PROMPT" > "$RUN/briefing.txt" 2> "$RUN/claude_err.log"

OUT=$(cat "$RUN/briefing.txt")
if [ -z "$OUT" ]; then
  send "⚠️ ${ASSISTANT_NAME}: брифинг не собрался (пустой ответ) — $(tail -c 300 "$RUN/claude_err.log")"
  exit 1
fi
CLEAN=$(printf '%s\n' "$OUT" | awk '/^☀️/{f=1} f')
if [ -z "$CLEAN" ]; then
  # Нет строки «☀️ Брифинг…» — это не брифинг, а ошибка или рассуждение модели
  # (например, «OAuth token has been revoked»). Под видом брифинга не отправляем.
  send "⚠️ ${ASSISTANT_NAME}: брифинг не собрался — ответ без «☀️». Начало: $(printf '%s' "$OUT" | head -c 300)"
  exit 1
fi
OUT="$CLEAN"
# Сломанные источники — первой строкой. Иначе строка об ошибке тонет в дампе,
# модель её не упоминает, и источник может молча не работать неделями.
SRC_ERR=$(grep -E '^=== .*ОШИБКА' "$RUN/personal.txt" | sed -E 's/^=== //; s/ ===$//' | cut -c1-160)
if [ -n "$SRC_ERR" ]; then
  OUT="⚠️ Источники с ошибкой:
$SRC_ERR

$OUT"
fi
printf '%s\n' "$OUT" > "$A/memory/briefing-$(date +%Y-%m-%d).txt"
if ! send "$OUT"; then
  echo "briefing: Telegram не подтвердил доставку" >&2
  exit 1
fi
echo "briefing ok"
