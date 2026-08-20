"""Async runner bridge.

The services are implemented with `async def` (matching the spec's Playwright
code), but the Flask web layer is synchronous. `run_async` executes a coroutine
on a dedicated background event loop, so routes never block on asyncio.run and
nested loops can never collide across threads.
"""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import Future
from typing import Awaitable, TypeVar

_T = TypeVar("_T")

_loop: asyncio.AbstractEventLoop | None = None
_loop_lock = threading.Lock()


def _get_loop() -> asyncio.AbstractEventLoop:
    """A single daemon-thread event loop reused for the life of the process."""
    global _loop
    with _loop_lock:
        if _loop is None or _loop.is_closed():
            loop = asyncio.new_event_loop()
            thread = threading.Thread(target=loop.run_forever, daemon=True)
            thread.start()
            _loop = loop
        return _loop


def run_async(coro: Awaitable[_T], timeout: float | None = None) -> _T:
    """Run a coroutine on the shared event loop and return its result."""
    future: Future = asyncio.run_coroutine_threadsafe(coro, _get_loop())
    return future.result(timeout=timeout)


def close_loop() -> None:
    """Shut the shared loop down (test teardown / process exit)."""
    global _loop
    with _loop_lock:
        if _loop is not None:
            _loop.call_soon_threadsafe(_loop.stop)
            _loop = None