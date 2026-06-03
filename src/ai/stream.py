from __future__ import annotations

"""
模型统一调用入口：
- stream / complete
- stream_simple / complete_simple
"""

from .api_registry import get_api_provider
from .event_stream import AssistantMessageEventStream
from .types import AssistantMessage, Context, Model, SimpleStreamOptions, StreamOptions


def _resolve_provider(api: str):
    """ 根据 api 字段找到对应的 provider 实现。 """
    provider = get_api_provider(api)
    if provider is None:
        raise RuntimeError(f"No API provider registered for api: {api}")
    return provider


def stream(model: Model, context: Context, options: StreamOptions | None = None) -> AssistantMessageEventStream:
    """立刻返回一个 AssistantMessageEventStream，
    可以一边生成一边消费事件，比如 text_delta、toolcall_delta"""
    provider = _resolve_provider(model.api)
    return provider.stream(model, context, options)


async def complete(model: Model, context: Context, options: StreamOptions | None = None) -> AssistantMessage:
    """返回一次完整回答,内部还是走流式,基于 stream.result()，但等到最终结果。"""
    s = stream(model, context, options)
    return await s.result()


def stream_simple(
    model: Model,
    context: Context,
    options: SimpleStreamOptions | None = None,
    *,
    reasoning: str | None = None,
) -> AssistantMessageEventStream:
    """
    简化版流式接口。

    reasoning 提供快捷写法：stream_simple(..., reasoning="low")
    """
    # 第一步：根据 model.api 找到对应的 provider 实现
    provider = _resolve_provider(model.api)
    # 第二步：把 reasoning 快捷参数写入 options
    effective_options = options or SimpleStreamOptions()
    if reasoning is not None:
        effective_options.reasoning = reasoning
    # 第三步：调用 provider 的 stream_simple 函数
    return provider.stream_simple(model, context, effective_options)


async def complete_simple(
    model: Model,
    context: Context,
    options: SimpleStreamOptions | None = None,
    *,
    reasoning: str | None = None,
) -> AssistantMessage:
    """简化版完整回答接口。"""
    s = stream_simple(model, context, options, reasoning=reasoning)
    return await s.result()
