from __future__ import annotations

"""
Anthropic Messages API 流式 provider。

把 Anthropic 的 SSE 流式响应，转换成项目内部统一的事件流 AssistantMessageEventStream。
实现思路：
1) 读取 SSE 的 event/data；
2) 按 content block 组装 text/thinking/toolCall；
3) 映射 stop reason 并输出统一 done/error 事件。
"""

import asyncio
import json
from typing import Any

import httpx

from ..env_api_keys import get_env_api_key
from ..event_stream import AssistantMessageEventStream
from ..types import Context, Model, SimpleStreamOptions, StreamOptions, TextContent, ThinkingContent, ToolCall
from ._common import empty_assistant_message, parse_partial_json, to_anthropic_messages, to_anthropic_tools


def _map_stop_reason(reason: str | None) -> str:
    if reason == "tool_use":
        return "toolUse"
    if reason == "max_tokens":
        return "length"
    return "stop"


def stream_anthropic(
    model: Model,
    context: Context,
    options: StreamOptions | None = None,
) -> AssistantMessageEventStream:
    """ 

    """

    # 1) 创建事件流容器
    stream = AssistantMessageEventStream()
    # 解析选项，环境变量，模型配置等，准备调用 API 需要的参数
    resolved_options = options or StreamOptions() # 如果 options 是 None，使用默认 StreamOptions 对象

    # 2) 后台异步任务：执行 API 调用，处理响应，推送事件
    async def _run() -> None:

        # 1) 空的最终消息 out
        out = empty_assistant_message(api=model.api, provider=model.provider, model=model.id)
        try:
            # 2) 读取 API key，组装 Anthropic 请求头和 payload
            # API key：调用选项 > 环境变量
            api_key = resolved_options.api_key or get_env_api_key(model.provider)
            if not api_key:
                raise RuntimeError("Missing ANTHROPIC_API_KEY")
            # header
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01", # FIXME 
                "Content-Type": "application/json",
            }
            # 模型配置和调用选项的 header 都要加上，调用选项优先级更高
            if model.headers:
                headers.update(model.headers) 
            if resolved_options.headers:
                headers.update(resolved_options.headers)

            # payload
            payload: dict[str, Any] = {
                "model": model.id,
                "max_tokens": resolved_options.max_tokens or model.max_tokens,
                # 把统一 Context 转成 Anthropic Messages API 的 messages 列表
                "messages": to_anthropic_messages(context), 
                "stream": True,
            }
            if context.system_prompt:
                payload["system"] = context.system_prompt
            if resolved_options.temperature is not None:
                payload["temperature"] = resolved_options.temperature
            tools = to_anthropic_tools(context.tools)
            if tools:
                payload["tools"] = tools

            # 3) httpx.AsyncClient发起请求，处理 SSE 流式响应
            timeout = resolved_options.timeout_seconds or None
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST",
                    f"{model.base_url.rstrip('/')}/v1/messages",
                    headers=headers,
                    json=payload,
                ) as response:
                    # 检查响应状态码，抛出异常会被外层捕获并推送 error 事件
                    response.raise_for_status()
                    # 连接成功后先推一个统一的 start 事件
                    stream.push({"type": "start", "partial": out})

                    current_event: str | None = None
                    current_index: int | None = None
                    text_blocks: dict[int, TextContent] = {}
                    thinking_blocks: dict[int, ThinkingContent] = {}
                    tool_blocks: dict[int, ToolCall] = {}
                    tool_partial_json: dict[int, str] = {}
                    
                    # 4) 核心循环：逐行读取 SSE 响应，解析 event/data，更新 out 和 block 状态，推送增量事件
                    async for raw_line in response.aiter_lines():
                        line = raw_line.strip()
                        if not line:
                            continue
                        
                        # 遇到 event: 记录当前事件类型
                        if line.startswith("event:"):
                            current_event = line[len("event:") :].strip()
                            continue
                        if not line.startswith("data:"):
                            continue
                        
                        # 遇到 data: 解析 JSON，然后按 Anthropic 事件类型分发处理。
                        data = json.loads(line[len("data:") :].strip())

                        # 根据事件类型组装消息
                        if current_event == "message_start":
                            message = data.get("message", {})
                            out.response_id = message.get("id")
                            usage = message.get("usage", {})
                            out.usage.input = usage.get("input_tokens", out.usage.input)

                        elif current_event == "content_block_start":
                            """ 新内容块开始（文本/思考/工具调用） """
                            current_index = data.get("index", 0)
                            block = data.get("content_block", {})
                            block_type = block.get("type")
                            if block_type == "text":
                                tb = TextContent(text="")
                                text_blocks[current_index] = tb
                                out.content.append(tb)
                                stream.push(
                                    {"type": "text_start", "contentIndex": len(out.content) - 1, "partial": out}
                                )
                            elif block_type in {"thinking", "redacted_thinking"}:
                                th = ThinkingContent(thinking="", redacted=(block_type == "redacted_thinking"))
                                thinking_blocks[current_index] = th
                                out.content.append(th)
                                stream.push(
                                    {"type": "thinking_start", "contentIndex": len(out.content) - 1, "partial": out}
                                )
                            elif block_type == "tool_use":
                                tc = ToolCall(id=block.get("id", ""), name=block.get("name", ""), arguments={})
                                tool_blocks[current_index] = tc
                                tool_partial_json[current_index] = ""
                                out.content.append(tc)
                                stream.push(
                                    {"type": "toolcall_start", "contentIndex": len(out.content) - 1, "partial": out}
                                )

                        elif current_event == "content_block_delta": 
                            """ 内容增量 """
                            idx = data.get("index", current_index if current_index is not None else 0)
                            delta = data.get("delta", {})
                            delta_type = delta.get("type")
                            if delta_type == "text_delta" and idx in text_blocks:
                                text = delta.get("text", "")
                                text_blocks[idx].text += text
                                stream.push(
                                    {
                                        "type": "text_delta",
                                        "contentIndex": out.content.index(text_blocks[idx]),
                                        "delta": text,
                                        "partial": out,
                                    }
                                )
                            elif delta_type in {"thinking_delta", "signature_delta"} and idx in thinking_blocks:
                                text = delta.get("thinking", "")
                                if text:
                                    thinking_blocks[idx].thinking += text
                                    stream.push(
                                        {
                                            "type": "thinking_delta",
                                            "contentIndex": out.content.index(thinking_blocks[idx]),
                                            "delta": text,
                                            "partial": out,
                                        }
                                    )
                            elif delta_type == "input_json_delta" and idx in tool_blocks:
                                piece = delta.get("partial_json", "")
                                tool_partial_json[idx] += piece
                                tool_blocks[idx].arguments = parse_partial_json(tool_partial_json[idx])
                                stream.push(
                                    {
                                        "type": "toolcall_delta",
                                        "contentIndex": out.content.index(tool_blocks[idx]),
                                        "delta": piece,
                                        "partial": out,
                                    }
                                )

                        elif current_event == "content_block_stop":
                            idx = data.get("index", current_index if current_index is not None else 0)
                            if idx in text_blocks:
                                block = text_blocks[idx]
                                stream.push(
                                    {
                                        "type": "text_end",
                                        "contentIndex": out.content.index(block),
                                        "content": block.text,
                                        "partial": out,
                                    }
                                )
                            elif idx in thinking_blocks:
                                block = thinking_blocks[idx]
                                stream.push(
                                    {
                                        "type": "thinking_end",
                                        "contentIndex": out.content.index(block),
                                        "content": block.thinking,
                                        "partial": out,
                                    }
                                )
                            elif idx in tool_blocks:
                                block = tool_blocks[idx]
                                stream.push(
                                    {
                                        "type": "toolcall_end",
                                        "contentIndex": out.content.index(block),
                                        "toolCall": block,
                                        "partial": out,
                                    }
                                )

                        elif current_event == "message_delta":
                            delta = data.get("delta", {})
                            usage = data.get("usage", {})
                            out.stop_reason = _map_stop_reason(delta.get("stop_reason"))
                            out.usage.output = usage.get("output_tokens", out.usage.output)
                    # 全部读完，推送done事件
                    stream.push({"type": "done", "reason": out.stop_reason, "message": out})
                    stream.end(out)
        except Exception as exc:
            out.stop_reason = "error"
            out.error_message = str(exc)
            stream.push({"type": "error", "reason": "error", "error": out})
            stream.end(out)

    # NOTE 后台异步任务异步执行_run()
    # NOTE python的异步机制:异步任务能改 stream，是因为它和调用方持有同一个对象引用；不是修改另一个线程的局部变量。
    asyncio.create_task(_run())
    # 3) 立即返回事件流（不等结果）
    return stream


def stream_simple_anthropic(
    model: Model,
    context: Context,
    options: SimpleStreamOptions | None = None,
) -> AssistantMessageEventStream:
    # 第一阶段实现：simple 接口复用标准 stream。
    return stream_anthropic(model, context, options)
