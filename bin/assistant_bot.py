#!/usr/bin/env python3
"""Личный ассистент — интерактивный Telegram-бот (только личка владельца).

Отвечает ТОЛЬКО владельцу (OWNER_ID из .env) в личном чате. Остальные люди,
группы и каналы получают тишину. На каждое сообщение запускается headless
Claude Code (`claude -p`) с личными инструментами из bin/ (права — в
.claude-config/settings.json, см. deploy/claude-config-settings.json.in).

Режим настройки: если OWNER_ID пуст, бот на любое личное сообщение отвечает
только числовым ID отправителя — чтобы вы узнали свой ID. Больше он ничего не делает.

Python 3.11+, stdlib-only.
"""
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pa_common as pa  # noqa: E402

QUERY_TIMEOUT_S = 240
STATE = pa.path("memory", "updates_state.json")
HIST = pa.path("memory", "dm_history.jsonl")
HIST_WINDOW_S = 20 * 60   # помним диалог 20 минут…
HIST_TURNS = 6            # …и не больше 6 последних реплик


def api(method, **params):
    tok = os.environ["BOT_TOKEN"]
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/{method}", data=data)
    with urllib.request.urlopen(req, timeout=70) as r:
        return json.load(r)


def send(chat_id, text):
    while text:
        chunk, text = text[:3900], text[3900:]
        try:
            r = api("sendMessage", chat_id=chat_id, text=chunk)
            if not r.get("ok"):
                print(f"telegram: {str(r)[:300]}", file=sys.stderr)
        except Exception as e:
            print(f"telegram: {type(e).__name__}: {e}", file=sys.stderr)


def hist_append(role, text):
    os.makedirs(os.path.dirname(HIST), exist_ok=True)
    with open(HIST, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.time(), "role": role, "text": text[:1500]},
                           ensure_ascii=False) + "\n")


def hist_recent():
    try:
        now, turns = time.time(), []
        with open(HIST, encoding="utf-8") as f:
            for line in f:
                try:
                    t = json.loads(line)
                except ValueError:
                    continue
                if now - t.get("ts", 0) <= HIST_WINDOW_S:
                    turns.append(t)
        return turns[-HIST_TURNS:]
    except OSError:
        return []


def build_prompt(question, reply_ctx=""):
    owner = pa.cfg("OWNER_NAME")
    ctx = ""
    if reply_ctx:
        ctx += (f"\n\nЭто РЕПЛАЙ владельца ({owner}) на твоё сообщение — процитированное является "
                "прямым контекстом вопроса (местоимения «ей/её/это» относятся к нему):\n«"
                + reply_ctx[:1200] + "»")
    turns = hist_recent()
    if turns:
        lines = "\n".join(f"[{t['role']}]: {t['text']}" for t in turns)
        ctx += ("\n\nФон — последние реплики вашего диалога (используй, если вопрос — продолжение):\n"
                + lines)
    return pa.render("assistant", raw={"CONTEXT": ctx, "QUESTION": question})


def run_agent(prompt):
    env = dict(os.environ)
    env["CLAUDE_CONFIG_DIR"] = pa.path(".claude-config")
    # MCP (connectors/mcp): только в чате с владельцем, по белому списку инструментов
    mcp_args, _ = pa.mcp_setup()
    deny = [t.strip() for t in os.environ.get("MCP_DISALLOWED_TOOLS", "").split(",") if t.strip()]
    if mcp_args and deny:
        mcp_args += ["--disallowedTools", *deny]
    try:
        out = subprocess.run(
            ["claude", "--model", pa.cfg("MODEL_ANSWER"), "--add-dir", pa.AGENT_HOME,
             "--output-format", "json", *mcp_args, "-p", prompt],
            capture_output=True, text=True, timeout=QUERY_TIMEOUT_S, cwd=pa.AGENT_HOME, env=env)
        try:
            d = json.loads(out.stdout.strip())
            text = (d.get("result") or "").strip()
            return text, bool(text) and not d.get("is_error")
        except ValueError:
            if out.returncode != 0:
                print(f"claude rc={out.returncode}: {out.stderr[-300:]}", file=sys.stderr)
            return out.stdout.strip(), out.returncode == 0
    except subprocess.TimeoutExpired:
        return "", False
    except FileNotFoundError:
        print("claude не найден в PATH", file=sys.stderr)
        return "", False


def state_load():
    try:
        with open(STATE) as f:
            return json.load(f)
    except Exception:
        return {"offset": 0}


def state_save(s):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w") as f:
        json.dump(s, f)


def handle(msg, owner_id):
    chat = msg.get("chat") or {}
    uid = str((msg.get("from") or {}).get("id"))
    text = (msg.get("text") or "").strip()
    if chat.get("type") != "private" or not text:
        return
    if not owner_id:
        # режим настройки: только сообщаем ID, ничего не читаем и не запускаем
        send(chat["id"], f"Ваш Telegram ID: {uid}\nВпишите его в OWNER_ID в .env и перезапустите бота.")
        return
    if uid != owner_id:
        return  # не владелец — тишина
    name = pa.cfg("ASSISTANT_NAME")
    owner = pa.cfg("OWNER_NAME")
    if text == "/start":
        send(chat["id"], f"🤵 {name} на связи. Спрашивай, кто ждёт ответа, что в календаре, "
                         "проси спланировать день или записать задачу.")
        return
    reply_ctx = ""
    rt = msg.get("reply_to_message") or {}
    if (rt.get("from") or {}).get("is_bot") and rt.get("text"):
        reply_ctx = rt["text"]
    send(chat["id"], "Секунду, смотрю…")
    answer, ok = run_agent(build_prompt(text, reply_ctx))
    final = answer if ok and answer else "⚠️ Не собрал ответ — попробуй переформулировать."
    send(chat["id"], final)
    hist_append(owner, text)
    hist_append(name, final)


def main():
    pa.load_env()
    if not os.environ.get("BOT_TOKEN"):
        sys.exit("нет BOT_TOKEN в .env")
    owner_id = os.environ.get("OWNER_ID", "").strip()
    if not owner_id:
        print("OWNER_ID пуст — режим настройки: бот только сообщает ID отправителя", file=sys.stderr)
    s = state_load()
    while True:
        try:
            upd = api("getUpdates", offset=s["offset"], timeout=50)
        except Exception:
            time.sleep(5)
            continue
        for u in upd.get("result", []):
            s["offset"] = u["update_id"] + 1
            state_save(s)
            try:
                handle(u.get("message") or {}, owner_id)
            except Exception as e:
                print(f"handle: {type(e).__name__}: {e}", file=sys.stderr)
        time.sleep(1)


if __name__ == "__main__":
    main()
