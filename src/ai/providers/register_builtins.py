from __future__ import annotations

"""
内置 provider 注册入口。
"""
# NOTE 相对位置导入包
from ..api_registry import ApiProvider, clear_api_providers, register_api_provider
from .anthropic import stream_anthropic, stream_simple_anthropic
from .openai_compatible import stream_openai_compatible, stream_simple_openai_compatible


def register_builtin_api_providers() -> None:
    """注册两个协议 anthropic-messages 和 openai-standard。"""
    # Anthropic Messages 协议
    register_api_provider(
        ApiProvider(
            api="anthropic-messages",
            stream=stream_anthropic,
            stream_simple=stream_simple_anthropic,
        )
    )
    # OpenAI 标准协议
    register_api_provider(
        ApiProvider(
            api="openai-standard",
            stream=stream_openai_compatible,
            stream_simple=stream_simple_openai_compatible,
        )
    )


def reset_api_providers() -> None:
    """重置并重新注册内置 provider。"""
    clear_api_providers()
    register_builtin_api_providers()


# 模块加载即注册，保证 stream() 可直接使用。
# 关键：模块加载时就自动注册！
# 当你 import ai 或 import ai.providers.register_builtins的时候，这行代码就会执行
register_builtin_api_providers()
