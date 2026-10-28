#!/usr/bin/env python3
"""Общие функции личного ассистента: загрузка .env, настройки, рендер промптов.

Python 3.11+, только stdlib. Импортируется остальными скриптами из bin/.

CLI (для bash-обёрток — чтобы не собирать промпт в heredoc):
  pa_common.py render <имя_промпта> [KEY=VALUE ...]
    Печатает prompts/<имя>.md с подставленными {{ПЕРЕМЕННЫМИ}}.
    Если после подстановки остался незаполненный {{...}} — выход с ошибкой.
"""
import os
import re
import sys
import time

# Корень установки = родитель bin/. Переопределяется AGENT_HOME (для тестов).
AGENT_HOME = os.environ.get("AGENT_HOME") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULTS = {
    "ASSISTANT_NAME": "Ассистент",
    "OWNER_NAME": "Владелец",
    "OWNER_ROLE": "",
    "MODEL_ANSWER": "claude-opus-5-5",
    "MODEL_DUTY": "claude-sonnet-5-5",
    "TG_SESSION": "personal_reader",
}

_PLACEHOLDER = re.compile(r"\{\{([A-Z0-9_]+)\}\}")


def path(*parts):
    return os.path.join(AGENT_HOME, *parts)


def load_env(required=True):
    """Читает AGENT_HOME/.env (KEY=VALUE, # — комментарий, кавычки снимаются).
    Уже заданные переменные окружения не перезаписываются."""
    p = path(".env")
    if not os.path.exists(p):
        if required:
            sys.exit(f"нет {p} — скопируйте .env.example в .env и заполните")
        return
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if k.startswith("export "):
                k = k[len("export "):].strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            os.environ.setdefault(k, v)
    if os.environ.get("TZ") and hasattr(time, "tzset"):
        time.tzset()


def cfg(key, default=None):
    v = os.environ.get(key, "")
    if v:
        return v
    return DEFAULTS.get(key, default) if default is None else default


def session_path():
    """TG_SESSION: относительный путь считается от AGENT_HOME (без суффикса .session)."""
    s = cfg("TG_SESSION")
    return s if os.path.isabs(s) else path(s)


def numbered(prefix, suffix, limit=5):
    """MAIL1_USER, MAIL2_USER… → список номеров, у которых задана переменная."""
    return [n for n in range(1, limit + 1) if os.environ.get(f"{prefix}{n}_{suffix}")]


# ---------- скиллы ментора ----------

def installed_skills():
    root = path(".claude-config", "skills")
    if not os.path.isdir(root):
        return []
    return sorted(d for d in os.listdir(root) if os.path.isfile(os.path.join(root, d, "SKILL.md")))


def mentor_mapping():
    """config/mentor-skills.md: строки вида «- <тип вопроса> -> <имя-скилла>»."""
    p = path("config", "mentor-skills.md")
    out = []
    if not os.path.exists(p):
        return out
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("- ") and "->" in line:
                when, skill = line[2:].rsplit("->", 1)
                out.append((when.strip(), skill.strip().strip("`")))
    return out


def mentor_skills_block():
    have = set(installed_skills())
    skills_dir = path(".claude-config", "skills")
    if not have:
        return ("Скиллы-фреймворки не установлены. Отвечай на общих принципах продуктового "
                "менеджмента: какая проблема и насколько она острая → для какого клиента → "
                "какая метрика покажет успех → какой минимальный эксперимент это проверит. "
                "Не выдумывай названия фреймворков.")
    lines = [f"ОБЯЗАТЕЛЬНО: перед ответом на продуктовый вопрос выбери подходящий скилл, ПРОЧИТАЙ "
             f"файл {skills_dir}/<имя>/SKILL.md и применяй его методику, а не общие слова. "
             f"Маппинг «тип вопроса → скилл»:"]
    mapped = set()
    for when, skill in mentor_mapping():
        if skill in have:
            lines.append(f"- {when} -> {skill}")
            mapped.add(skill)
    rest = sorted(have - mapped)
    if rest:
        lines.append("Другие установленные скиллы (выбирай по описанию в SKILL.md): " + ", ".join(rest))
    lines.append("В ответе скажи, какой фреймворк использовал. Если ни один не подходит — так и скажи "
                 "и отвечай на общих принципах.")
    return "\n".join(lines)


# ---------- GitLab ----------

def gitlab_enabled():
    return all(os.environ.get(k) for k in ("GITLAB_URL", "GITLAB_TOKEN", "GITLAB_PROJECT"))


def gitlab_labels():
    return [x.strip() for x in os.environ.get("GITLAB_LABELS", "").split(",") if x.strip()]


def gitlab_marker():
    return os.environ.get("GITLAB_MARKER") or f"Создано через ассистента {cfg('ASSISTANT_NAME')}"


# ---------- рендер промптов ----------

def base_vars():
    role = cfg("OWNER_ROLE", "")
    return {
        "ASSISTANT_NAME": cfg("ASSISTANT_NAME"),
        "OWNER_NAME": cfg("OWNER_NAME"),
        "OWNER_ROLE": role or "роль не указана",
        "AGENT_HOME": AGENT_HOME,
        "PY_VENV": path(".venv", "bin", "python3"),
        "GITLAB_LABELS": ", ".join(gitlab_labels()) or "(список пуст — создавай без лейблов)",
        "GITLAB_MARKER": gitlab_marker(),
    }


def _fill(text, values, name):
    def sub(m):
        k = m.group(1)
        return values[k] if k in values else m.group(0)
    out = _PLACEHOLDER.sub(sub, text)
    left = sorted(set(_PLACEHOLDER.findall(out)))
    if left:
        raise ValueError(f"промпт {name}: не заполнены {', '.join(left)}")
    return out


def render(name, extra=None, raw=None):
    """prompts/<name>.md → текст. extra — доп. переменные; raw — значения, которые
    подставляются ПОСЛЕ проверки (текст пользователя может содержать «{{», и это не ошибка)."""
    with open(path("prompts", f"{name}.md"), encoding="utf-8") as f:
        text = f.read()
    values = base_vars()
    values["MENTOR_SKILLS"] = mentor_skills_block()
    gl = ""
    if gitlab_enabled():
        with open(path("prompts", "assistant-gitlab.md"), encoding="utf-8") as f:
            gl = _fill(f.read(), values, "assistant-gitlab").strip()
    values["GITLAB_TOOLS"] = gl or "- GitLab не настроен: задачи в трекере ты не читаешь и не создаёшь."
    values.update(extra or {})
    markers = {}
    for i, k in enumerate(raw or {}):
        markers[k] = f"\x00RAW{i}\x00"
    values.update(markers)
    out = _fill(text, values, name)
    for k, m in markers.items():
        out = out.replace(m, raw[k])
    return out.strip() + "\n"


def main():
    a = sys.argv[1:]
    if len(a) >= 2 and a[0] == "render":
        load_env()
        extra = {}
        for kv in a[2:]:
            k, _, v = kv.partition("=")
            extra[k] = v
        try:
            sys.stdout.write(render(a[1], extra))
        except (OSError, ValueError) as e:
            sys.exit(str(e))
        return
    sys.exit(__doc__)


if __name__ == "__main__":
    main()
