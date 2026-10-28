#!/usr/bin/env python3
"""События календаря на N дней из секретных ICS-адресов Google Calendar (read-only).

В .env (секретный адрес в формате iCal — где его взять, см. INSTALL.md):
  CAL1_ICS=https://calendar.google.com/calendar/ical/.../basic.ics
  CAL1_LABEL=личный
  CAL2_ICS=…   CAL2_LABEL=рабочий      (до CAL5_*)
Usage: read_calendar.py [days=2]

Ограничения простого парсера: повторяющиеся события (RRULE) показываются только
в дату первого вхождения; время с TZID трактуется как локальное время сервера —
поставьте в .env тот же TZ, что у календаря.
"""
import datetime as dt
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pa_common as pa  # noqa: E402


def unescape(s):
    return s.replace("\\n", " ").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def parse_ics(text):
    text = re.sub(r"\r?\n[ \t]", "", text)   # длинные строки ICS переносятся с пробелом
    events = []
    for block in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.S):
        def field(name):
            m = re.search(rf"^{name}[^:\r\n]*:(.+)$", block, re.M)
            return unescape(m.group(1).strip()) if m else ""
        if field("STATUS").upper() == "CANCELLED":
            continue
        events.append({"start": field("DTSTART"), "summary": field("SUMMARY"),
                       "loc": field("LOCATION")})
    return events


def to_dt(v):
    """→ (datetime в локальном времени, весь_день?) или (None, False)."""
    v = v.strip()
    try:
        if "T" in v:
            d = dt.datetime.strptime(v.rstrip("Z"), "%Y%m%dT%H%M%S")
            if v.endswith("Z"):
                d = d.replace(tzinfo=dt.timezone.utc).astimezone().replace(tzinfo=None)
            return d, False
        return dt.datetime.strptime(v, "%Y%m%d"), True
    except ValueError:
        return None, False


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    pa.load_env()
    feeds = [(os.environ.get(f"CAL{n}_LABEL") or f"календарь {n}", os.environ[f"CAL{n}_ICS"])
             for n in pa.numbered("CAL", "ICS")]
    if not feeds:
        print("(календарь не настроено: нет CAL1_ICS в .env)")
        return
    today = dt.date.today()
    horizon = today + dt.timedelta(days=days)
    for label, url in feeds:
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                text = r.read().decode("utf-8", "replace")
        except Exception as e:
            # адрес секретный — в вывод только тип ошибки, без URL
            print(f"\n=== 📅 Календарь ({label}): ОШИБКА {type(e).__name__} ===")
            continue
        rows = []
        for e in parse_ics(text):
            d, allday = to_dt(e["start"])
            if not d:
                continue
            day = d.date()
            if today <= day < horizon:
                t = "весь день" if allday else d.strftime("%H:%M")
                loc = f" @{e['loc'][:30]}" if e["loc"] else ""
                rows.append((day, t, f"{e['summary'][:80]}{loc}"))
        rows.sort()
        print(f"\n=== 📅 Календарь ({label}): {len(rows)} событий до {horizon.strftime('%d.%m')} ===")
        for day, t, s in rows[:20]:
            print(f"  {day.strftime('%d.%m')} {t}  {s}")


if __name__ == "__main__":
    main()
