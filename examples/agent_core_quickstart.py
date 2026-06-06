"""
agent_core 最小示例：
1) 创建 Agent
2) 注册一个简单工具
3) 发起一次对话并打印事件

用户问“现在时间”
→ Agent 调用大模型
→ 大模型发现需要工具
→ Agent 执行 get_time 工具
→ 把工具结果交回大模型
→ 大模型生成最终回答
→ 程序打印事件和最终消息

工具调用链：
await agent.prompt(...)
→ Agent 调用大模型
→ 大模型返回一个 ToolCall：我要调用 get_time
→ agent_core 找到 name == "get_time" 的 AgentTool
→ 调用 tool.execute(...)
→ 实际执行 get_time_tool(...)
→ 把工具结果作为 ToolResultMessage 放回上下文
→ 再调用一次大模型生成最终回答
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from ai import AssistantMessage, TextContent, get_model
from agent_core import Agent, AgentOptions, AgentTool, AgentToolResult


async def get_time_tool(tool_call_id: str, params: dict, signal=None, on_update=None) -> AgentToolResult:
    """ 工具函数：获取当前时间 
    tool_call_id: 这次工具调用的唯一 ID。模型一次请求多个工具，每个工具调用需要 ID 和结果配对。
    params: 模型调用工具传入的参数
    signal: 取消信号
    on_update: 工具执行过程中的进度回调,工具执行过程中可以多次调用它来更新结果（如进度、分阶段结果等）。
    """
    _ = tool_call_id, signal
    # 工具参数
    timezone = params.get("timezone", "local")
    # 如果 Agent 给了进度回调，就发送一个中间状态：“正在查询时间...”。
    if on_update:
        on_update(AgentToolResult(content=[TextContent(text="正在查询时间...")],
                                   details={"stage": "start"}))
    # 获取当前时间
    now = datetime.now().isoformat(timespec="seconds")
    # 返回 AgentToolResult，给模型看的工具结果文本content、给日志、UI 或调试用的额外信息details
    return AgentToolResult(content=[TextContent(text=f"当前时间({timezone}): {now}")], 
                           details={"timezone": timezone})


async def main() -> None:
    # 模型：通过统一模型注册层获取模型。
    model = get_model("openai-standard", "deepseek-v4-pro")
    # 工具
    # 真正调用 get_time_tool 的是Agent 框架里的工具执行循环，不是 on_event
    tool = AgentTool(
        name="get_time",
        label="Get Time",
        description="获取当前时间",
        # JSON Schema 格式的参数定义
        parameters={
            "type": "object",
            "properties": {"timezone": {"type": "string",  
                                        "description": "时区描述，如 Asia/Shanghai"}},
            "required": [],
            "additionalProperties": False,
        },
        execute=get_time_tool,
    )
    # 创建Agent
    agent = Agent(
        # 使用AgentOptions配置
        AgentOptions(
            model=model,
            system_prompt="你是一个简洁的助手。需要时间时请调用 get_time 工具。",
            tools=[tool],
            thinking_level="minimal",
        )
    )

    def on_event(event: dict) -> None:
        """ 事件监听器（事件回调函数），监听 Agent 运行过程中的事件
        注册之后，Agent 内部每次发事件，都会通知 on_event(event)
        """
        # 获取事件类型
        event_type = event.get("type")
        # 工具开始或结束
        if event_type in {"tool_execution_start", "tool_execution_end"}:
            print(f"[tool-event] {event_type}: {event.get('toolName')}")
            return
        # 消息流式更新：处理模型流式输出的文本增量text_delta
        if event_type == "message_update":
            assistant_event = event.get("assistantMessageEvent") or {}
            if assistant_event.get("type") == "text_delta":
                # flush=True 表示立刻刷新终端，让你看到实时输出。
                print(assistant_event.get("delta", ""), end="", flush=True)
            return
        # Assistant消息结束
        if event_type == "message_end":
            message = event.get("message")
            if getattr(message, "role", "") == "assistant":
                print()
    # 订阅事件：把 on_event 注册给 Agent；之后 Agent 内部每次调用 _dispatch_event，都会通知这个函数
    agent.subscribe(on_event)

    # 发起对话
    await agent.prompt("请告诉我现在时间，并说明你使用了哪个工具。")

    # 无论是否出现 text_delta，都打印最终 assistant 结果，方便排查问题。
    final_assistant = next(
        (m for m in reversed(agent.state.messages) if isinstance(m, AssistantMessage)),
        None,
    )
    # 打印最终结果：停用原因、错误信息、文本内容等
    if final_assistant is not None:
        text_blocks = [b.text for b in final_assistant.content if isinstance(b, TextContent)]
        final_text = "".join(text_blocks).strip()
        print(f"[assistant.stop_reason] {final_assistant.stop_reason}")
        print(f"[assistant.error_message] {final_assistant.error_message}")
        print(f"[assistant.text] {final_text if final_text else '(empty)'}")

    print("---- 对话结束 ----")
    for m in agent.state.messages:
        role = getattr(m, "role", "unknown")
        print(f"- {role}")


if __name__ == "__main__":
    asyncio.run(main())
