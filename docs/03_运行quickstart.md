# quickstart.py

## 代码

`quickstart.py`：演示**最小对话流程**；**测试底层的ai统一接口**，演示get_model()、Context、stream_simple()、流式输出text_delta 。不是Agent，更多用于理解模型调用和流式响应。

- 选模型
- 准备上下文
- 请求模型，流式返回，逐步消费文本增量text_delta
- 拿最终消息

```python
import asyncio
import time

# 示例脚本：演示最小对话流程
# 1) 选模型
# 2) 准备上下文
# 3) 逐步消费 文本增量 text_delta
# 4) 拿最终消息
from ai import Context, TextContent, Tool, UserMessage, get_model, stream_simple


async def main() -> None:
    # 1) 选模型
    # model = get_model("anthropic", "glm-4.7")
    model = get_model("openai-standard", "deepseek-v4-pro")

    # 2) 准备上下文：系统提示 + 用户消息 + 可选工具
    context = Context(
        # 系统提示
        system_prompt="You are a helpful assistant.",
        # 用户消息
        messages=[
            UserMessage(
                # 当前 examples/quickstart.py 只能让模型“提出要调用工具”，即打印出stop_reason=toolUse，但不会真正执行工具。
                # content=[TextContent(text="tell me current time")],
                content=[TextContent(text="introduce yourself in 20 words")],
                timestamp=int(time.time() * 1000),
            )
        ],
        # 可选工具
        tools=[
            Tool(
                name="get_time",
                description="Get current UTC time",
                parameters={"type": "object", "properties": {}, "additionalProperties": False},
            )
        ],
    )

    # 3) 调用大模型，并一边生成一边打印回复内容
    s = stream_simple(model, context, reasoning="low") # 流式请求
    # 异步地从模型响应里一段一段取事件，模型像打字一样分段返回，每一小段都会变成一个 event
    async for event in s:
        # 只处理“文本增量”事件
        # event["delta"]：本次新增的文本片段
        # end=""：打印完不要自动换行
        # flush=True：立刻显示，不要等缓冲区满了再显示
        if event["type"] == "text_delta":
            print(event["delta"], end="", flush=True)

    # 4) 拿最终消息(模型最终回复内容+停止原因+错误信息+token使用量等)
    # 停止原因: 正常结束stop/模型调用工具toolUse/达到长度限制length/用户中途取消aborted/请求报错error等
    msg = await s.result()
    print(f"\nstop_reason={msg.stop_reason}") 
    if msg.stop_reason in {"error", "aborted"}:
        print(f"error_message={msg.error_message}")


if __name__ == "__main__":
    # 启动异步事件循环，执行 main 里面的模型调用流程。
    asyncio.run(main())

```

## 执行方式

先安装项目

```
pip install -e ".[dev]"
```

加载环境变量

```
. .\.env.ps1
```

运行`python examples\quickstart.py`之前，有几个地方需要修改

```python
model = get_model("openai-standard", "deepseek-v4-pro")
```

执行

```
python examples\quickstart.py
```

执行结果

<img src="img/03_运行quickstart_img/image-20260602204549299.png" alt="image-20260602204549299" style="zoom: 80%;" />

当前的quickstart能让模型“提出要调用工具”，即打印出stop_reason=toolUse，但不会真正执行工具。



## 小问题

我使用的是deepseek，我问了好几遍，一直回答他是claude？因为有系统提示词吗？还是什么原因？

<img src="img/03_运行quickstart_img/image-20260602205057307.png" alt="image-20260602205057307" style="zoom:80%;" />

让AI单独写了个测试，即使完全绕开项目代码，直接打 DeepSeek API，response_model 也显示是 deepseek-v4-pro，但模型内容仍然自称 Claude。

应该是提示词的原因，之前问他【"introduce your model in 20 words"】，回答是cluade，问他【"What model are you?"】，就回复是deepseek了

<img src="img/03_运行quickstart_img/image-20260602211932052.png" alt="image-20260602211932052" style="zoom: 80%;" />



# agent_core_quickstart.py

## 代码

`agent_core_quickstart.py`：**最小 Agent + 自定义工具**，**不包含coding_agent**；看模型能否调用工具

- 定义工具AgentTool
- 创建模型、工具
- 创建Agent：模型、工具、提示词....
- 
- 创建监听器：监听事件
- Agent订阅监听器
- 
- 发起对话agent.prompt()
- 打印输出



```python
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

```

真正调用 get_time_tool 的是 **Agent 框架里的工具执行循环**，不是 on_event

```python
# 如果后面模型请求调用名为 get_time 的工具，Agent 就执行这个 Python 函数。
tool = AgentTool(
    name="get_time",
    ...
    execute=get_time_tool,
)
```

调用链

```
await agent.prompt(...)
→ Agent 调用大模型
→ 大模型返回一个 ToolCall：我要调用 get_time
→ agent_core 找到 name == "get_time" 的 AgentTool
→ 调用 tool.execute(...)
→ 实际执行 get_time_tool(...)
→ 把工具结果作为 ToolResultMessage 放回上下文
→ 再调用一次大模型生成最终回答
```



## 执行

```
. .\.env.ps1
python agent_core_quickstart.py
```

终端打印了`[tool-event] tool_execution_end: get_time`，说明调用了工具

<img src="img/03_运行quickstart_img/image-20260606133047299.png" alt="image-20260606133047299" style="zoom:67%;" />



# coding_agent_quickstart.py

`coding_agent_quickstart.py`：coding_agent最小示例；**创建并保存会话记录**

- 创建 AgentSession
- 向大模型发一句话，拿到助手回复
- 打印会话信息：会话目录与历史条数
- 保存会话到`.xingclaw/sessions/<session_id>`

为什么要创建会话

- **创建会话就是创建一段<u>可持续对话的上下文容器</u>**，AgentSession负责保存**这次 Agent 运行需要的一整套东西**：
  - 模型：provider="openai-standard" + model_id="deepseek-v4-pro"
  - **系统提示词**：你是一个简洁可靠的编程助手。
  - **工作目录**：workspace_dir=Path.cwd()
  - **对话历史**：用户说过什么，助手回过什么
  - **会话 ID**：session.session_id
  - **会话文件目录**：.xingclaw/sessions/<session_id>
  - 事件日志：比如消息开始、消息结束、工具调用等
  - 上下文压缩、重试、恢复等应用层能力
- 模型本身其实没有长期记忆。每次请求大模型本质上都是一次独立 API 调用。所谓“连续对话”，是程序把之前的消息历史一起带给模型，模型才看起来像记得前文。**session.messages 里保存了历史，第二次请求时可以把历史一起传进去**。
- 保存会话到`.xingclaw/sessions/<session_id>`

```python
"""
coding_agent 最小示例：
1) 创建 AgentSession
2) 发起一次对话
3) 打印会话目录与历史条数
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from ai import AssistantMessage, TextContent
from coding_agent import CreateAgentSessionOptions, create_agent_session


async def main() -> None:
    # 创建会话
    session = create_agent_session(
        CreateAgentSessionOptions(
            workspace_dir=Path.cwd(), # 当前运行目录当成工作区
            provider="openai-standard",
            model_id="deepseek-v4-pro",
            system_prompt="你是一个简洁可靠的编程助手。",
            thinking_level="minimal",
        )
    )

    # 发起对话
    await session.prompt("请用一句话介绍你自己。")

    # 找到并打印最后一条助手消息AssistantMessage
    # session.messages 保存整个会话历史，包括用户消息、助手消息、工具结果等
    final_assistant = next((m for m in reversed(session.messages) if isinstance(m, AssistantMessage)), None)
    if final_assistant is not None:
        text = "".join(b.text for b in final_assistant.content if isinstance(b, TextContent)).strip()
        print("[assistant.stop_reason]", final_assistant.stop_reason)
        print("[assistant.error_message]", final_assistant.error_message)
        print("[assistant.text]", text if text else "(empty)")

    # coding_agent 把会话持久化到.xingclaw/sessions/<session_id>
    print("[session.id]", session.session_id)
    print("[session.dir]", Path.cwd() / ".xingclaw" / "sessions" / session.session_id)
    print("[session.message_count]", len(session.messages))
    # 关闭会话
    session.close()


if __name__ == "__main__":
    asyncio.run(main())

```



```
python examples\coding_agent_quickstart.py
```

<img src="img/03_运行quickstart_img/image-20260606133107620.png" alt="image-20260606133107620" style="zoom:80%;" />



# coding_agent_print_mode.py

`coding_agent_print_mode.py`：**CLI 的单次问答**

- 没有传入工具

```python
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

```



<img src="img/03_运行quickstart_img/image-20260606133836348.png" alt="image-20260606133836348" style="zoom:67%;" />

# coding_agent_interactive_mode.py

`coding_agent_interactive_mode.py`：**交互式多轮对话**

```python
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

```



能进行交互式的多轮对话

<img src="img/03_运行quickstart_img/image-20260606140221940.png" alt="image-20260606140221940" style="zoom:80%;" />

# coding_agent_resume_quickstart.py

`coding_agent_resume_quickstart.py`：**恢复会话**

- 第一次，创建 session
- 第二次，用 session_id 恢复历史

```python
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

```

<img src="img/03_运行quickstart_img/image-20260606141205283.png" alt="image-20260606141205283" style="zoom:80%;" />

