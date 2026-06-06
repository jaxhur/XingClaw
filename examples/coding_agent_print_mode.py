"""
print 模式示例：传入一个 prompt，打印一次回答。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from coding_agent import CreateAgentSessionOptions, RunOptions, create_agent_session, run


async def main() -> None:
    # 创建会话
    session = create_agent_session(
        CreateAgentSessionOptions(
            workspace_dir=Path.cwd(), # 工作目录
            provider="openai-standard", # 模型提供商
            model_id="deepseek-v4-pro",
            system_prompt="你是一个简洁可靠的助手。",
            thinking_level="minimal",
        )
    )
    try:
        # 发起对话：传入 prompt 和 run 配置项，等待结果。
        # run 内部会处理事件流，打印模型的流式输出和工具调用事件。
        await run(
            RunOptions(
                mode="print",
                session=session,
                prompt="请用一段话介绍 Python 的优势。",
            )
        )
    finally:
        session.close()


if __name__ == "__main__":
    asyncio.run(main())
