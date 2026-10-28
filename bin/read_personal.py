#!/usr/bin/env python3
"""READ-ONLY дамп ЛИЧНЫХ Telegram-диалогов владельца за последние N часов.

Личные = один-на-один с людьми (не группы, не каналы, не боты).
Usage: read_personal.py [hours=24] [max_dialogs=40]
Вывод: по диалогу — имя, unread, сообщения окна (реплики владельца — под OWNER_NAME).
Запускать из venv с telethon: .venv/bin/python3 bin/read_personal.py
Сессия — своя (bin/tg_login.py), не копия сессии другого клиента.
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pa_common as pa  # noqa: E402

from telethon import TelegramClient  # noqa: E402


async def main():
    hours = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    max_dialogs = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    pa.load_env()
    owner = pa.cfg("OWNER_NAME")
    sess = pa.session_path()
    if not os.path.exists(sess + ".session"):
        sys.exit(f"нет сессии {sess}.session — сначала bin/tg_login.py")
    client = TelegramClient(sess, int(os.environ["TG_API_ID"]), os.environ["TG_API_HASH"])
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        sys.exit("сессия Telegram не авторизована — перезайдите через bin/tg_login.py")
    me = await client.get_me()
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    shown = 0
    async for d in client.iter_dialogs(limit=250):
        if shown >= max_dialogs:
            break
        e = d.entity
        if not d.is_user or getattr(e, "bot", False) or getattr(e, "id", 0) == me.id:
            continue
        last = d.date if d.date.tzinfo else d.date.replace(tzinfo=dt.timezone.utc)
        if last < since and not d.unread_count:
            continue
        name = " ".join(x for x in [getattr(e, "first_name", ""), getattr(e, "last_name", "")] if x) or "?"
        uname = f" @{e.username}" if getattr(e, "username", None) else ""
        print(f"\n=== {name}{uname} | unread: {d.unread_count} ===")
        msgs = []
        async for m in client.iter_messages(e, limit=30):
            mdate = m.date if m.date.tzinfo else m.date.replace(tzinfo=dt.timezone.utc)
            if mdate < since:
                break
            who = owner if m.out else name
            text = (m.message or "(вложение/медиа)").replace("\n", " ")[:400]
            msgs.append(f"  [{mdate.astimezone().strftime('%d.%m %H:%M')}] {who}: {text}")
        for line in reversed(msgs):
            print(line)
        if not msgs and d.unread_count:
            print("  (непрочитанное старше окна)")
        shown += 1
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
