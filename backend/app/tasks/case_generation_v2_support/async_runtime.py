from __future__ import annotations

import asyncio
import atexit
import inspect
import os
import threading
from typing import Awaitable, TypeVar

import httpx


T = TypeVar("T")


class AsyncRuntime:
    """One long-lived event loop and HTTP pool per worker process."""

    def __init__(self) -> None:
        self._pid = os.getpid()
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._http_client: httpx.AsyncClient | None = None

    def _serve(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        loop.run_forever()
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._pid != os.getpid():
            self.__init__()
        if self._thread and self._thread.is_alive() and self._loop:
            return self._loop
        with self._lock:
            if not self._thread or not self._thread.is_alive():
                self._ready.clear()
                self._thread = threading.Thread(
                    target=self._serve,
                    name="case-generation-v2-async",
                    daemon=True,
                )
                self._thread.start()
        if not self._ready.wait(timeout=5) or self._loop is None:
            raise RuntimeError("V2 异步运行时启动失败")
        return self._loop

    def run(self, awaitable: Awaitable[T]) -> T:
        if not inspect.isawaitable(awaitable):
            raise TypeError("run_async 需要 awaitable")
        loop = self._ensure_loop()
        if threading.current_thread() is self._thread:
            raise RuntimeError("不能在 V2 异步运行时内部同步等待协程")
        return asyncio.run_coroutine_threadsafe(awaitable, loop).result()

    async def shared_http_client(self) -> httpx.AsyncClient | None:
        loop = self._loop
        if loop is None or self._thread is None or not self._thread.is_alive():
            return None
        if asyncio.get_running_loop() is not loop:
            return None
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )
        return self._http_client

    def close(self) -> None:
        loop = self._loop
        thread = self._thread
        if not loop or not thread or not thread.is_alive():
            return
        if self._http_client is not None and not self._http_client.is_closed:
            try:
                asyncio.run_coroutine_threadsafe(self._http_client.aclose(), loop).result(timeout=3)
            except Exception:
                pass
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=3)


_RUNTIME = AsyncRuntime()


def run_async(awaitable: Awaitable[T]) -> T:
    return _RUNTIME.run(awaitable)


async def shared_http_client() -> httpx.AsyncClient | None:
    return await _RUNTIME.shared_http_client()


atexit.register(_RUNTIME.close)
