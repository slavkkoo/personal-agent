#!/usr/bin/env python3
"""Вход в Telegram для СВОЕЙ сессии ассистента (Telethon). Запускать ИНТЕРАКТИВНО
под пользователем ассистента, например:
  ssh -t <admin>@<server> 'sudo -iu assistant ~/.local/share/personal-agent/.venv/bin/python3 \
      ~/.local/share/personal-agent/bin/tg_login.py'

Почему отдельная сессия: одна Telethon-сессия на два клиента (например, копия сессии
другого бота) конфликтует — Telegram рвёт одну из них. Здесь заводится новая.

Показывает, КУДА Telegram отправил код (приложение / почта / SMS), даёт запросить повторно.
Код и облачный пароль вводятся здесь же и никуда не пересылаются. Новая сессия
проверяется чтением диалогов и только потом заменяет старую
(старая → <TG_SESSION>.session.old-<дата>).
"""
import asyncio
import getpass
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pa_common as pa  # noqa: E402

from telethon import TelegramClient, errors, functions  # noqa: E402
from telethon.tl import types  # noqa: E402

WHERE = {
    types.auth.SentCodeTypeApp: "в приложение Telegram — чат «Telegram» (синяя галочка) на любом устройстве, где вы залогинены",
    types.auth.SentCodeTypeSms: "SMS на номер",
    types.auth.SentCodeTypeCall: "звонком",
    types.auth.SentCodeTypeFlashCall: "flash-звонком (код — последние цифры номера)",
    types.auth.SentCodeTypeEmailCode: "на ПОЧТУ, привязанную ко входу в Telegram",
    types.auth.SentCodeTypeFragmentSms: "SMS через Fragment",
}


def describe(sent):
    t = sent.type
    name = WHERE.get(type(t), type(t).__name__)
    extra = ""
    if isinstance(t, types.auth.SentCodeTypeEmailCode):
        extra = f" ({getattr(t, 'email_pattern', '')})"
    if isinstance(t, getattr(types.auth, "SentCodeTypeSetUpEmailRequired", ())):
        name = ("Telegram требует сначала привязать почту для входа "
                "(Настройки → Конфиденциальность → Почта для входа)")
    nxt = type(sent.next_type).__name__ if sent.next_type else "нет"
    return f"Код отправлен: {name}{extra}. Длина кода: {getattr(t, 'length', '?')}. Повторно можно: {nxt}"


async def main():
    pa.load_env()
    old = pa.session_path()
    new = old + "_new"
    phone = os.environ.get("TG_PHONE") or input("Телефон (в международном формате, +…): ").strip()
    name = pa.cfg("ASSISTANT_NAME")
    c = TelegramClient(new, int(os.environ["TG_API_ID"]), os.environ["TG_API_HASH"],
                       device_model=f"{name} (личный ассистент, сервер)", system_version="Linux",
                       app_version="personal-agent-1")
    await c.connect()
    if not await c.is_user_authorized():
        sent = await c.send_code_request(phone)
        print(describe(sent))
        while True:
            code = input("Код (или r — запросить повторно другим способом): ").strip()
            if code.lower() == "r":
                sent = await c(functions.auth.ResendCodeRequest(phone, sent.phone_code_hash))
                print(describe(sent))
                continue
            try:
                await c.sign_in(phone=phone, code=code, phone_code_hash=sent.phone_code_hash)
                break
            except errors.SessionPasswordNeededError:
                await c.sign_in(password=getpass.getpass("Облачный пароль Telegram: "))
                break
            except errors.PhoneCodeInvalidError:
                print("Неверный код, попробуйте ещё раз")
            except errors.PhoneCodeExpiredError:
                print("Код истёк — введите r, чтобы запросить новый")
    me = await c.get_me()
    n = 0
    async for _ in c.iter_dialogs(limit=5):
        n += 1
    await c.disconnect()
    print(f"OK: вошли как {me.first_name}, диалогов прочитано: {n}")
    stamp = time.strftime("%Y%m%d-%H%M")
    if os.path.exists(old + ".session"):
        shutil.move(old + ".session", f"{old}.session.old-{stamp}")
    shutil.move(new + ".session", old + ".session")
    os.chmod(old + ".session", 0o600)
    print(f"Новая сессия: {old}.session. В Telegram → Настройки → Устройства появится «{name} (личный ассистент, сервер)».")


if __name__ == "__main__":
    asyncio.run(main())
