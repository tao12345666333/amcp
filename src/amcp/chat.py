from __future__ import annotations

import contextlib
import json
import os
import re
from collections.abc import Iterable
from pathlib import Path

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel

from .config import AMCPConfig, ChatConfig, load_config
from .mcp_client import call_mcp_tool, list_mcp_tools
from .readfile import read_file_with_ranges

console = Console()


def _run_quietly(coro):
    """Run an asyncio coroutine while suppressing child-process stderr.
    This helps hide noisy MCP server startup logs in chat mode.
    """
    import contextlib

    with open(os.devnull, "w") as devnull, contextlib.redirect_stderr(devnull):
        return __import__("asyncio").run(coro)


def _resolve_base_url(cli_base: str | None, cfg: ChatConfig | None) -> str:
    # CLI > config > env > default
    base = (
        cli_base
        or (cfg.base_url if cfg and cfg.base_url else None)
        or os.environ.get("AMCP_OPENAI_BASE")
        or "https://inference.baseten.co/v1"
    ).rstrip("/")
    if not base.endswith("/v1"):
        base = base + "/v1"
    return base


def _resolve_api_key(cli_key: str | None, cfg: ChatConfig | None) -> str | None:
    # CLI > config > env
    if cli_key:
        return cli_key
    if cfg and cfg.api_key:
        return cfg.api_key
    return os.environ.get("OPENAI_API_KEY")


def _make_client(base_url: str, api_key: str | None):
    try:
        from openai import OpenAI
    except Exception:  # pragma: no cover
        console.print("[red]openai package not installed. Please install dependencies.[/red]")
        raise
    return OpenAI(base_url=base_url, api_key=api_key or "")


def _stream_chat(client, model: str, messages: list[dict], stream: bool = True) -> str:
    # Primary path: Chat Completions streaming
    try:
        if stream:
            accum = []
            with Live(console=console, refresh_per_second=12) as live:
                live.update(Panel("", title="assistant", border_style="cyan"))
                for chunk in client.chat.completions.create(
                    model=model,
                    messages=messages,
                    stream=True,
                ):
                    delta = getattr(chunk.choices[0].delta, "content", None)
                    if delta:
                        accum.append(delta)
                        live.update(Panel(Markdown("".join(accum)), title="assistant", border_style="cyan"))
            return "".join(accum)
        else:
            resp = client.chat.completions.create(model=model, messages=messages, stream=False)
            return resp.choices[0].message.content or ""
    except Exception:
        # Fallback to Responses API if provider prefers it
        try:
            if stream:
                accum = []
                with Live(console=console, refresh_per_second=12) as live:
                    live.update(Panel("", title="assistant", border_style="cyan"))
                    for event in client.responses.stream(
                        model=model,
                        input=messages,
                    ):
                        if event.type == "response.output_text.delta":
                            accum.append(event.delta)
                            live.update(Panel(Markdown("".join(accum)), title="assistant", border_style="cyan"))
                return "".join(accum)
            else:
                r = client.responses.create(model=model, input=messages)
                parts = []
                for item in r.output:
                    if item.type == "output_text":
                        parts.append(item.text)
                return "".join(parts)
        except Exception:
            raise


def _fmt_block_for_console(file: Path, start: int, end: int, lines: list[tuple[int, str]]) -> str:
    # Render as a code block with metadata for CLI display
    header = f"```text path={file} start={start}\n"
    body = "\n".join(line for _, line in lines)
    return header + body + "\n```"


def _attach_file_context(path: Path, ranges: Iterable[str] | None, max_lines: int = 400) -> tuple[str, str]:
    blocks = read_file_with_ranges(path, list(ranges or []))
    rendered_parts = []
    for b in blocks:
        lines = b["lines"]
        if not ranges and len(lines) > max_lines:
            lines = lines[:max_lines]
            rendered_parts.append(_fmt_block_for_console(path, b["start"], b["start"] + len(lines) - 1, lines))
            rendered_parts.append("[...truncated...]")
            continue
        rendered_parts.append(_fmt_block_for_console(path, b["start"], b["end"], lines))
    # For LLM context, we send plain text without markdown fences to reduce tokens
    llm_context = []
    for b in blocks:
        lines = b["lines"]
        if not ranges and len(lines) > max_lines:
            lines = lines[:max_lines]
        llm_context.append(
            f"FILE: {path} ({b['start']}-{b['start'] + len(lines) - 1})\n" + "\n".join(line for _, line in lines)
        )
        if not ranges and len(b["lines"]) > max_lines:
            llm_context.append("[...truncated...]")
    return "\n\n".join(rendered_parts), "\n\n".join(llm_context)


_READ_CMD = re.compile(
    r"^\s*(?:/read|read|open|查看|读取|打开)\s+(?P<path>\S+)(?:\s+(?:lines?|行|第)\s*(?P<s>\d+)\s*[-~]\s*(?P<e>\d+))?\s*$",
    re.I,
)
_PATH_RANGE_INLINE = re.compile(r"(?P<path>\S+?):(?P<s>\d+)-(?P<e>\d+)")


def _parse_read_intent(text: str) -> list[tuple[Path, list[str] | None]]:
    """Return list of (path, ranges) if the user text clearly asks for reading files.
    Supports:
    - '/read PATH - implicit whole file'
    - 'read PATH lines 10-20'
    - 'PATH:10-20' inline
    """
    out: list[tuple[Path, list[str] | None]] = []
    m = _READ_CMD.match(text)
    if m:
        p = Path(m.group("path")).expanduser()
        ranges = None
        if m.group("s") and m.group("e"):
            ranges = [f"{m.group('s')}-{m.group('e')}"]
        out.append((p, ranges))
        return out
    for m in _PATH_RANGE_INLINE.finditer(text):
        p = Path(m.group("path")).expanduser()
        ranges = [f"{m.group('s')}-{m.group('e')}"]
        out.append((p, ranges))
    # If the text starts with known verbs and the next token looks like a path ending with a known ext
    return out


def _builtin_read_tool_spec() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text file from the local workspace. Returns the full file content with line numbers. If no ranges specified, reads the entire file. CRITICAL: You MUST provide a path to a specific FILE, not a directory. Use relative paths from current working directory (e.g., 'src/amcp/readfile.py', 'README.md'), NOT absolute paths starting with '/'. COMMON FILES: 'src/amcp/readfile.py', 'src/amcp/rg.py', 'src/amcp/cli.py', 'src/amcp/chat.py', 'README.md', 'pyproject.toml'. NEVER use just 'src/amcp' - it's a directory, not a file. IMPORTANT: When you get the file content, analyze it and provide your response - don't call the tool again unless you need additional different files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to a specific FILE (not directory). Use relative paths like 'src/amcp/readfile.py', NEVER directories like 'src/amcp'. COMMON FILES: 'src/amcp/readfile.py', 'src/amcp/rg.py', 'src/amcp/cli.py', 'src/amcp/chat.py', 'README.md', 'pyproject.toml'. Always include the file extension (.py, .md, .toml, etc).",
                    },
                    "ranges": {
                        "type": "array",
                        "items": {"type": "string", "pattern": "^\\d+-\\d+$"},
                        "description": "Optional list of line ranges like '1-200'. Use only if you need specific line ranges. For general file analysis, omit this to get the full file.",
                    },
                    "max_lines": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 5000,
                        "description": "Safety cap for lines returned per block (default 400)",
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    }


def _get_chat_runtime_settings(override: dict | None = None) -> dict:
    cfg: AMCPConfig = load_config()
    chat_cfg = cfg.chat
    tool_loop_limit = chat_cfg.tool_loop_limit if chat_cfg and chat_cfg.tool_loop_limit else 5
    default_max_lines = chat_cfg.default_max_lines if chat_cfg and chat_cfg.default_max_lines else 400
    roots: list[Path]
    if chat_cfg and chat_cfg.read_roots:
        roots = [Path(r).expanduser().resolve() for r in chat_cfg.read_roots]
    else:
        roots = [Path.cwd().resolve()]
    if override:
        if override.get("read_roots"):
            roots = [Path(r).expanduser().resolve() for r in override["read_roots"]]
        if override.get("tool_loop_limit"):
            tool_loop_limit = int(override["tool_loop_limit"])
        if override.get("default_max_lines"):
            default_max_lines = int(override["default_max_lines"])
    return {
        "tool_loop_limit": int(tool_loop_limit),
        "default_max_lines": int(default_max_lines),
        "allowed_roots": roots,
    }


def _dispatch_tool_call(name: str, arguments: dict, *, settings: dict) -> tuple[str, str]:
    if name != "read_file":
        raise ValueError(f"Unknown tool: {name}")
    raw_path = arguments.get("path", "")
    ranges = arguments.get("ranges") or None
    max_lines = int(arguments.get("max_lines") or settings["default_max_lines"])

    p = Path(raw_path).expanduser().resolve()
    allowed_roots: list[Path] = settings["allowed_roots"]
    if not any(_is_within_root(p, root) for root in allowed_roots):
        raise ValueError(f"Path {p} is outside allowed roots: {allowed_roots}")

    # Check if path exists and is a file
    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")
    if not p.is_file():
        raise ValueError(
            f"Path is a directory, not a file: {p}. Use a specific file like 'src/amcp/readfile.py' instead of just 'src/amcp'."
        )

    rendered, llm = _attach_file_context(p, ranges, max_lines=max_lines)
    # content for model
    tool_text = f"READ_FILE OK\nPATH: {p}\n" + llm
    return tool_text, rendered


def _is_within_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except Exception:
        return False


def _build_mcp_tools_and_registry(
    cfg: AMCPConfig, chat_cfg: ChatConfig | None, servers_override: list[str] | None
) -> tuple[list[dict], dict]:
    # Decide which servers to include
    if chat_cfg and chat_cfg.mcp_tools_enabled is False:
        return [], {}
    selected = None
    if servers_override:
        selected = [s for s in servers_override if s in cfg.servers]
    elif chat_cfg and chat_cfg.mcp_servers:
        selected = [s for s in chat_cfg.mcp_servers if s in cfg.servers]
    else:
        selected = list(cfg.servers.keys())
    tools: list[dict] = []
    reg: dict[str, tuple[str, str]] = {}
    for name in selected:
        try:
            server = cfg.servers[name]
            info_list = _run_quietly(list_mcp_tools(server))
            for info in info_list:
                tname = info.get("name") or "tool"
                oname = f"mcp.{name}.{tname}"
                # Parameters: best effort; prefer server-provided schema when available
                params = info.get("inputSchema") or {"type": "object"}
                tools.append(
                    {
                        "type": "function",
                        "function": {"name": oname, "description": info.get("description", ""), "parameters": params},
                    }
                )
                reg[oname] = (name, tname)
        except Exception as e:
            console.print(f"[yellow]MCP tool discovery failed for server {name}:[/yellow] {e}")
    return tools, reg


def _chat_with_tools(
    client,
    model: str,
    base_messages: list[dict],
    stream: bool,
    settings_override: dict | None = None,
    *,
    extra_tools: list[dict] | None = None,
    tool_registry: dict | None = None,
) -> str:
    messages = list(base_messages)
    used_tools = False
    settings = _get_chat_runtime_settings(settings_override)
    max_steps = settings["tool_loop_limit"]
    tools = [_builtin_read_tool_spec()]
    if extra_tools:
        tools.extend(extra_tools)
    registry = tool_registry or {}
    read_file_call_count = 0
    for _step in range(max_steps):  # safety loop
        # print(f"DEBUG: Step {step + 1}/{max_steps}, messages count: {len(messages)}")
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            stream=False,
        )
        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None)
        # print(f"DEBUG: Tool calls: {bool(tool_calls)}, Content: {msg.content[:50] if msg.content else 'None'}")
        if tool_calls:
            used_tools = True
            # print(f"DEBUG: Processing {len(tool_calls)} tool calls")
            for _, tc in enumerate(tool_calls):
                # print(f"DEBUG: Tool call {i+1}: {tc.function.name}, args: {tc.function.arguments}")
                if tc.function.name == "read_file":
                    read_file_call_count += 1
                    if read_file_call_count >= 2:
                        # Force the model to respond by adding a system message
                        messages.append(
                            {
                                "role": "system",
                                "content": "You have already read the file content. Please analyze the information you have and provide your response without calling the read_file tool again.",
                            }
                        )
                        break
            # append assistant message with tool calls
            assistant_msg = {"role": "assistant", "content": msg.content or "", "tool_calls": []}
            for tc in tool_calls:
                fn = tc.function
                args = {}
                with contextlib.suppress(Exception):
                    args = json.loads(fn.arguments or "{}")
                assistant_msg["tool_calls"].append(
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": fn.name, "arguments": fn.arguments or "{}"},
                    }
                )
                try:
                    if fn.name.startswith("mcp.") and registry:
                        server_name, inner_name = registry.get(fn.name, (None, None))
                        if not server_name:
                            raise ValueError("Unknown MCP tool")
                        server = cfg_global.servers.get(server_name)  # defined below
                        if not server:
                            raise ValueError(f"Unknown MCP server: {server_name}")
                        # Normalize arguments for known tools (robust against model variants)
                        if server_name == "exa" and inner_name == "web_search_exa":
                            args = _normalize_exa_web_search_args(args)
                        # Call MCP tool quietly to suppress server startup logs
                        mcp_resp = _run_quietly(call_mcp_tool(server, inner_name, args))
                        # Build text for model
                        parts = []
                        sc = mcp_resp.get("structuredContent")
                        if sc is not None:
                            parts.append("STRUCTURED:\n" + json.dumps(sc, ensure_ascii=False))
                        for c in mcp_resp.get("content", []) or []:
                            if c.get("type") == "text":
                                parts.append(c.get("text", ""))
                        tool_result_text = ("\n\n".join(parts)) or json.dumps(mcp_resp, ensure_ascii=False)
                        preview = ("\n".join(parts[:1])) if parts else "(no text content)"
                        console.print(Panel(preview, title=f"tool: {fn.name}", border_style="blue"))
                    else:
                        tool_result_text, preview = _dispatch_tool_call(fn.name, args, settings=settings)
                        # print(f"DEBUG: Tool {fn.name} result preview: {preview[:100]}...")
                except Exception as e:
                    tool_result_text = f"TOOL_ERROR: {fn.name}: {type(e).__name__}: {e}"
                    console.print(f"[red]Tool {fn.name} error:[/red] {e}")
                    # Add more specific error info for TaskGroup issues
                    if "TaskGroup" in str(e) and "exa" in fn.name:
                        console.print(
                            "[yellow]Hint: Exa MCP server may be experiencing connectivity issues. Try rephrasing your request or using local tools instead.[/yellow]"
                        )
                # append tool result
                messages.append(assistant_msg)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": fn.name,
                        "content": tool_result_text,
                    }
                )
            continue  # back to the loop
        else:
            final_text = msg.content or ""
            if stream and not used_tools:
                # stream only when no tool phases were needed
                return _stream_chat(client, model, messages, stream=True)
            # Debug: print what we got
            # print(f"DEBUG: Final response: {final_text[:100]}...")
            return final_text
    return "[Tool loop limit reached]"


def _normalize_exa_web_search_args(args: dict) -> dict:
    out = dict(args or {})
    # Map possible synonyms
    if "query" not in out:
        for k in ("q", "query_text", "search", "text"):
            if k in out and isinstance(out[k], str):
                out["query"] = out.pop(k)
                break
    if "numResults" not in out:
        if "num_results" in out:
            out["numResults"] = out.pop("num_results")
        elif "limit" in out:
            out["numResults"] = out.pop("limit")
        else:
            out["numResults"] = 4
    if "type" not in out:
        out["type"] = "fast"
    return out


def do_exa_search(server_name: str, query: str, num_results: int = 4) -> str:
    cfg: AMCPConfig = load_config()
    if server_name not in cfg.servers:
        raise RuntimeError(f"Unknown MCP server '{server_name}'. Use 'amcp mcp tools -s ...' to verify.")
    result = console.status("Calling MCP web_search_exa...")
    with result:
        resp = __import__("asyncio").run(
            call_mcp_tool(
                cfg.servers[server_name],
                "web_search_exa",
                {
                    "query": query,
                    "numResults": num_results,
                    "type": "fast",
                },
            )
        )
    # Render
    out_lines = [f"MCP search results for: {query}"]
    for block in resp.get("content", []):
        if block.get("type") == "text":
            out_lines.append(block.get("text", ""))
    return "\n".join(out_lines)


# Global cfg snapshot for MCP dispatch
cfg_global: AMCPConfig = load_config()


def chat_once(
    model: str | None,
    user_text: str,
    base_url: str | None = None,
    system_prompt: str | None = None,
    mcp_server: str = "exa",
    stream: bool = True,
    api_key: str | None = None,
    work_dir: Path | None = None,
    mcp_servers_override: list[str] | None = None,
    mcp_tools_enabled: bool | None = None,
) -> str:
    cfg: AMCPConfig = load_config()
    chat_cfg = cfg.chat
    base = _resolve_base_url(base_url, chat_cfg)
    resolved_model = (
        model
        or (chat_cfg.model if chat_cfg and chat_cfg.model else None)
        or os.environ.get("AMCP_CHAT_MODEL")
        or "DeepSeek-V3.1-Terminus"
    )
    key = _resolve_api_key(api_key, chat_cfg)
    client = _make_client(base, key)
    messages: list[dict] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_text})
    overrides = {"read_roots": [str(work_dir.resolve())]} if work_dir else None

    # Build MCP tools
    extra_tools = []
    registry = {}
    enabled = True

    # Check if MCP tools are disabled in config
    if hasattr(chat_cfg, "mcp_tools_enabled") and chat_cfg and chat_cfg.mcp_tools_enabled is False:
        enabled = False

    # Override with command line flag
    if mcp_tools_enabled is not None:
        enabled = bool(mcp_tools_enabled)

    if enabled:
        extra_tools, registry = _build_mcp_tools_and_registry(cfg, chat_cfg, mcp_servers_override)

    return _chat_with_tools(
        client,
        resolved_model,
        messages,
        stream=stream,
        settings_override=overrides,
        extra_tools=extra_tools,
        tool_registry=registry,
    )


def chat_repl(
    model: str | None,
    base_url: str | None = None,
    system_prompt: str | None = None,
    mcp_server: str = "exa",
    stream: bool = True,
    api_key: str | None = None,
    work_dir: Path | None = None,
    mcp_servers_override: list[str] | None = None,
    mcp_tools_enabled: bool | None = None,
) -> None:
    cfg: AMCPConfig = load_config()
    chat_cfg = cfg.chat
    base = _resolve_base_url(base_url, chat_cfg)
    resolved_model = (
        model
        or (chat_cfg.model if chat_cfg and chat_cfg.model else None)
        or os.environ.get("AMCP_CHAT_MODEL")
        or "DeepSeek-V3.1-Terminus"
    )
    key = _resolve_api_key(api_key, chat_cfg)
    client = _make_client(base, key)

    overrides = {"read_roots": [str(work_dir.resolve())]} if work_dir else None
    settings = _get_chat_runtime_settings(overrides)
    roots_str = "\n".join(f"- {r}" for r in settings["allowed_roots"])
    # Build MCP tool exposure summary
    cfg = load_config()
    chat_cfg = cfg.chat
    enabled = True
    if hasattr(chat_cfg, "mcp_tools_enabled") and chat_cfg and chat_cfg.mcp_tools_enabled is False:
        enabled = False
    if mcp_tools_enabled is not None:
        enabled = bool(mcp_tools_enabled)
    extra_tools = []
    registry = {}
    if enabled:
        extra_tools, registry = _build_mcp_tools_and_registry(cfg, chat_cfg, mcp_servers_override)
    enabled_servers = sorted(set(name.split(".")[1] for name in registry)) if registry else []
    mcp_line = f"MCP tools: {'on' if extra_tools else 'off'}; servers: {', '.join(enabled_servers) if enabled_servers else '-'}"
    console.print(
        Panel(
            f"Chat model: [bold]{resolved_model}[/bold]\n"
            f"Base: {base}\n"
            f"Tool loop limit: {settings['tool_loop_limit']}\n"
            f"Default max lines: {settings['default_max_lines']}\n"
            f"Allowed read roots:\n{roots_str}\n"
            f"{mcp_line}\n\n"
            f"Commands: /read <path> [lines A-B], /search <q>, /quit",
            title="amcp chat",
            border_style="green",
        )
    )

    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    while True:
        try:
            console.print("[bold]You[/bold]: ", end="", style="yellow")
            text = input()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Bye.[/dim]")
            return

        if not text.strip():
            continue
        if text.strip() in {"/quit", ":q"}:
            console.print("[dim]Bye.[/dim]")
            return
        if text.startswith("/read "):
            # Try parse and attach, but do NOT send to model yet unless more content exists
            try:
                intents = _parse_read_intent(text)
                if intents:
                    for p, ranges in intents:
                        if not p.is_absolute():
                            p = Path.cwd() / p
                        if p.is_file():
                            console.print(Panel(f"Attaching file context: {p}", border_style="blue"))
                            rendered, llm = _attach_file_context(p, ranges)
                            console.print(rendered)
                            messages.append({"role": "system", "content": f"File context:\n{llm}"})
                        else:
                            console.print(f"[red]File not found:[/red] {p}")
                    # If the input was purely a read request, continue to next prompt
                    if _READ_CMD.match(text) or _PATH_RANGE_INLINE.fullmatch(text.strip()):
                        continue
            except Exception as e:
                console.print(f"[yellow]File intent parse/read warning:[/yellow] {e}")

        if text.startswith("/search "):
            q = text[len("/search ") :].strip()
            try:
                result = do_exa_search(mcp_server, q)
                console.print(Panel(Markdown(result), title="exa search", border_style="magenta"))
            except Exception as e:
                console.print(f"[red]MCP search error:[/red] {e}")
            continue

        messages.append({"role": "user", "content": text})
        try:
            extra_tools, registry = _build_mcp_tools_and_registry(load_config(), load_config().chat, None)
            reply = _chat_with_tools(
                client,
                resolved_model,
                messages,
                stream=stream,
                settings_override=overrides,
                extra_tools=extra_tools,
                tool_registry=registry,
            )
            messages.append({"role": "assistant", "content": reply})
        except Exception as e:
            console.print(f"[red]Chat error:[/red] {e}")
