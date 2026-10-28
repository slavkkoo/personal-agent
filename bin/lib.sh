#!/bin/bash
# Общее для bash-обёрток: пути, .env, отправка владельцу с проверкой доставки.
# Подключается через `source "$(dirname "$0")/lib.sh"`.

A="${AGENT_HOME:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
RUN="$A/run"
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
export CLAUDE_CONFIG_DIR="$A/.claude-config"
mkdir -p "$RUN" "$A/memory"

if [ ! -f "$A/.env" ]; then
  echo "нет $A/.env — скопируйте .env.example и заполните" >&2
  exit 1
fi
set -a; source "$A/.env"; set +a
: "${BOT_TOKEN:?нет BOT_TOKEN в .env}"
: "${OWNER_ID:?нет OWNER_ID в .env}"
ASSISTANT_NAME="${ASSISTANT_NAME:-Ассистент}"
MODEL_DUTY="${MODEL_DUTY:-claude-sonnet-5-5}"

# send: код 0 — только если Telegram подтвердил КАЖДЫЙ кусок (ok:true).
# Без этой проверки в лог писалось «ok», даже когда сообщение не дошло.
send() {
  local text="$1" resp rc=0 chunk
  while [ -n "$text" ]; do
    chunk="${text:0:3900}"; text="${text:3900}"
    resp=$(curl -s -m 30 -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
      --data-urlencode "chat_id=${OWNER_ID}" --data-urlencode "text=${chunk}")
    printf '%s' "$resp" | grep -q '"ok":true' || { echo "telegram: $resp" >&2; rc=1; }
  done
  return $rc
}

# render <промпт> [KEY=VALUE ...] — промпт из prompts/*.md. Не heredoc без кавычек:
# там bash подставил бы `бэктики` и $переменные из текста промпта.
render() {
  python3 "$A/bin/pa_common.py" render "$@"
}

# Агент дежурных задач: только Read подготовленного файла. Bash/запись/веб запрещены,
# чтобы текст из чужого письма или сообщения не мог ничего сделать от имени владельца.
duty_claude() {
  claude --model "$MODEL_DUTY" --allowedTools "Read" \
    --disallowedTools "Bash,Edit,Write,NotebookEdit,WebFetch,WebSearch,Agent,Task" -p "$1"
}
