#!/usr/bin/env python3
"""mcp_check — проверка конфига MCP-серверов и белого списка инструментов личного ассистента.

Usage:
  mcp_check.py check     конфиг MCP_CONFIG + белый список MCP_ALLOWED_TOOLS (из .env)
  mcp_check.py args      какие аргументы бот добавит к `claude -p`
  mcp_check.py --selftest  без сети: пример конфига и фикстуры

Бот (только интерактивный чат с владельцем; брифинг и ментор MCP не получают) добавляет
  --mcp-config <MCP_CONFIG> --strict-mcp-config --allowedTools <MCP_ALLOWED_TOOLS…>
В headless-режиме инструмент вне --allowedTools вызвать нельзя — белый список и есть граница.
Пишущие инструменты (create/update/delete/send/…) отклоняются без MCP_ALLOW_WRITE_TOOLS=1:
ассистент читает чужие письма и сообщения, а prompt injection в них превращает
write-инструмент в действие от вашего имени.
"""
import json
import os
import re
import stat
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "bin"))

NAME_RE = re.compile(r"[A-Za-z0-9_-]+")
WRITE_WORDS = {"create", "update", "delete", "remove", "write", "send", "post", "put", "patch", "merge",
               "close", "archive", "move", "upload", "comment", "edit", "set", "add", "insert", "publish",
               "invite", "share", "transfer", "run", "exec", "execute", "append", "replace", "trash", "complete"}
SECRETISH = re.compile(r"(?i)(token|secret|key|password|authorization)")


def is_write(tool):
    words = re.split(r"[_\-.]+|(?<=[a-z0-9])(?=[A-Z])", tool)
    return any(w.lower() in WRITE_WORDS for w in words if w)


def parse_tool(t):
    if not t.startswith("mcp__"):
        return None
    srv, sep, tool = t[5:].partition("__")
    if not srv or not NAME_RE.fullmatch(srv) or (sep and not NAME_RE.fullmatch(tool or "")):
        return None
    return srv, (tool if sep else None)


def check_config(cfg):
    errs, warns = [], []
    servers = cfg.get("mcpServers") if isinstance(cfg, dict) else None
    if not isinstance(servers, dict) or not servers:
        return ["нет объекта mcpServers"], warns, {}
    for name, s in servers.items():
        if not NAME_RE.fullmatch(name):
            errs.append(f"{name}: имя сервера — только буквы/цифры/_/-")
        kind = s.get("type", "stdio")
        if kind == "stdio":
            if not s.get("command"):
                errs.append(f"{name}: stdio без command")
        elif kind in ("http", "sse"):
            url = s.get("url", "")
            if not url.startswith(("https://", "http://127.0.0.1", "http://localhost")):
                errs.append(f"{name}: url должен быть https:// (или localhost)")
        else:
            errs.append(f"{name}: неизвестный type {kind!r}")
        for where in ("env", "headers"):
            for k, v in (s.get(where) or {}).items():
                if SECRETISH.search(k) and isinstance(v, str) and v and "<" not in v and not v.startswith("${"):
                    warns.append(f"{name}.{where}.{k}: похоже на живой секрет — файл вне git, chmod 600")
    return errs, warns, servers


def check_tools(tools, servers, allow_write):
    ok, errs = [], []
    for t in tools:
        parsed = parse_tool(t)
        if not parsed:
            errs.append(f"{t}: формат mcp__<сервер>__<инструмент>")
            continue
        srv, tool = parsed
        if servers and srv not in servers:
            errs.append(f"{t}: сервера {srv} нет в конфиге")
            continue
        if (tool is None or is_write(tool)) and not allow_write:
            errs.append(f"{t}: весь сервер или пишущий инструмент — нужен явный MCP_ALLOW_WRITE_TOOLS=1")
            continue
        ok.append(t)
    return ok, errs


def bot_args(cfg_path, tools):
    if not cfg_path or not tools:
        return []
    return ["--mcp-config", cfg_path, "--strict-mcp-config", "--allowedTools", *tools]


def setup(env, home):
    """→ (аргументы claude, разрешённые инструменты, ошибки). env — словарь окружения."""
    p = env.get("MCP_CONFIG", "").strip()
    if not p:
        return [], [], []
    p = p if os.path.isabs(p) else os.path.join(home, p)
    try:
        with open(p, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError) as e:
        return [], [], [f"{p}: {e}"]
    errs, _, servers = check_config(cfg)
    if errs:
        return [], [], errs
    tools = [t.strip() for t in env.get("MCP_ALLOWED_TOOLS", "").split(",") if t.strip()]
    ok, terrs = check_tools(tools, servers, env.get("MCP_ALLOW_WRITE_TOOLS") == "1")
    return bot_args(p, ok), ok, terrs


def selftest():
    n, fail = 0, []

    def eq(got, want, what):
        nonlocal n
        n += 1
        if got != want:
            fail.append(f"{what}: ждали {want!r}, получили {got!r}")
    with open(os.path.join(HERE, "mcp.json.example"), encoding="utf-8") as f:
        ex = json.load(f)
    errs, warns, servers = check_config(ex)
    eq((errs, warns), ([], []), "пример конфига валиден и без живых секретов")
    eq(sorted(servers), ["notes", "todo"], "два сервера")
    eq({s["type"] for s in servers.values()}, {"stdio", "http"}, "stdio и http")
    eq(check_tools(["mcp__notes__search", "mcp__todo__list_tasks"], servers, False)[0],
       ["mcp__notes__search", "mcp__todo__list_tasks"], "read-инструменты проходят")
    eq(check_tools(["mcp__todo__create_task", "mcp__todo__completeTask", "mcp__notes"], servers, False)[0], [],
       "пишущие и весь сервер — отказ")
    eq(check_tools(["mcp__todo__create_task"], servers, True)[0], ["mcp__todo__create_task"], "с явным разрешением")
    eq(len(check_tools(["mcp__ghost__x", "Bash(rm:*)", "mcp__notes__"], servers, False)[1]), 3, "битые имена")
    eq(is_write("list_datasets"), False, "dataset ≠ set")
    live = {"mcpServers": {"x": {"type": "http", "url": "http://mcp.example.com",
                                 "headers": {"Authorization": "Bearer " + "abc" + "def12345"}}}}
    errs, warns, _ = check_config(live)
    eq((bool(errs), bool(warns)), (True, True), "http без TLS и живой токен")
    import tempfile
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "mcp.json"), "w") as f:
        json.dump(ex, f)
    args, ok, _ = setup({"MCP_CONFIG": "mcp.json", "MCP_ALLOWED_TOOLS": "mcp__notes__search,mcp__todo__create_task"}, d)
    eq(args, ["--mcp-config", os.path.join(d, "mcp.json"), "--strict-mcp-config", "--allowedTools", "mcp__notes__search"],
       "аргументы бота без пишущего")
    eq(setup({"MCP_CONFIG": ""}, d), ([], [], []), "выключен — пусто")
    eq(setup({"MCP_CONFIG": "mcp.json", "MCP_ALLOWED_TOOLS": ""}, d)[0], [], "без инструментов MCP не подключается")
    if fail:
        print(f"selftest mcp: FAIL {len(fail)} из {n}")
        for x in fail:
            print("  ✗ " + x)
        sys.exit(1)
    print(f"selftest mcp: OK ({n} проверок)")


def main():
    a = sys.argv[1:]
    if a[:1] == ["--selftest"]:
        selftest()
        return
    import pa_common as pa
    pa.load_env()
    args, ok, errs = setup(dict(os.environ), pa.AGENT_HOME)
    if a[:1] == ["args"]:
        print(" ".join(args) or "(MCP не подключится)")
        return
    for x in errs:
        print("✗ " + x)
    p = os.environ.get("MCP_CONFIG", "")
    if p:
        p = p if os.path.isabs(p) else pa.path(p)
        if os.path.exists(p) and stat.S_IMODE(os.stat(p).st_mode) & 0o077:
            print(f"! {p}: поставьте chmod 600 (в файле токены)")
    print(f"разрешено инструментов: {len(ok)}: {', '.join(ok) or '—'}")
    sys.exit(1 if errs or not ok else 0)


if __name__ == "__main__":
    main()
