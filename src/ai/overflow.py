from __future__ import annotations

"""
上下文溢出检测。

根据模型 context_window 粗略估算当前 token 总量，
判定是否超出上下文窗口，便于 Agent 侧在调用前主动压缩。

每次发送 prompt 之前都会检查是否溢出，用户发消息 → 检查是否溢出 → 如果溢出，用 LLM 生成摘要压缩历史 → 再发送

这里不使用每个模型都有自己的分词器：不是精确计费、安装依赖太重
"""

from .types import (
    AssistantMessage,
    Context,
    ImageContent,
    Message,
    Model,
    TextContent,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)

# 粗略估计: 真正的 token 计算需要用模型专用的分词器（tokenizer），不同模型的分词方式不一样。
# 但在"判断要不要压缩"这个场景下，用字符数除以 4 就够用了——偏差在可接受范围内，而且几乎不消耗性能
CHARS_PER_TOKEN = 4  # 粗略估算：平均 4 个字符 ≈ 1 个 token
IMAGE_TOKEN_ESTIMATE = 1000 #  一张图片粗算 1000 token
TOOL_SCHEMA_TOKEN_ESTIMATE = 200 # 一个工具的 JSON Schema 粗算 200 token


def estimate_message_tokens(msg: Message) -> int:
    """ 估算一条消息的 token 数。根据消息类型和内容不同，计算方式也不同。"""
    # 字符数
    total = 0
    # 用户消息：可能是纯文本，也可能包含图片
    if isinstance(msg, UserMessage):
        # 文本内容直接按字符数估算
        if isinstance(msg.content, str):
            total += len(msg.content)
        else:
            for block in msg.content:
                # 文本按字符数估算，图片按固定 token 数估算
                if isinstance(block, TextContent):
                    total += len(block.text)
                elif isinstance(block, ImageContent):
                    total += IMAGE_TOKEN_ESTIMATE * CHARS_PER_TOKEN
    elif isinstance(msg, AssistantMessage):
        for block in msg.content:
            if isinstance(block, TextContent):
                total += len(block.text)
            elif isinstance(block, ThinkingContent):
                total += len(block.thinking)
            elif isinstance(block, ToolCall):
                total += len(str(block.arguments)) + len(block.name) + 20
    elif isinstance(msg, ToolResultMessage):
        for block in msg.content:
            if isinstance(block, TextContent):
                total += len(block.text)
            elif isinstance(block, ImageContent):
                total += IMAGE_TOKEN_ESTIMATE * CHARS_PER_TOKEN
    return max(1, total // CHARS_PER_TOKEN)


def estimate_context_tokens(
    messages: list[Message],
    system_prompt: str = "",
    tools: list | None = None,
) -> int:
    """ 估算整个请求上下文的 token 数。"""

    # 系统提示词的 token
    total = len(system_prompt) // CHARS_PER_TOKEN

    # 消息列表的 token
    for msg in messages:
        total += estimate_message_tokens(msg)

    # 工具定义的 token（每个工具固定 200）
    if tools:
        total += len(tools) * TOOL_SCHEMA_TOKEN_ESTIMATE
    return total


def is_context_overflow(
    model: Model,
    context: Context,
    *,
    safety_margin: float = 0.95, 
) -> bool:
    """
    检查 context 是否超出模型 context_window。

    safety_margin：安全系数（默认 0.95，即保留 5% 余量给输出）。
    """
    # 阈值
    limit = int(model.context_window * safety_margin)
    estimated = estimate_context_tokens(
        context.messages,
        context.system_prompt or "",
        context.tools,
    )
    return estimated > limit


def overflow_ratio(model: Model, context: Context) -> float:
    """返回当前 token 占 context_window 的比例。"""
    estimated = estimate_context_tokens(
        context.messages,
        context.system_prompt or "",
        context.tools,
    )
    if model.context_window <= 0:
        return 0.0
    return estimated / model.context_window
