from __future__ import annotations

"""
统一事件流容器，封装一个统一的“AI 回复流”。

调用方可以：
1) async for event in stream: 逐个消费事件；
2) message = await stream.result() 等待获取最终 AssistantMessage。
"""

import asyncio
from typing import Any, AsyncIterator, Optional

from .types import AssistantMessage


_SENTINEL = object()


class AssistantMessageEventStream:
    def __init__(self) -> None:
        # 事件队列：生产者 push 事件进来，消费者 async for 取出去
        # NOTE asyncio.Queue[Any]表示_queue是asyncio.Queue且队列中的元素类型为Any
        # ""是延迟解析类型，避免运行时类型解析问题
        # = asyncio.Queue()：真正创建一个异步队列实例
        self._queue: "asyncio.Queue[Any]" = asyncio.Queue()
        # Future对象：保存最终完整的 
        # 在当前事件循环上创建一个 Future 对象。
        self._result: "asyncio.Future[AssistantMessage]" = asyncio.get_event_loop().create_future()
        self._closed = False

    def push(self, event: dict[str, Any]) -> None:
        """生产者调用：provider 生成一小段内容后，往队列中推送一个事件（text_delta/toolcall_delta/...）。"""
        if self._closed:
            return
        self._queue.put_nowait(event)

    def end(self, message: AssistantMessage) -> None:
        """生产者调用：流正常结束，写入最终消息，并放入_SENTINEL通知 async for 停止。"""
        if self._closed:
            return
        self._closed = True
        if not self._result.done():
            self._result.set_result(message)
        self._queue.put_nowait(_SENTINEL)

    def fail(self, error: Exception, fallback: Optional[AssistantMessage] = None) -> None:
        """
        生产者调用：流异常结束。

        fallback 存在时，result() 仍返回 fallback；
        否则 result() 抛出异常。
        """
        if self._closed:
            return
        self._closed = True
        if fallback is not None:
            if not self._result.done():
                self._result.set_result(fallback)
        else:
            if not self._result.done():
                self._result.set_exception(error)
        self._queue.put_nowait(_SENTINEL)

    async def result(self) -> AssistantMessage:
        """消费者调用：等待并返回最终 AssistantMessage。"""
        return await self._result

    def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
        return self._iter_events()

    async def _iter_events(self) -> AsyncIterator[dict[str, Any]]:
        """ 消费者调用：逐个取出事件，直到流结束。 """
        while True:
            item = await self._queue.get()
            if item is _SENTINEL:
                break
            yield item
