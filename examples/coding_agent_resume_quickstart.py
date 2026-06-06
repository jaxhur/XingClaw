"""
会话恢复示例：
1) 第一次创建会话并提问；
2) 用同一个 session_id 重建会话对象；
3) 继续提问并验证历史仍在。
"""

from __future__ import annotations

import asyncio
from ai import AssistantMessage, TextContent
from pathlib import Path

from coding_agent import CreateAgentSessionOptions, create_agent_session

def print_last_assistant(session, label: str) -> None:
    """ 打印 session 中最后一个 AssistantMessage """
    final = next((m for m in reversed(session.messages) if isinstance(m, AssistantMessage)), None)
    if final is None:
        print(label, "(no assistant message)")
        return

    text = "".join(
        b.text for b in final.content if isinstance(b, TextContent)
    ).strip()

    print(label, text if text else "(empty)")

async def main() -> None:
    # 第一次，创建 session
    first = create_agent_session(
        CreateAgentSessionOptions(
            workspace_dir=Path.cwd(),
            provider="openai-standard",
            model_id="deepseek-v4-pro",
            system_prompt="你是一个会话型助手。",
            thinking_level="minimal",
        )
    )
    await first.prompt("请记住：我的名字叫【丁真珍珠】")
    print_last_assistant(first, "[first.assistant]")
    # session_id
    sid = first.session_id
    print("[first.session_id]", sid)
    print("[first.message_count]", len(first.messages))
    first.close()

    # 第二次，用 session_id 恢复历史
    second = create_agent_session(
        CreateAgentSessionOptions(
            workspace_dir=Path.cwd(),
            session_id=sid,  
            thinking_level="minimal",
        )
    )
    print("[second.message_count.before]", len(second.messages))
    await second.prompt("我的名字叫什么")
    print_last_assistant(second, "[second.assistant]")
    print("[second.message_count.after]", len(second.messages))
    second.close()


if __name__ == "__main__":
    asyncio.run(main())
