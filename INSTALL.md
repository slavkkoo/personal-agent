# Установка с нуля

Путь от пустого сервера до первого брифинга. На всё уходит около часа, больше всего
времени занимают шаги 7–9: вход в Telegram, app-пароли и календарь.

Обозначения: `$` — команда под вашим админ-пользователем (с sudo), `assistant$` —
под пользователем ассистента. `AGENT_HOME` = `/home/assistant/.local/share/personal-agent`.

Что понадобится:
- сервер с Linux и systemd, который работает круглосуточно;
- подписка Claude (Pro или Max) для `claude setup-token`;
- Telegram-аккаунт, Gmail или Google Workspace (почта и календарь опциональны);
- GitLab — по желанию.

---

## 1. Сервер: VPS или домашний Linux

Подойдёт любой Debian 12+ или Ubuntu 22.04+ с systemd. Ресурсов нужно немного:
1 vCPU, 1–2 ГБ RAM, 10 ГБ диска. Основная работа (модель) идёт в облаке Anthropic.

- **VPS** — самый простой вариант: всегда онлайн, белый IP не нужен (бот работает через
  long-poll, входящих портов нет). Закройте SSH по паролю, оставьте вход по ключу.
- **Домашний Linux** (мини-ПК, Raspberry Pi 4/5 с 64-битной ОС, старый ноутбук) тоже
  подойдёт, если он не засыпает. Отключите сон и проверьте, что после перезагрузки
  поднимается сеть. Таймеры с `Persistent=true` догонят пропущенный запуск, когда
  машина проснётся.

Поставьте часовой пояс сервера (не обязательно: таймеры всё равно берут `TZ` из `.env`,
но так удобнее читать журналы):

```bash
$ sudo timedatectl set-timezone <Ваш/Пояс>     # например Europe/Berlin
```

## 2. Пользователь `assistant` и пакеты

Ассистент работает под отдельным системным пользователем. Если на сервере уже
живёт командный агент ([team-os-agent](https://github.com/slavkkoo/team-os-agent)), он
работает под своим пользователем `teamagent`. Пользователи, токены и сессии у них не
пересекаются.

```bash
$ sudo apt update && sudo apt install -y git curl python3 python3-venv
$ python3 --version                      # нужен 3.11+
$ sudo adduser --disabled-password --gecos "" assistant
$ sudo chmod 700 /home/assistant
```

Дальше почти всё делается под этим пользователем:

```bash
$ sudo -iu assistant
```

## 3. Node.js и Claude Code

Claude Code ставится в домашний каталог пользователя, sudo для этого не нужен.

**Вариант А — через npm (нужен Node.js 18+, лучше 20+):**

```bash
$ sudo apt install -y nodejs npm         # или Node 20 из NodeSource / nvm
assistant$ npm config set prefix ~/.local
assistant$ npm install -g @anthropic-ai/claude-code
```

**Вариант Б — нативный установщик (Node не нужен):**

```bash
assistant$ curl -fsSL https://claude.ai/install.sh | bash
```

Проверка:

```bash
assistant$ export PATH="$HOME/.local/bin:$PATH"
assistant$ claude --version
```

Обёртки и юниты сами добавляют `~/.local/bin` в `PATH`.

## 4. `claude setup-token`

```bash
assistant$ claude setup-token
```

Откройте ссылку, войдите в свой аккаунт Claude и скопируйте выданный токен в файл
вне репозитория:

```bash
assistant$ umask 077
assistant$ printf 'CLAUDE_CODE_OAUTH_TOKEN=%s\n' '<токен>' > ~/.claude-token.env
assistant$ chmod 600 ~/.claude-token.env
```

systemd подключает этот файл как `EnvironmentFile=`. Агент не может его прочитать:
на него стоит deny в `settings.json`. Если токен отозван или истёк, повторите шаг.

## 5. Код и `.env`

Склонируйте репозиторий прямо в `AGENT_HOME` и заведите `.env`:

```bash
assistant$ git clone https://github.com/slavkkoo/personal-agent ~/.local/share/personal-agent
assistant$ cd ~/.local/share/personal-agent
assistant$ cp .env.example .env && chmod 600 .env
```

Дальше на каждом шаге вписывайте значения в `.env` (`nano .env`). Все переменные
описаны в `.env.example`. Значения с пробелами берите в двойные кавычки.

## 6. Бот у @BotFather и ваш Telegram ID

1. В Telegram откройте [@BotFather](https://t.me/BotFather) → `/newbot` → имя и username
   (должен заканчиваться на `bot`).
2. Скопируйте токен в `.env`: `BOT_TOKEN=<токен>`.
3. Желательно: `/setjoingroups` → Disable (бот не нужен в группах), `/setprivacy` → Enable.
4. Узнайте свой числовой ID. Оставьте `OWNER_ID` пустым и запустите бота вручную:

   ```bash
   assistant$ python3 bin/assistant_bot.py
   ```

   Напишите боту что угодно. Пока `OWNER_ID` пуст, бот работает в режиме настройки:
   он отвечает «Ваш Telegram ID: …» и больше ничего не делает. Остановите его
   (`Ctrl+C`) и впишите `OWNER_ID=<ваш_id>`.

   Можно узнать ID и без этого, например у [@userinfobot](https://t.me/userinfobot).

После этого бот отвечает только вам, и только в личном чате.

## 7. api_id / api_hash и вход в Telegram

Это нужно, чтобы ассистент читал **вашу** личку. Бот её не видит, поэтому читается
аккаунт через Telethon.

1. Откройте <https://my.telegram.org> → войдите по номеру → **API development tools**.
2. Создайте приложение (название и short name — любые, платформа — Other).
3. Впишите в `.env` `TG_API_ID=<api_id>` и `TG_API_HASH=<api_hash>`. Можно также
   добавить `TG_PHONE=+<номер>`.

   ⚠️ api_hash вместе с сессией даёт полный доступ к аккаунту. Ограничение «только
   чтение» обеспечивает код (`read_personal.py`), а не Telegram. Не публикуйте их.

4. Поставьте Telethon в venv и войдите **интерактивно** (нужен настоящий терминал):

   ```bash
   assistant$ python3 -m venv .venv
   assistant$ .venv/bin/pip install -r requirements.txt
   assistant$ .venv/bin/python3 bin/tg_login.py
   ```

   Скрипт покажет, куда Telegram отправил код: в приложение (чат «Telegram»), на почту
   или по SMS. Если код не пришёл, введите `r`, чтобы запросить его другим способом.
   Если включён облачный пароль, скрипт его спросит. Код и пароль никуда не
   пересылаются. Сессия сохранится в `AGENT_HOME/<TG_SESSION>.session` (chmod 600).

   Если подключаетесь по SSH одной командой, нужен `-t`:
   `ssh -t <admin>@<server> 'sudo -iu assistant ~/.local/share/personal-agent/.venv/bin/python3 ~/.local/share/personal-agent/bin/tg_login.py'`

5. Проверка:

   ```bash
   assistant$ .venv/bin/python3 bin/read_personal.py 24 5
   ```

Не копируйте сессию другого клиента (например, командного агента). Одна сессия
на двух клиентах конфликтует, поэтому у каждого должен быть свой вход.

## 8. App-пароли Gmail (нужна двухэтапная аутентификация)

Для каждого ящика (до пяти: `MAIL1_*` … `MAIL5_*`):

1. Включите двухэтапную аутентификацию: <https://myaccount.google.com/security> →
   «Двухэтапная аутентификация». Без неё пункта app-паролей нет.
2. Создайте пароль приложения: <https://myaccount.google.com/apppasswords> → имя,
   например «personal-agent». Google покажет 16 букв.
3. Проверьте, что IMAP доступен (в Gmail: Настройки → «Пересылка и POP/IMAP», если такой
   пункт есть). В Google Workspace app-пароли и IMAP может запретить администратор.
4. Впишите в `.env`:

   ```
   MAIL1_USER=<адрес>
   MAIL1_PASS="<16 букв, можно с пробелами>"
   MAIL1_LABEL=рабочий
   ```

   Не Gmail? Укажите `MAIL1_HOST=<imap-хост>`. Нужен IMAP по SSL на порту 993.

5. Корзина. Обычно она находится сама по IMAP-флагу `\Trash`. Если нет, укажите
   её имя в `MAIL_TRASH` (или `MAILn_TRASH` для отдельного ящика). По умолчанию
   используется `[Gmail]/Trash`. В локализованном Gmail имя другое и записано в
   modified UTF-7. Посмотреть точное имя:

   ```bash
   assistant$ python3 bin/mail_triage.py list-folders
   ```

6. Проверка (только чтение, без `--clean` ничего не переносится):

   ```bash
   assistant$ python3 bin/mail_triage.py 24
   ```

Список мусорных отправителей начинается пустым (`memory/junk_senders.txt` создаст
`install.sh`). Пополняйте его фразой «это тоже мусор» в чате с ботом.

## 9. Секретный ICS-адрес Google Calendar

Для каждого календаря (до пяти: `CAL1_*` … `CAL5_*`):

1. Откройте <https://calendar.google.com> **в браузере на компьютере** (в мобильном
   приложении этого пункта нет).
2. ⚙️ → «Настройки» → слева в «Настройках моих календарей» выберите нужный календарь.
3. Пролистайте до блока «Интеграция календаря» → **«Секретный адрес в формате iCal»** →
   скопируйте (ссылка заканчивается на `/basic.ics`).
4. Впишите в `.env`: `CAL1_ICS=<адрес>`, `CAL1_LABEL=личный`.

⚠️ Любой, у кого есть эта ссылка, видит календарь. При утечке нажмите там же
«Сбросить». В Google Workspace этот пункт может быть отключён администратором.

Проверка:

```bash
assistant$ python3 bin/read_calendar.py 7
```

Ограничения простого парсера: повторяющиеся события показываются только в дату
первого вхождения. Время с `TZID` трактуется как время сервера, поэтому в `.env`
должен стоять тот же `TZ`, что у календаря.

## 10. GitLab-токен (опционально)

Если GitLab не нужен, оставьте `GITLAB_*` пустыми: инструмент выключится и пропадёт из промпта.

1. GitLab → аватар → **Edit profile → Access tokens** → Add new token. Scope — **`api`**
   (нужен для создания задач и лейблов). Поставьте срок действия.
   Ещё лучше — project access token только на нужный проект.
2. ID проекта показан на главной странице проекта (Project ID). Вместо него можно
   указать путь `group/project`.
3. В `.env`:

   ```
   GITLAB_URL=https://gitlab.example.com
   GITLAB_TOKEN=<токен>
   GITLAB_PROJECT=<id или group/project>
   GITLAB_LABELS="bug,feature,support,doc"
   ```

   `GITLAB_MARKER` можно не задавать, по умолчанию это «Создано через ассистента
   <ASSISTANT_NAME>». Не меняйте его после запуска: `edit` правит только задачи с этой
   пометкой.

4. Проверка: только чтение и dry-run. **Не тестируйте пишущие команды на настоящих
   задачах.**

   ```bash
   assistant$ bin/gl_task search "onboarding"
   assistant$ bin/gl_task create --title "Тест шаблона ассистента" --labels bug --dry-run
   ```

   Настоящий `create`/`label`/`edit` проверяйте на тестовой задаче или в тестовом проекте.

## 11. Заполните `.env` до конца

Проверьте блоки «Кто есть кто» и «Модели и расписание»:

```
ASSISTANT_NAME=<имя ассистента>
OWNER_NAME=<как вас называть>
OWNER_ROLE="<одна строка о вашей работе — для ментора>"
TZ=<Ваш/Пояс>
BRIEFING_TIME=08:00
MENTOR_DAY=Fri
MENTOR_TIME=16:00
```

**Скиллы ментора (по желанию).** Положите свои скиллы в
`.claude-config/skills/<имя>/SKILL.md`, по каталогу на скилл, в формате скиллов Claude
Code. Затем поправьте `config/mentor-skills.md`, где указано, какой тип вопроса каким
скиллом разбирать. Пример маппинга с именами 14 скиллов есть в файле. Сами скиллы в
репозиторий не входят. Если скиллов нет, ментор работает на общих принципах.

## 12. `install.sh`

Сначала посмотрите, что будет сделано:

```bash
assistant$ ./install.sh --dry-run
```

Затем установите. Можно двумя способами.

**От пользователя ассистента** — юниты рендерятся в `run/systemd/`, и скрипт печатает
команду для их установки:

```bash
assistant$ ./install.sh
$ sudo cp /home/assistant/.local/share/personal-agent/run/systemd/personal-agent* /etc/systemd/system/
$ sudo systemctl daemon-reload
```

**От root** — юниты сразу ставятся в `/etc/systemd/system`, затем выполняются
`daemon-reload` и `chown`:

```bash
$ cd /home/assistant/.local/share/personal-agent && sudo AGENT_USER=assistant ./install.sh
```

Что делает скрипт (повторный запуск безопасен):
- создаёт каталоги `memory/`, `run/`, `logs/` и `.claude-config/skills/`;
- ставит права 700 на `AGENT_HOME` и 600 на `.env`;
- копирует `config/junk_senders.example.txt` → `memory/junk_senders.txt`, если файла ещё нет;
- рендерит `deploy/claude-config-settings.json.in` → `.claude-config/settings.json`
  (подставляет `@AGENT_HOME@` и другие плейсхолдеры) и проверяет, что JSON валиден;
- создаёт `.venv` с Telethon, если её нет (`SKIP_VENV=1` — пропустить);
- рендерит `deploy/systemd/*.in`: пользователь, пути, `TZ` и время таймеров;
- в конце показывает, чего не хватает (токен, `.env`, сессия).

После любой правки `TZ`, `BRIEFING_TIME` или `MENTOR_*` в `.env` запустите `install.sh`
ещё раз и скопируйте юниты.

## 12a. Коннектор MCP (опционально)

Если хотите подключить Notion, Google или трекер задач через MCP вместо app-паролей и своих
скриптов:

```bash
cd ~/.local/share/personal-agent
cp connectors/mcp/mcp.json.example config/mcp.json && chmod 600 config/mcp.json
nano config/mcp.json                       # свои серверы и токены (минимальные права)
nano .env                                  # MCP_CONFIG=config/mcp.json, MCP_ALLOWED_TOOLS=mcp__<сервер>__<инструмент>,…
python3 connectors/mcp/mcp_check.py check  # пишущие инструменты без MCP_ALLOW_WRITE_TOOLS=1 будут отклонены
```

Пусто `MCP_CONFIG` — MCP выключен, промпт не меняется. Права, риски и prompt injection —
[connectors/README.md](connectors/README.md).

## 13. Включить

```bash
$ sudo systemctl enable --now personal-agent.service personal-agent-briefing.timer personal-agent-mentor.timer
$ systemctl list-timers 'personal-agent*'
```

`personal-agent-failed@.service` включать не нужно: его вызывает `OnFailure=` из
остальных юнитов. Он читает журнал через группу `systemd-journal`.

## 14. Проверка и логи

1. **Бот.** Напишите ему `/start`, затем, например, «кто ждёт ответа?» или «что у
   меня завтра?». Сначала бот пишет «Секунду, смотрю…», потом присылает
   ответ. Обычно это занимает от десятков секунд до пары минут, лимит — 240 секунд.
2. **Ручной прогон брифинга** (не дожидаясь утра):

   ```bash
   $ sudo systemctl start personal-agent-briefing.service
   $ journalctl -u personal-agent-briefing -n 50 --no-pager
   ```

   В журнале должно быть `briefing ok`, а в Telegram — сообщение, начинающееся с «☀️».
   Так же проверяется ментор: `personal-agent-mentor.service`, в журнале `mentor ok`.
3. **Где логи:**
   - `journalctl -u personal-agent -f` — бот;
   - `journalctl -u personal-agent-briefing` / `-u personal-agent-mentor` — дежурные задачи;
   - `AGENT_HOME/run/` — `personal.txt` (что ушло в модель), `briefing.txt`,
     `read_err.log`, `claude_err.log`, `mentor_err.log`;
   - `AGENT_HOME/memory/` — `briefing-*.txt`, `mentor-*.txt`, `triage_log.jsonl`
     (какие письма ушли в корзину), `dm_history.jsonl`.

Типичные проблемы:

| Симптом | Где смотреть |
|---|---|
| Бот молчит | `journalctl -u personal-agent`: не тот `OWNER_ID`, пустой `BOT_TOKEN`, вы пишете не в личку |
| «⚠️ Не собрал ответ» | `claude` не в `PATH`, токен в `~/.claude-token.env` протух → шаг 4 |
| «⚠️ … не смог прочитать личку» | `run/read_err.log`; сессия разлогинена → шаг 7 |
| Брифинг начинается с «⚠️ Источники с ошибкой» | так и задумано: строка показывает, какой ящик или календарь упал и почему |
| «ответ без ☀️» | `run/claude_err.log`; обычно авторизация Claude → шаг 4 |
| Брифинг приходит не в то время | `TZ` в `.env` → повторный `install.sh` → скопировать юниты |

## 15. Обновление и удаление

```bash
assistant$ cd ~/.local/share/personal-agent && git pull && ./install.sh
$ sudo cp ~assistant/.local/share/personal-agent/run/systemd/personal-agent* /etc/systemd/system/ && sudo systemctl daemon-reload
$ sudo systemctl restart personal-agent.service
```

Удаление: `sudo systemctl disable --now personal-agent.service personal-agent-briefing.timer
personal-agent-mentor.timer`, удалите юниты из `/etc/systemd/system/` и пользователя
`assistant`. Затем в Telegram → Настройки → Устройства завершите сессию ассистента,
отзовите app-пароли и сбросьте секретные ICS-адреса.
