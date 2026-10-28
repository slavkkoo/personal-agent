#!/usr/bin/env python3
"""Триаж почты (IMAP, ящики MAIL1…MAIL5). Мусор → корзина, остальное → сводка.

Мусор = отправители из memory/junk_senders.txt (по адресу на строку, # — комментарий).
Список пополняется по просьбе владельца («это тоже мусор») командой add-junk.

Usage:
  mail_triage.py [hours=24] [--clean]   # сводка непрочитанного; --clean — мусор в корзину
  mail_triage.py add-junk <email>       # добавить отправителя в мусор
  mail_triage.py list-folders           # показать папки ящиков (найти имя корзины)

Защиты:
- письма читаются через BODY.PEEK — не помечаются прочитанными;
- «удаление» = MOVE в корзину (в Gmail она хранит письма 30 дней), без EXPUNGE;
- двигаем только точные совпадения адреса отправителя (IMAP FROM ищет подстроку).

Корзина: сначала ищется папка с флагом \\Trash (Gmail его ставит), иначе берётся
MAILn_TRASH / MAIL_TRASH (по умолчанию «[Gmail]/Trash»). В локализованном Gmail имя
другое и закодировано в modified UTF-7 — например, для русского интерфейса
«[Gmail]/Корзина» выглядит как «[Gmail]/&BBoEPgRABDcEOAQ9BDA-». Точное имя покажет
`mail_triage.py list-folders` (строка с \\Trash).
"""
import datetime as dt
import email
import email.header
import email.utils
import imaplib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pa_common as pa  # noqa: E402

JUNK_FILE = pa.path("memory", "junk_senders.txt")
LOG_FILE = pa.path("memory", "triage_log.jsonl")   # что ушло в корзину (без тем писем)
DEFAULT_TRASH = "[Gmail]/Trash"
ADDR_RE = re.compile(r'^[^\s"\\()<>,;]+@[^\s"\\()<>,;]+$')


def boxes():
    out = []
    for n in pa.numbered("MAIL", "USER"):
        u, p = os.environ.get(f"MAIL{n}_USER"), os.environ.get(f"MAIL{n}_PASS")
        if not p:
            continue
        out.append({
            "user": u, "pass": p.replace(" ", ""),   # app-пароль Google показывают с пробелами
            "label": os.environ.get(f"MAIL{n}_LABEL") or u,
            "host": os.environ.get(f"MAIL{n}_HOST") or "imap.gmail.com",
            "trash": os.environ.get(f"MAIL{n}_TRASH") or os.environ.get("MAIL_TRASH") or DEFAULT_TRASH,
        })
    return out


def junk_list():
    if not os.path.exists(JUNK_FILE):
        return []
    out = []
    with open(JUNK_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip().lower()
            if line and not line.startswith("#"):
                out.append(line)
    return out


def dec(s):
    out = []
    for part, enc in email.header.decode_header(s or ""):
        out.append(part.decode(enc or "utf-8", "replace") if isinstance(part, bytes) else part)
    return "".join(out)


def quote_box(name):
    return '"' + name.strip('"') + '"'


def find_trash(M, fallback):
    for f in (M.list()[1] or []):
        s = f.decode(errors="replace")
        if "\\Trash" in s:
            return quote_box(s.split(' "/" ')[-1])
    return quote_box(fallback)


def connect(b):
    M = imaplib.IMAP4_SSL(b["host"])
    M.login(b["user"], b["pass"])
    return M


def triage_box(b, hours, clean, junk):
    M = connect(b)
    M.select("INBOX")
    trash = find_trash(M, b["trash"])
    moved = 0
    if clean:
        for s in junk:
            _, d = M.uid("SEARCH", None, f'(FROM "{s}")')
            cand = d[0].split()
            exact = []
            for i in range(0, len(cand), 200):
                _, md = M.uid("FETCH", b",".join(cand[i:i + 200]).decode(),
                              "(UID BODY.PEEK[HEADER.FIELDS (FROM)])")
                for part in md:
                    if not isinstance(part, tuple):
                        continue
                    head = part[0].decode(errors="replace")
                    uid = head.split("UID ")[1].split()[0] if "UID " in head else None
                    addr = email.utils.parseaddr(dec(email.message_from_bytes(part[1]).get("From", "")))[1].lower()
                    if uid and addr == s:
                        exact.append(uid.encode())
            n = 0
            for i in range(0, len(exact), 400):
                ok, _ = M.uid("MOVE", b",".join(exact[i:i + 400]).decode(), trash)
                if ok == "OK":
                    n += len(exact[i:i + 400])
            if n:
                moved += n
                with open(LOG_FILE, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"ts": dt.datetime.now().isoformat(timespec="seconds"),
                                        "box": b["label"], "sender": s, "moved": n,
                                        "skipped_not_exact": len(cand) - len(exact)},
                                       ensure_ascii=False) + "\n")
    since = (dt.datetime.now() - dt.timedelta(hours=hours)).strftime("%d-%b-%Y")
    _, d = M.uid("SEARCH", None, f'(UNSEEN SINCE "{since}")')
    rows = []
    for uid in d[0].split()[-40:]:
        _, md = M.uid("FETCH", uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])")
        m = email.message_from_bytes(md[0][1])
        frm = dec(m.get("From", ""))
        if email.utils.parseaddr(frm)[1].lower() in junk:
            continue
        rows.append(f"  • {frm[:55]} — {dec(m.get('Subject', '(без темы)'))[:110]}")
    print(f"\n=== 📬 {b['label']}: мусора убрано {moved}, непрочитанных (не мусор) за {hours}ч: {len(rows)} ===")
    for r in rows:
        print(r)
    M.logout()


def list_folders():
    for b in boxes():
        print(f"\n=== {b['label']} ===")
        try:
            M = connect(b)
            for f in (M.list()[1] or []):
                s = f.decode(errors="replace")
                print(("  ← корзина (\\Trash)  " if "\\Trash" in s else "  ") + s)
            M.logout()
        except Exception as e:
            print(f"  ОШИБКА {type(e).__name__}: {e}")


def main():
    a = sys.argv[1:]
    if len(a) >= 2 and a[0] == "add-junk":
        addr = a[1].strip().lower()
        if not ADDR_RE.match(addr):
            sys.exit("это не похоже на email-адрес")
        os.makedirs(os.path.dirname(JUNK_FILE), exist_ok=True)
        if addr in junk_list():
            print(f"{addr} уже в списке мусора")
            return
        with open(JUNK_FILE, "a", encoding="utf-8") as f:
            f.write(addr + "\n")
        print(f"добавлен в мусор: {addr} (письма уйдут в корзину при следующем триаже)")
        return
    pa.load_env()
    if a and a[0] == "list-folders":
        list_folders()
        return
    clean = "--clean" in a
    args = [x for x in a if x != "--clean"]
    hours = int(args[0]) if args else 24
    bx = boxes()
    if not bx:
        print("(почта: не настроено — нет MAIL1_USER/MAIL1_PASS в .env)")
        return
    junk = [j for j in junk_list() if ADDR_RE.match(j)]
    if clean and not junk:
        print("(memory/junk_senders.txt пуст — чистка пропущена)")
    for b in bx:
        try:
            triage_box(b, hours, clean and bool(junk), junk)
        except Exception as e:
            print(f"\n=== 📬 {b['label']}: ОШИБКА {type(e).__name__}: {str(e)[:120]} ===")


if __name__ == "__main__":
    main()
