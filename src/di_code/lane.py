from __future__ import annotations

import concurrent.futures
import threading
from collections import deque
from typing import Any, Callable


class LaneQueue:
    def __init__(self, name: str, max_concurrency: int = 1) -> None:
        self.name = name
        self.max_concurrency = max(1, max_concurrency)
        self._deque: deque[tuple[Callable[[], Any], concurrent.futures.Future]] = deque()
        self._condition = threading.Condition()
        self._active_count = 0

    def enqueue(self, fn: Callable[[], Any]) -> concurrent.futures.Future:
        future: concurrent.futures.Future = concurrent.futures.Future()
        with self._condition:
            self._deque.append((fn, future))
            self._pump()
        return future

    def _pump(self) -> None:
        while self._active_count < self.max_concurrency and self._deque:
            fn, future = self._deque.popleft()
            self._active_count += 1
            thread = threading.Thread(
                target=self._run_task,
                args=(fn, future),
                daemon=True,
                name=f"lane-{self.name}",
            )
            thread.start()

    def _run_task(self, fn: Callable[[], Any], future: concurrent.futures.Future) -> None:
        try:
            future.set_result(fn())
        except Exception as exc:
            future.set_exception(exc)
        finally:
            with self._condition:
                self._active_count -= 1
                self._pump()
                self._condition.notify_all()


class LaneManager:
    def __init__(self) -> None:
        self._lanes: dict[str, LaneQueue] = {}
        self._lock = threading.Lock()

    def enqueue(self, lane_name: str, fn: Callable[[], Any]) -> concurrent.futures.Future:
        with self._lock:
            lane = self._lanes.setdefault(lane_name, LaneQueue(lane_name))
        return lane.enqueue(fn)
