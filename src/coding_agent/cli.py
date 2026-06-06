from __future__ import annotations

"""
coding_agent CLI入口。
解析命令行参数、创建 AgentSession、把 session 交给 runner.run() 按不同模式运行。

示例：
python -m coding_agent --mode print --prompt "你好"
python -m coding_agent --mode interactive --provider openai-standard --model-id deepseek-v4-pro
"""

import argparse
import asyncio
import json
from pathlib import Path
from typing import Sequence

# 项目内部导入
from .factory import create_agent_session
from .runner import RunOptions, run
from .types import CreateAgentSessionOptions


def build_parser() -> argparse.ArgumentParser:
    """ 创建 ArgumentParser，并注册所有 CLI 参数 """
    parser = argparse.ArgumentParser(description="XingClaw coding-agent CLI")
    # 运行模式
    parser.add_argument("--mode", choices=["print", "interactive", "rpc"], default="interactive")
    # 工作目录
    parser.add_argument("--workspace", default=".", help="Workspace directory")
    # session_id
    parser.add_argument("--session-id", default=None, help="Existing session id to resume")
    
    # session树相关参数：列出历史节点、查看树、从某个 entry 分叉、切换当前叶子节点。
    parser.add_argument("--list-entries", action="store_true", help="Print session entry ids and exit")
    parser.add_argument("--show-tree", action="store_true", help="Print session tree as JSON and exit")
    parser.add_argument("--fork-entry", default=None, help="Fork from entry id and print new session id")
    parser.add_argument("--switch-entry", default=None, help="Switch current session leaf to entry id")
    
    # 模型提供商
    parser.add_argument("--provider", default=None, help="Model provider, e.g. anthropic/openai-standard")
    # 模型ID
    parser.add_argument("--model-id", default=None, help="Model id")
    # 系统提示词
    parser.add_argument("--system-prompt", default="", help="System prompt")
    # 思考层级
    parser.add_argument("--thinking-level", default="off", help="Thinking level: off/minimal/low/medium/high/xhigh")
    # 工具调用模式：parallel（默认）或 sequential
    parser.add_argument("--tool-execution", choices=["parallel", "sequential"], default="parallel")
    
    # 上下文压缩相关参数：压缩触发的消息数量 或 token 数量阈值，压缩时保留的最近消息数量。
    parser.add_argument("--max-context-messages", type=int, default=None, help="Compaction message threshold")
    parser.add_argument("--max-context-tokens", type=int, default=None, help="Compaction token threshold (approx)")
    parser.add_argument("--retain-recent-messages", type=int, default=24, help="Keep recent messages when compacting")
   
   
    parser.add_argument("--no-retry", action="store_true", help="Disable automatic retry on transient errors")
    parser.add_argument("--max-retries", type=int, default=2, help="Maximum retry count")
    parser.add_argument("--retry-base-delay-ms", type=int, default=1200, help="Retry base delay in milliseconds")
    parser.add_argument("--read-only", action="store_true", help="Enable read-only mode (disable write/edit/bash)")
    parser.add_argument("--allow-dangerous-bash", action="store_true", help="Disable dangerous bash blocking")
    parser.add_argument(
        "--bash-allow-pattern",
        action="append",
        default=None,
        help="Regex pattern to allow bash command (can be repeated)",
    )
    parser.add_argument(
        "--bash-block-pattern",
        action="append",
        default=None,
        help="Regex pattern to block bash command (can be repeated)",
    )
    parser.add_argument(
        "--relaxed-edit",
        action="store_true",
        help="Disable strict unique-match requirement for edit tool",
    )
    # 提示词
    parser.add_argument("--prompt", default=None, help="Prompt text (required in print mode)")
    parser.add_argument("--no-tool-events", action="store_true", help="Hide tool events in output")
    parser.add_argument(
        "--disable-workspace-resources",
        action="store_true",
        help="Disable reading .xingclaw/{settings,prompt,tools}",
    )
    return parser


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
