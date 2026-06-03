from __future__ import annotations

"""
本模块定义 ai 包的核心数据结构。

设计原则：
1. 对外暴露稳定的数据模型，避免调用方直接依赖 provider 私有字段。
2. 不同 provider 的输入输出都先转换成同一种内部格式，再交给上层 Agent 使用。


"""

from dataclasses import dataclass, field
from typing import Any, Literal, Optional, Union

# 协议标识：用于把请求分发到对应 provider, openai-compatible/anthropic
Api = str
# 供应商标识：用于鉴权和模型分组。
Provider = str
# 一次回答结束原因：正常结束stop/达到长度限制length/工具调用toolUse/错误error/被外部中断aborted。
StopReason = Literal["stop", "length", "toolUse", "error", "aborted"]
# 简化推理等级（留给 stream_simple 接口使用）。
ThinkingLevel = Literal["minimal", "low", "medium", "high", "xhigh"]


####################################################################
# 成本统计、用量统计
####################################################################

# @dataclass是装饰器(注解)，类似Java的@Data，自动生成一些常用方法
# 如__init__()、__repr__()、__eq__()等。
@dataclass
class Cost:
    """成本统计，单位由上层自行约定（通常是美元）。"""
    input: float = 0.0
    output: float = 0.0
    cache_read: float = 0.0
    cache_write: float = 0.0
    total: float = 0.0


@dataclass
class Usage:
    """token 使用统计。"""
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    total_tokens: int = 0
    cost: Cost = field(default_factory=Cost)

####################################################################
# 4种内容块：文本块、思考块、图片块、工具调用块
####################################################################

@dataclass
class TextContent:
    """普通文本块。"""
    # type 字段只能是字符串 "text"，默认值也是 "text"
    # Literal["text"]表示这个变量的值必须是某个具体的字面量
    type: Literal["text"] = "text"
    # 类型是str，默认值是空字符串
    text: str = ""
    # Optional[str] 等同于 str | None（或 Union[str, None]），表示该字段可以是字符串也可以是 None。
    text_signature: Optional[str] = None


@dataclass
class ThinkingContent:
    """模型的思考块（如果 provider 支持）。"""

    type: Literal["thinking"] = "thinking"
    thinking: str = ""
    thinking_signature: Optional[str] = None
    redacted: bool = False


@dataclass
class ImageContent:
    """图片块，使用 base64 数据承载。"""

    type: Literal["image"] = "image"
    data: str = ""
    mime_type: str = "image/png"


@dataclass
class ToolCall:
    """模型发起的工具调用。"""

    type: Literal["toolCall"] = "toolCall"
    id: str = ""
    name: str = ""
    # 字典key 是 str，value 可以是任意类型；
    # 如果创建对象时不传 arguments，dataclass 会调用 dict() 生成一个新的空字典。
    # 默认值是不可变的，比如 0、""、None，可以直接写；
    # 默认值是可变容器，比如 dict、list、set，用 default_factory。
    arguments: dict[str, Any] = field(default_factory=dict)



####################################################################
# 3种消息角色：用户消息、助手消息、工具结果消息
####################################################################

AssistantBlock = Union[TextContent, ThinkingContent, ToolCall]
UserBlock = Union[TextContent, ImageContent]
ToolResultBlock = Union[TextContent, ImageContent]


@dataclass
class UserMessage:
    """用户消息。"""

    role: Literal["user"] = "user"
    content: Union[str, list[UserBlock]] = ""
    timestamp: int = 0


@dataclass
class AssistantMessage:
    """助手消息（流式完成后的标准形态）。"""

    role: Literal["assistant"] = "assistant"
    content: list[AssistantBlock] = field(default_factory=list)
    api: Api = ""
    provider: Provider = ""
    model: str = ""
    usage: Usage = field(default_factory=Usage)
    stop_reason: StopReason = "stop"
    response_id: Optional[str] = None
    error_message: Optional[str] = None
    timestamp: int = 0


@dataclass
class ToolResultMessage:
    """工具执行结果消息。"""

    role: Literal["toolResult"] = "toolResult"
    # 通过 `tool_call_id` 跟 `ToolCall` 配对
    # AI 说"我要调用工具 A"（ToolCall），工具执行完后返回"工具 A 的结果是 xxx"（ToolResultMessage），两者通过 id 关联。
    tool_call_id: str = ""
    tool_name: str = ""
    content: list[ToolResultBlock] = field(default_factory=list)
    is_error: bool = False
    details: Any = None
    timestamp: int = 0

# 统一的消息类型——任何一条消息都是这三者之一
Message = Union[UserMessage, AssistantMessage, ToolResultMessage]



####################################################################
# 工具定义、请求上下文
####################################################################
@dataclass
class Tool:
    """可被模型调用的工具定义。"""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class Context:
    """一次请求上下文：系统提示词 + 消息历史 + 可用工具。
    每次调用 LLM 时，都是把一个 Context 发过去
    """

    messages: list[Message]
    system_prompt: Optional[str] = None
    tools: Optional[list[Tool]] = None



####################################################################
# 流式调用参数
####################################################################

@dataclass
class StreamOptions:
    """流式调用的通用参数。"""

    temperature: Optional[float] = None # 模型输出随机性
    max_tokens: Optional[int] = None # 模型回复的最大 token 数 
    api_key: Optional[str] = None # 
    headers: Optional[dict[str, str]] = None
    timeout_seconds: Optional[float] = None
    session_id: Optional[str] = None


@dataclass
class SimpleStreamOptions(StreamOptions):
    """简化接口参数：额外支持 reasoning 等级。"""

    reasoning: Optional[ThinkingLevel] = None # 推理等级


####################################################################
# 模型配置
####################################################################

@dataclass
class Model:
    """
    模型配置。

    注意：
    - api 决定请求走哪种协议实现；
    - provider 决定默认鉴权读取方式；
    - base_url 允许指向官方服务或自建兼容网关。
    """

    id: str   # 模型 ID，如 "claude-sonnet-4-5"
    name: str  # 模型名称，如 "Claude Sonnet 4.5"
    api: Api  # 协议标识，如 "anthropic-messages" 或 "openai-standard"
    provider: Provider # 供应商标识，如 "anthropic" 或 "openai"
    base_url: str # api URL
    reasoning: bool # 是否支持"思考"模式  
    input: list[Literal["text", "image"]] #  支持的输入类型（文本、图片）
    context_window: int #   上下文窗口大小（能记住多少 token）
    max_tokens: int # 单次回复最大 token 数
    cost: Cost = field(default_factory=Cost) # 预估成本
    headers: Optional[dict[str, str]] = None # 额外请求头
    compat: Optional[dict[str, Any]] = None
