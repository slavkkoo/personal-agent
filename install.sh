#!/bin/bash
# install.sh — идемпотентная установка личного ассистента (personal-agent).
#
#   ./install.sh            установить / обновить
#   ./install.sh --dry-run  только показать, что будет сделано (ничего не меняет)
#
# Запуск:
#   - от root (sudo ./install.sh) — файлы в AGENT_HOME, chown на AGENT_USER,
#     юниты сразу в /etc/systemd/system и daemon-reload (enable — вручную, см. вывод);
#   - от пользователя ассистента — файлы в AGENT_HOME, юниты рендерятся в
#     AGENT_HOME/run/systemd/, команды для их установки через sudo печатаются в конце.
#
# Переопределяемые переменные окружения:
#   AGENT_USER (assistant), USER_HOME (домашний каталог AGENT_USER),
#   AGENT_HOME ($USER_HOME/.local/share/personal-agent), SYSTEMD_DIR (/etc/systemd/system),
#   SKIP_VENV=1 — не создавать .venv с telethon.
# Значения TZ, BRIEFING_TIME, MENTOR_DAY, MENTOR_TIME, ASSISTANT_NAME, TEAM_AGENT_USER
# берутся из AGENT_HOME/.env (или .env рядом с install.sh), иначе — дефолты.
set -euo pipefail

DRY=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY=1 ;;
    -h|--help) sed -n '2,19p' "$0"; exit 0 ;;
    *) echo "неизвестный аргумент: $arg (есть только --dry-run)" >&2; exit 2 ;;
  esac
done

SRC="$(cd "$(dirname "$0")" && pwd)"
AGENT_USER="${AGENT_USER:-assistant}"
if [ -z "${USER_HOME:-}" ]; then
  if [ "$(id -un)" = "$AGENT_USER" ]; then
    USER_HOME="$HOME"
  elif command -v getent >/dev/null && getent passwd "$AGENT_USER" >/dev/null; then
    USER_HOME="$(getent passwd "$AGENT_USER" | cut -d: -f6)"
  else
    USER_HOME="/home/$AGENT_USER"
  fi
fi
AGENT_HOME="${AGENT_HOME:-$USER_HOME/.local/share/personal-agent}"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"
IS_ROOT=0; [ "$(id -u)" = 0 ] && IS_ROOT=1

say()  { printf '%s\n' "$*"; }
warn() { printf '⚠️  %s\n' "$*" >&2; }
run()  { if [ "$DRY" = 1 ]; then printf '[dry-run] %s\n' "$*"; else "$@"; fi; }

# envget KEY DEFAULT — значение из .env (без source: .env может содержать что угодно)
envget() {
  local key="$1" def="$2" f v=""
  for f in "$AGENT_HOME/.env" "$SRC/.env"; do
    if [ -f "$f" ]; then
      v="$(grep -E "^[[:space:]]*${key}=" "$f" | tail -n1 | cut -d= -f2- | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//; s/^"(.*)"$/\1/; s/^'"'"'(.*)'"'"'$/\1/')" || true
      [ -n "$v" ] && break
    fi
  done
  [ -z "$v" ] && v="${!key:-}"
  printf '%s' "${v:-$def}"
}

esc() { printf '%s' "$1" | sed -e 's/[\\|&]/\\&/g'; }

TZ_VAL="$(envget TZ UTC)"
BRIEFING_TIME="$(envget BRIEFING_TIME 08:00)"
MENTOR_DAY="$(envget MENTOR_DAY Fri)"
MENTOR_TIME="$(envget MENTOR_TIME 16:00)"
ASSISTANT_NAME="$(envget ASSISTANT_NAME Ассистент)"
TEAM_AGENT_USER="$(envget TEAM_AGENT_USER teamagent)"
PYTHON3="$(command -v python3 || echo /usr/bin/python3)"
[ "$IS_ROOT" = 1 ] && PYTHON3="/usr/bin/python3"

re_time='^([01][0-9]|2[0-3]):[0-5][0-9]$'
[[ "$BRIEFING_TIME" =~ $re_time ]] || { echo "BRIEFING_TIME должно быть HH:MM, а не «$BRIEFING_TIME»" >&2; exit 1; }
[[ "$MENTOR_TIME" =~ $re_time ]]   || { echo "MENTOR_TIME должно быть HH:MM, а не «$MENTOR_TIME»" >&2; exit 1; }
[[ "$MENTOR_DAY" =~ ^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)$ ]] || { echo "MENTOR_DAY: Mon…Sun, а не «$MENTOR_DAY»" >&2; exit 1; }
[[ "$TZ_VAL" =~ ^[A-Za-z0-9_+/-]+$ ]] || { echo "TZ выглядит странно: «$TZ_VAL» (пример: Europe/Berlin)" >&2; exit 1; }
[ "$TZ_VAL" = UTC ] && warn "TZ не задан в .env — расписания будут по UTC. Поставьте свой TZ (например, Europe/Berlin)."

say "== personal-agent: установка $([ "$DRY" = 1 ] && echo '(dry-run)')"
say "   исходники:   $SRC"
say "   AGENT_USER:  $AGENT_USER"
say "   AGENT_HOME:  $AGENT_HOME"
say "   TZ:          $TZ_VAL; брифинг $BRIEFING_TIME; ментор $MENTOR_DAY $MENTOR_TIME"

# ---- 1. предпроверки ----
pyok=$(python3 -c 'import sys; print(int(sys.version_info >= (3, 11)))' 2>/dev/null || echo 0)
[ "$pyok" = 1 ] || warn "нужен Python 3.11+ (python3 не найден или старый)"
command -v curl   >/dev/null || warn "нет curl — обёртки брифинга не смогут отправить сообщение"
command -v claude >/dev/null || [ -x "$USER_HOME/.local/bin/claude" ] || warn "claude (Claude Code CLI) не найден в PATH — см. INSTALL.md, шаг 3"

# ---- 2. каталоги ----
for d in "" bin prompts config deploy deploy/systemd memory logs run .claude-config .claude-config/skills; do
  run mkdir -p "$AGENT_HOME/$d"
done
run chmod 700 "$AGENT_HOME"

# ---- 3. код (если ставим не из клона прямо в AGENT_HOME) ----
if [ "$SRC" != "$AGENT_HOME" ]; then
  run cp -f "$SRC"/bin/* "$AGENT_HOME/bin/"
  run cp -f "$SRC/deploy/claude-config-settings.json.in" "$AGENT_HOME/deploy/"
  run cp -f "$SRC"/deploy/systemd/*.in "$AGENT_HOME/deploy/systemd/"
  run cp -f "$SRC/requirements.txt" "$SRC/.env.example" "$AGENT_HOME/"
  # коннекторы (connectors/mcp и т.п.): код — обновляем; ваш config/mcp.json живёт отдельно
  run mkdir -p "$AGENT_HOME/connectors"
  run cp -Rf "$SRC/connectors/." "$AGENT_HOME/connectors/"
  # промпты и конфиги — ваши правки не затираем
  for f in "$SRC"/prompts/*.md "$SRC"/config/*; do
    rel="${f#"$SRC"/}"
    if [ -e "$AGENT_HOME/$rel" ]; then
      cmp -s "$f" "$AGENT_HOME/$rel" || say "   $rel уже есть и отличается — не перезаписываю (сравните с $f)"
    else
      run cp "$f" "$AGENT_HOME/$rel"
    fi
  done
fi
run chmod +x "$AGENT_HOME"/bin/*.sh "$AGENT_HOME"/bin/*.py "$AGENT_HOME/bin/tasks" "$AGENT_HOME/bin/gl_task"

# ---- 4. .env и рабочие файлы ----
if [ ! -f "$AGENT_HOME/.env" ]; then
  if [ -f "$SRC/.env" ] && [ "$SRC" != "$AGENT_HOME" ]; then
    run cp "$SRC/.env" "$AGENT_HOME/.env"
  else
    run cp "$SRC/.env.example" "$AGENT_HOME/.env"
    warn "$([ "$DRY" = 1 ] && echo "будет создан" || echo "создан") $AGENT_HOME/.env из примера — заполните его (INSTALL.md, шаг 11)"
  fi
fi
run chmod 600 "$AGENT_HOME/.env"
if [ ! -f "$AGENT_HOME/memory/junk_senders.txt" ]; then
  run cp "$SRC/config/junk_senders.example.txt" "$AGENT_HOME/memory/junk_senders.txt"
fi

# ---- 5. права Claude-агента ----
render_to() {  # render_to <шаблон> <куда>
  if [ "$DRY" = 1 ]; then
    say "[dry-run] render $1 → $2"
    return
  fi
  sed -e "s|@AGENT_USER@|$(esc "$AGENT_USER")|g" \
      -e "s|@AGENT_HOME@|$(esc "$AGENT_HOME")|g" \
      -e "s|@USER_HOME@|$(esc "$USER_HOME")|g" \
      -e "s|@TZ@|$(esc "$TZ_VAL")|g" \
      -e "s|@PYTHON3@|$(esc "$PYTHON3")|g" \
      -e "s|@BRIEFING_TIME@|$(esc "$BRIEFING_TIME")|g" \
      -e "s|@MENTOR_DAY@|$(esc "$MENTOR_DAY")|g" \
      -e "s|@MENTOR_TIME@|$(esc "$MENTOR_TIME")|g" \
      -e "s|@ASSISTANT_NAME@|$(esc "$ASSISTANT_NAME")|g" \
      -e "s|@TEAM_AGENT_USER@|$(esc "$TEAM_AGENT_USER")|g" \
      "$1" > "$2.tmp"
  if grep -q '@[A-Z_0-9]*@' "$2.tmp"; then
    echo "в $2 остались незаполненные плейсхолдеры:" >&2; grep -n '@[A-Z_0-9]*@' "$2.tmp" >&2
    rm -f "$2.tmp"; exit 1
  fi
  mv "$2.tmp" "$2"
}
render_to "$SRC/deploy/claude-config-settings.json.in" "$AGENT_HOME/.claude-config/settings.json"
if [ "$DRY" = 0 ]; then
  chmod 600 "$AGENT_HOME/.claude-config/settings.json"
  python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$AGENT_HOME/.claude-config/settings.json" \
    || { echo "settings.json получился невалидным JSON" >&2; exit 1; }
fi
n_sk=$( (find "$AGENT_HOME/.claude-config/skills" -name SKILL.md 2>/dev/null || true) | wc -l | tr -d ' ')
say "   скиллов ментора установлено: ${n_sk:-0} (нет — ментор работает на общих принципах)"

# ---- 6. venv для Telethon ----
if [ ! -x "$AGENT_HOME/.venv/bin/python3" ]; then
  if [ "${SKIP_VENV:-0}" = 1 ]; then
    warn "SKIP_VENV=1 — .venv не создаю; read_personal.py без него не заработает"
  else
    run python3 -m venv "$AGENT_HOME/.venv"
    run "$AGENT_HOME/.venv/bin/pip" install -q -r "$SRC/requirements.txt"
  fi
fi

# ---- 7. systemd-юниты ----
if [ -w "$SYSTEMD_DIR" ] || { [ "$IS_ROOT" = 1 ] && [ -d "$SYSTEMD_DIR" ]; }; then
  UNIT_DIR="$SYSTEMD_DIR"; STAGED=0
else
  UNIT_DIR="$AGENT_HOME/run/systemd"; STAGED=1
  run mkdir -p "$UNIT_DIR"
fi
for t in "$SRC"/deploy/systemd/*.in; do
  name="$(basename "$t" .in)"
  render_to "$t" "$UNIT_DIR/$name"
done

if [ "$IS_ROOT" = 1 ]; then
  run chown -R "$AGENT_USER:" "$AGENT_HOME"
  if [ "$UNIT_DIR" = /etc/systemd/system ] && command -v systemctl >/dev/null; then
    run systemctl daemon-reload
  fi
fi

# ---- 8. что ещё не готово ----
say ""
say "== проверки"
[ -f "$USER_HOME/.claude-token.env" ] || warn "нет $USER_HOME/.claude-token.env (CLAUDE_CODE_OAUTH_TOKEN=…) — без него юниты не стартуют (INSTALL.md, шаг 4)"
for k in BOT_TOKEN OWNER_ID TG_API_ID TG_API_HASH; do
  [ -n "$(envget "$k" "")" ] || warn "$k не заполнен в .env"
done
if [ -n "$(envget MCP_CONFIG "")" ]; then
  if [ "$DRY" = 1 ]; then say "[dry-run] MCP: проверка python3 connectors/mcp/mcp_check.py check"
  else AGENT_HOME="$AGENT_HOME" python3 "$AGENT_HOME/connectors/mcp/mcp_check.py" check | sed 's/^/   MCP: /' || warn "MCP: конфиг или белый список с ошибками — MCP не подключится"; fi
fi
ls "$AGENT_HOME"/*.session >/dev/null 2>&1 || warn "нет Telegram-сессии — запустите bin/tg_login.py (INSTALL.md, шаг 7)"

say ""
say "== дальше"
if [ "$STAGED" = 1 ]; then
  say "1. Установите юниты (нужен sudo):"
  say "     sudo cp $UNIT_DIR/personal-agent* /etc/systemd/system/ && sudo systemctl daemon-reload"
else
  say "1. Юниты установлены в $UNIT_DIR."
fi
say "2. Включите:"
say "     sudo systemctl enable --now personal-agent.service personal-agent-briefing.timer personal-agent-mentor.timer"
say "3. Проверьте: напишите боту /start; ручной брифинг — sudo systemctl start personal-agent-briefing.service"
say "4. Логи: journalctl -u personal-agent -f; файлы ошибок — $AGENT_HOME/run/*.log"
[ "$DRY" = 1 ] && say "(dry-run: ничего не изменено)"
exit 0
