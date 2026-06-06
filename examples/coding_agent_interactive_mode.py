"""
interactive 模式示例：启动一个简易对话 REPL。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from coding_agent import CreateAgentSessionOptions, RunOptions, create_agent_session, run


async def main() -> None:
    # 创建会话
    session = create_agent_session(
        CreateAgentSessionOptions(
            workspace_dir=Path.cwd(),
            provider="openai-standard",
            model_id="deepseek-v4-pro",
            system_prompt="你是一个简洁可靠的助手。",
            thinking_level="minimal",
        )
    )
    try:
        # 没有传prompt，只传session
        await run(
            RunOptions(
                mode="interactive",
                session=session,
            )
        )
    finally:
        session.close()


if __name__ == "__main__":
    asyncio.run(main())
