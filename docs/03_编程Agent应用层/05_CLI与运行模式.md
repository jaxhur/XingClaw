**CLI与三种运行模式**：`src/coding_agent/cli.py`、`src/coding_agent/runner.py`

- 单次对话 `--mode print`：进程启动 →问一句 → 打印结果 → 退出
- 交互式多轮对话模式`--mode interactive`：`you> ` 循环输入，内置 `/help`、`/session` 等
- RPC模式：不写人类终端 UI，而是 **stdin 一行一条 JSON**



示例：执行

```
python -m coding_agent --mode interactive --provider openai-standard --model-id deepseek-v4-pro
```

调用链路：

```
__main__.py
  -> cli.main()
    -> build_parser() 解析参数
    -> _run_from_args(args)
      -> CreateAgentSessionOptions(...)
      -> create_agent_session(options)
      -> run(RunOptions(...))
      -> run_print / run_interactive / run_rpc
```



# cli.py

`cli.py`：argparse解析命令行参数并包装成`CreateAgentSessionOptions`，建好 `AgentSession`，交给 `runner.run`根据 `--mode` 按不同模式运行；`runner.py` 是三种运行方式的具体实现。

```python
def main(argv: Sequence[str] | None = None) -> int:
    # 构建参数解析器并解析参数
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return asyncio.run(_run_from_args(args))
    except ValueError as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

```

关键参数

- `--mode` ：`print` | `interactive` | `rpc`，默认interactive
- 工作区、会话、模型、工具执行方式等与会话构造相关；另有压缩/重试、只读、bash 策略等开关。

```python
def build_parser() -> argparse.ArgumentParser:
    """ 创建 ArgumentParser，并注册所有 CLI 参数 """
    parser = argparse.ArgumentParser(description="XingClaw coding-agent CLI")
    parser.add_argument("--mode", choices=["print", "interactive", "rpc"], default="interactive")
    parser.add_argument("--workspace", default=".", help="Workspace directory")
    parser.add_argument("--session-id", default=None, help="Existing session id to resume")
    parser.add_argument("--provider", default=None, help="Model provider, e.g. anthropic/openai-standard")
    parser.add_argument("--model-id", default=None, help="Model id")
    parser.add_argument("--thinking-level", default="off", help="Thinking level: off/minimal/low/medium/high/xhigh")
    parser.add_argument("--tool-execution", choices=["parallel", "sequential"], default="parallel")
    parser.add_argument("--max-context-messages", type=int, default=None, help="Compaction message threshold")
    parser.add_argument("--max-context-tokens", type=int, default=None, help="Compaction token threshold (approx)")
    parser.add_argument("--prompt", default=None, help="Prompt text (required in print mode)")
    # ... --list-entries, --show-tree, --fork-entry, --switch-entry, --no-retry 等
    return parser
```

`_run_from_args` 里若带 `--switch-entry` / `--fork-entry` / `--list-entries` / `--show-tree`，会**先处理并 `return`**，不会进入 `run()`；否则组装 `RunOptions` 调用 `run(...)`。

- **session 是一棵消息树，entry 是树上的一个“消息节点”，leaf 是当前选中的最后一个节点**。
  - session.get_leaf_id() 读取.xingclaw/sessions/<session_id>/meta.json 里的 leaf_id，新 session 初始化时 leaf_id 是 None，；每次保存一条 message，都会创建一个新的 entry，并把 meta["leaf_id"] 更新成这个 entry 的 id
  - entry 之间靠 parent_id 连起来。get_entry_path(entry_id) 会从某个 entry 往父节点一路追溯，再反转，得到“从根到当前节点”的分支路径
  - switch_to_entry() 本质就是把当前 leaf 切到某个历史 entry，然后按这条路径恢复消息上下文

```python
async def _run_from_args(args: argparse.Namespace) -> int:
    """ 把参数变成 session 并执行 """
    # 根据命令行参数创建SessionOptions，然后创建Session传给工厂函数创建 session
    options = CreateAgentSessionOptions(
        workspace_dir=Path(args.workspace),
        provider=args.provider,
        model_id=args.model_id,
        system_prompt=args.system_prompt,
        session_id=args.session_id,
        thinking_level=args.thinking_level,
        tool_execution=args.tool_execution,
        max_context_messages=args.max_context_messages,
        max_context_tokens=args.max_context_tokens,
        retain_recent_messages=args.retain_recent_messages,
        retry_enabled=not bool(args.no_retry),
        max_retries=args.max_retries,
        retry_base_delay_ms=args.retry_base_delay_ms,
        read_only_mode=bool(args.read_only),
        block_dangerous_bash=not bool(args.allow_dangerous_bash),
        bash_allow_patterns=args.bash_allow_pattern,
        bash_block_patterns=args.bash_block_pattern,
        edit_require_unique_match=not bool(args.relaxed_edit),
        load_workspace_resources=not bool(args.disable_workspace_resources),
    )
    session = create_agent_session(options)


    try:
        # 会话管理命令（只操作会话，不跑模型）：切换节点、分叉节点、列出节点、显示树结构
        # 这些分支都会 return 0，表示命令执行成功且不再进入对话模式
        
        # 切换当前 session 的叶子节点，然后输出 JSON
        if args.switch_entry:
            session.switch_to_entry(str(args.switch_entry))
            print(json.dumps({"type": "switch_entry", 
                              "session_id": session.session_id, 
                              "entry_id": args.switch_entry}))
            return 0
        # 从某个 entry 创建新会话分支，输出新 session id。
        if args.fork_entry:
            forked = session.fork_from_entry(str(args.fork_entry))
            try:
                print(
                    json.dumps(
                        {
                            "type": "forked",
                            "from_session_id": session.session_id,
                            "from_entry_id": args.fork_entry,
                            "new_session_id": forked.session_id,
                        },
                        ensure_ascii=False,
                    )
                )
            finally:
                forked.close()
            return 0
        # 列出当前 session 的 entry id。
        if args.list_entries:
            print(json.dumps({"session_id": session.session_id, "entry_ids": session.list_entry_ids()}, ensure_ascii=False))
            return 0
        # 输出完整 session tree。
        if args.show_tree:
            print(json.dumps({"session_id": session.session_id, "tree": session.get_session_tree()}, ensure_ascii=False))
            return 0

        
        # 真正运行Agent
        await run(
            # CLI 解析结果包装成 RunOptions
            RunOptions(
                mode=args.mode,
                session=session,
                prompt=args.prompt,
                show_tool_events=not bool(args.no_tool_events),
            )
        )
    finally:
        session.close()
    return 0
```



# runner.py

`run()`：统一运行入口，根据 options.mode 转发到不同的运行模式。

```python
async def run(options: RunOptions) -> AssistantMessage | None:
    """
    统一运行入口，根据 options.mode 转发到不同的运行模式。
    """
    # print模式
    if options.mode == "print":
        if not options.prompt:
            raise ValueError("print mode requires prompt")
        return await run_print(
            options.session,
            options.prompt,
            output=options.output,
            show_tool_events=options.show_tool_events,
        )
    # rpc模式
    if options.mode == "rpc":
        await run_rpc(options.session, output=options.output)
        return None
    # 交互模式
    await run_interactive(
        options.session,
        input_fn=options.input_fn,
        output=options.output,
        show_tool_events=options.show_tool_events,
        exit_commands=options.exit_commands,
    )
    return None
```

## print模式

`run_print()`

- 订阅 `AgentEvent`
- 把 `message_update` 里的 `text_delta` 拼起来，最后若没有 delta 则输出最终 assistant 文本，并打印 `stop_reason` / `error_message`。

```python
async def run_print(
    session: AgentSession,
    prompt: str,
    *, 
    output: OutputFn = print, # 输出函数是print
    show_tool_events: bool = True,
) -> AssistantMessage | None:
    """
    单次问答模式
    python -m coding_agent --mode print --prompt "帮我解释这个项目"
    """
    # 收集文本增量delta
    deltas: list[str] = []

    # 内部的事件监听器
    def on_event(event: AgentEvent) -> None:
        t = event["type"]
        # 工具执行开始\结束
        if show_tool_events and t in {"tool_execution_start", "tool_execution_end"}:
            output(f"[tool-event] {t}: {event.get('toolName', '')}")
            return
        # 模型流式输出更新
        if t == "message_update":
            assistant_event = event.get("assistantMessageEvent") or {}
            # 只处理文本增量事件，其他事件（如工具调用结果）不处理
            if assistant_event.get("type") == "text_delta":
                delta = str(assistant_event.get("delta", ""))
                deltas.append(delta)
    # session订阅事件
    unsubscribe = session.subscribe(on_event)
    try:
        # session.prompt会处理生命周期 hook、上下文压缩、重试、真正调用 agent。
        await session.prompt(prompt)
    finally:
        # 取消订阅
        unsubscribe()

    # 从历史消息倒序找最后一条 assistant 消息
    final_assistant = next((m for m in reversed(session.messages) 
                            if isinstance(m, AssistantMessage)), None)

    # 如果运行时收集到了流式 delta，就输出 delta 拼接结果
    if deltas:
        output("".join(deltas).strip())
    # 如果没有 delta，就从最终 assistant 消息中提取文本输出
    elif final_assistant is not None:
        output(_extract_assistant_text(final_assistant) or "(empty)")

    if final_assistant is not None:
        output(f"[assistant.stop_reason] {final_assistant.stop_reason}")
        output(f"[assistant.error_message] {final_assistant.error_message}")
    return final_assistant

```

## 交互模式

`run_interactive`：

- 内置命令：`/help`、`/session`、`/tree`、`/clear`、`/new` 与 `/fork`、`/switch <entry_id>`；
- 未命中时，`resolve_registered_command` 走**扩展命令**。

```python
async def run_interactive(
    session: AgentSession,
    *,
    input_fn: InputFn = input,
    output: OutputFn = print,
    show_tool_events: bool = True,
    exit_commands: tuple[str, ...] = ("exit", "quit", ":q"),
) -> None:
    """
    交互模式：复用run_print()
        持续读取输入，处理输入（命令、提示词），直到输入退出命令。
    python -m coding_agent
    """
    # 打印出交互模式下支持的命令
    output("Entering interactive mode. Type 'exit' or '/exit' to quit.")
    output(format_commands_for_help(session)) # 列出可用命令
    current_session = session

    # 循环，持续读取用户输入
    while True:
        # 读取输入,开头是you>，取出前后空格
        text = input_fn("you> ").strip()
        # 去掉开头的斜杠，得到"裸"命令（exit 和 /exit 都能退出）
        bare = text.lstrip("/")

        # 退出命令exit/quit/:q
        if bare in exit_commands:
            output("Bye.")
            return
        # 空输入就继续循环
        if not text:
            continue
        # 如果输入以斜杠开头，尝试解析为命令并执行
        if text.startswith("/"):
            handled, switched = await _handle_interactive_command(current_session, text, output=output)
            # 如果命令执行后返回了新的 session（如切换节点、分叉节点等），就切换到新 session
            if switched is not None:
                current_session.close()
                current_session = switched
            # 命令已被处理则跳到下一个循环
            if handled:
                continue
        # 不是特殊命令，作为普通prompt发送给agent
        await run_print(current_session, text, output=output, show_tool_events=show_tool_events)


async def _handle_interactive_command(
    session: AgentSession, text: str, *, output: OutputFn = print
) -> tuple[bool, AgentSession | None]:
    """ 处理斜杠命令 
    handled: 这个命令是否被处理了
    switched: 是否需要切换到一个新的 session
    支持命令：
        /help
        /session
        /tree
        /clear
        /new
        /fork
        /switch
    """

    cmd, _, rest = text.partition(" ") #  输入按第一个空格切分，cmd 是命令（例如 /help）
    arg = rest.strip() # 命令参数（去掉多余空白）
    # /help: 输出帮助文本
    if cmd == "/help":
        output(format_commands_for_help(session))
        return True, None
    # /session: 输出当前 session id 和叶子节点 id
    if cmd == "/session":
        output(f"session_id={session.session_id} leaf_id={session.get_leaf_id()}")
        return True, None
    # /tree: 输出当前会话树的文本表示
    if cmd == "/tree":
        entries = session.list_entries()
        if not entries:
            output("(empty)")
            return True, None
        for item in entries:
            depth = int(item.get("depth", 0))
            prefix = "  " * max(depth, 0)
            leaf_mark = " *" if item.get("is_leaf") else ""
            output(f"{prefix}- {item.get('id')}{leaf_mark}")
        return True, None
    # /clear: 清除当前上下文，创建新的 session
    if cmd == "/clear":
        fresh = _create_fresh_session(session)
        output(f"context cleared → new session_id={fresh.session_id}")
        return True, fresh
    # 从指定 entry 分叉一个新 session。如果没有参数，就从当前 leaf 分叉
    if cmd in {"/new", "/fork"}:
        from_entry = arg or session.get_leaf_id() or ""
        if not from_entry:
            output("cannot resolve source entry")
            return True, None
        forked = session.fork_from_entry(from_entry)
        output(f"forked to session_id={forked.session_id}")
        return True, forked
    # /switch: 切换到指定的 entry
    if cmd == "/switch":
        if not arg:
            output("usage: /switch <entry_id>")
            return True, None
        session.switch_to_entry(arg)
        output(f"switched leaf -> {session.get_leaf_id()}")
        return True, None

    # 如果不是内置命令，就去 session.extension_commands 找扩展注册的命令
    reg = resolve_registered_command(session, cmd)
    if reg:
        value = reg.handler(
            ExtensionCommandContext(
                name=reg.name,
                args=[p for p in arg.split(" ") if p],
                raw_text=text,
                session=session,
                message=None,
            )
        )
        if inspect.isawaitable(value):
            value = await value
        if value:
            output(str(value))
        return True, None
    return False, None


def _create_fresh_session(old: AgentSession) -> AgentSession:
    """ 执行/clear命令，用旧 session 的配置创建一个新 session"""
    from .session_store import new_session_id
    from .types import AgentSessionOptions

    return AgentSession(
        AgentSessionOptions(
            model=old.agent.state.model,
            workspace_dir=old.workspace_dir,
            system_prompt=old.agent.state.system_prompt,
            tools=list(old.agent.state.tools),
            session_id=new_session_id(),
            messages=[],
            thinking_level=old.agent.state.thinking_level,
            tool_execution=old.tool_execution,
            max_context_messages=old.max_context_messages,
            max_context_tokens=old.max_context_tokens,
            retain_recent_messages=old.retain_recent_messages,
            summary_builder=old.summary_builder,
            retry_enabled=old.retry_enabled,
            max_retries=old.max_retries,
            retry_base_delay_ms=old.retry_base_delay_ms,
            mcp_servers=old.mcp_servers,
            mcp_client=old.mcp_client,
            extension_commands=old.extension_commands,
            before_prompt_hooks=old.before_prompt_hooks,
            after_prompt_hooks=old.after_prompt_hooks,
            before_tool_call=old.before_tool_call,
            after_tool_call=old.after_tool_call,
        )
    )

```



## RPC模式|JSONL请求类型与响应形状

`run_rpc()`：进程启动后，先打印一行 **`rpc_ready`**（含 `session_id`、`protocol_version`）。随后每行 stdin 为 JSON 对象，字段 **`type`** 表示命令；可选 **`id`** 用于与 `response` 关联。

**RPC 命令详解**

| type | 含义 |
|------|------|
| `prompt` | `text` 字段，调用 `session.prompt` |
| `continue` | `session.continue_run()` |
| `state` | 返回 message_count、entry_ids、leaf_id 等 |
| `list_entries` | 条目列表与 id |
| `show_tree` | 会话树 JSON |
| `fork_entry` | 需要 `entry_id`，fork 后返回 `new_session_id`（fork 的 session 会 close） |
| `switch_entry` | 需要 `entry_id`，切换叶子并返回 path 等 |
| `get_commands` | 运行时命令列表（含扩展） |
| `shutdown` | 正常结束 RPC 循环 |

另：**`entry_path`** 需 `entry_id`，返回从根到该 entry 的路径（源码中有实现，IDE 常用）。

订阅 `session` 的事件会通过 **`{"type": "event", "event": ...}`** 实时写出（与单次请求的 `response` 不同）。

**成功响应**：

```json
{"type": "response", "id": "<可选>", "command": "prompt", "status": "ok", "data": { ... }}
```

**错误响应**：

```json
{"type": "response", "id": null, "command": null, "status": "error", "error": {"code": "invalid_json", "message": "..."}}
```



```python
async def run_rpc(
    session: AgentSession,
    *,
    output: OutputFn = print,
) -> None:
    """
    极简 RPC 模式：
     实现一个基于 JSONL（JSON Line）的远程过程调用（RPC）协议，
     允许外部程序通过标准输入（stdin）向 agent 发送 JSON 命令，
     并通过标准输出（stdout）接收 JSON 响应。
    - {"type":"prompt","text":"..."}
    - {"type":"continue"}
    - {"type":"state"}
    - {"type":"shutdown"}
    """

    def _json_default(value: Any) -> Any:
        """ JSON 序列化的自定义处理器 """
        # dataclass -> 字典
        if is_dataclass(value):
            return asdict(value)
        # set -> list
        if isinstance(value, set):
            return list(value)
        # 其他类型 -> 字符串
        return str(value)

    def _emit(obj: dict[str, Any]) -> None:
        """ 将 Python 字典序列化为 JSON 字符串并调用output方法输出 """
        output(json.dumps(obj, ensure_ascii=False, default=_json_default))

    def _emit_error(*, req_id: Any, command: Any, code: str, message: str) -> None:
        """ 输出错误响应 """
        _emit(
            {
                "type": "response",
                "id": req_id,
                "command": command,
                "status": "error",
                "error": {"code": code, "message": message},
            }
        )

    def _emit_ok(*, req_id: Any, command: str, data: dict[str, Any] | None = None) -> None:
        """ 输出成功响应 """
        payload: dict[str, Any] = {
            "type": "response",
            "id": req_id,
            "command": command,
            "status": "ok",
        }
        if data is not None:
            payload["data"] = data
        _emit(payload)

    # 订阅 session 事件，任何事件发生时都通过 _emit 输出 JSON
    unsubscribe = session.subscribe(
        lambda event: _emit(
            {
                "type": "event",
                "event": event,
            }
        )
    )
    # 向客户端发送"服务就绪"信号，告知 session_id 和协议版本
    _emit({"type": "rpc_ready", "session_id": session.session_id, "protocol_version": "1.2"})
    
    
    try:
        # 逐行读取、JSON 解析
        for raw in sys.stdin:
            line = raw.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except Exception as exc:
                _emit_error(req_id=None, command=None, code="invalid_json", message=f"Invalid JSON: {exc}")
                continue
            if not isinstance(req, dict):
                _emit_error(req_id=None, command=None, code="invalid_request", message="Request must be object")
                continue
            
            # 提取 cmd（"type"）和 req_id（"id"）
            cmd = req.get("type")
            req_id = req.get("id")

            # 多种命令处理
            try:
                if cmd == "prompt":
                    text = str(req.get("text", ""))
                    await session.prompt(text)
                    _emit_ok(req_id=req_id, command="prompt")
                elif cmd == "continue":
                    await session.continue_run()
                    _emit_ok(req_id=req_id, command="continue")
                elif cmd == "state":
                    _emit_ok(
                        req_id=req_id,
                        command="state",
                        data={
                            "session_id": session.session_id,
                            "message_count": len(session.messages),
                            "entry_ids": session.list_entry_ids(),
                            "leaf_id": session.get_leaf_id(),
                        },
                    )
                elif cmd == "list_entries":
                    _emit_ok(
                        req_id=req_id,
                        command="list_entries",
                        data={
                            "session_id": session.session_id,
                            "entry_ids": session.list_entry_ids(),
                            "entries": session.list_entries(),
                            "leaf_id": session.get_leaf_id(),
                        },
                    )
                elif cmd == "show_tree":
                    _emit_ok(
                        req_id=req_id,
                        command="show_tree",
                        data={
                            "session_id": session.session_id,
                            "tree": session.get_session_tree(),
                            "leaf_id": session.get_leaf_id(),
                        },
                    )
                elif cmd == "entry_path":
                    entry_id = str(req.get("entry_id", ""))
                    if not entry_id:
                        raise ValueError("entry_path requires entry_id")
                    _emit_ok(
                        req_id=req_id,
                        command="entry_path",
                        data={"session_id": session.session_id, "entry_id": entry_id, "path": session.get_entry_path(entry_id)},
                    )
                elif cmd == "fork_entry":
                    entry_id = str(req.get("entry_id", ""))
                    if not entry_id:
                        raise ValueError("fork_entry requires entry_id")
                    forked = session.fork_from_entry(entry_id)
                    try:
                        _emit_ok(
                            req_id=req_id,
                            command="fork_entry",
                            data={
                                "from_session_id": session.session_id,
                                "from_entry_id": entry_id,
                                "new_session_id": forked.session_id,
                            },
                        )
                    finally:
                        forked.close()
                elif cmd == "switch_entry":
                    entry_id = str(req.get("entry_id", ""))
                    if not entry_id:
                        raise ValueError("switch_entry requires entry_id")
                    session.switch_to_entry(entry_id)
                    _emit_ok(
                        req_id=req_id,
                        command="switch_entry",
                        data={
                            "session_id": session.session_id,
                            "entry_id": entry_id,
                            "path": session.get_entry_path(entry_id),
                        },
                    )
                elif cmd == "get_commands":
                    _emit_ok(
                        req_id=req_id,
                        command="get_commands",
                        data={
                            "session_id": session.session_id,
                            "commands": [
                                {"name": c.name, "description": c.description, "source": c.source}
                                for c in list_runtime_commands(session)
                            ],
                        },
                    )
                elif cmd == "shutdown":
                    _emit_ok(req_id=req_id, command="shutdown")
                    return
                else:
                    _emit_error(req_id=req_id, command=cmd, code="unknown_command", message="Unknown command")
            except Exception as exc:
                _emit_error(req_id=req_id, command=cmd, code="execution_error", message=str(exc))
    finally:
        unsubscribe()

```

