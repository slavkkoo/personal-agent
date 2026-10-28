#!/bin/bash
# Вызывается из personal-agent-failed@<unit>.service (OnFailure= в юнитах):
# юнит упал — владельцу алерт с хвостом журнала. Без этого упавший таймер
# замечаешь, только когда брифинг не пришёл.
set -uo pipefail
source "$(dirname "$0")/lib.sh"
U="${1:?usage: notify_failure.sh <unit>}"
tail=$(journalctl -u "$U" -n 12 --no-pager -o cat 2>/dev/null | tail -c 900)
send "🛑 Упал $U ($(date '+%d.%m %H:%M')). Хвост журнала:
${tail:-(журнал недоступен — проверьте journalctl -u $U)}"
