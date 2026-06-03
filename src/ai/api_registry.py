from __future__ import annotations

"""
api -> provider 实现的注册中心。

这样可以做到：
1) stream() 时按 model.api 动态分发；
2) 后续扩展新 provider 时只需注册，不改调用方代码。
"""

from dataclasses import dataclass
from typing import Callable

from .event_stream import AssistantMessageEventStream
from .types import Context, Model, SimpleStreamOptions, StreamOptions


# 两个函数签名约束，类似Java的接口
# StreamFn 是完整流式调用函数，SimpleStreamFn 是简化流式调用函数。
# StreamFn接收3个参数，返回AssistantMessageEventStream
StreamFn = Callable[[Model, Context, StreamOptions | None], AssistantMessageEventStream]
# SimpleStreamFn接收3个参数，返回AssistantMessageEventStream
SimpleStreamFn = Callable[[Model, Context, SimpleStreamOptions | None], AssistantMessageEventStream]

@dataclass
class ApiProvider:
    """ 保存某个 API 协议的名称、这个协议对应的两个调用函数 """
    api: str # 协议标识，如 "anthropic-messages"
    stream: StreamFn # 完整流式调用函数
    stream_simple: SimpleStreamFn # 简化流式调用函数


# API 协议实现注册表：根据 API 协议名分发到具体请求实现函数的注册表。
_REGISTRY: dict[str, ApiProvider] = {}


def register_api_provider(provider: ApiProvider) -> None:
    """注册或覆盖某个 api 的 provider。"""
    _REGISTRY[provider.api] = provider


def get_api_provider(api: str) -> ApiProvider | None:
    """按 api 获取 provider；不存在返回 None。"""
    return _REGISTRY.get(api)


def clear_api_providers() -> None:
    """清空注册中心（通常用于测试或重置）。"""
    _REGISTRY.clear()
