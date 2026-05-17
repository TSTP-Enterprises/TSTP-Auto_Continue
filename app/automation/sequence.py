import threading
import time
from dataclasses import dataclass
from typing import Dict, List

from app.automation.matching import DetectionHit


@dataclass
class SequenceDecision:
    hits_to_click: List[DetectionHit]
    reset_happened: bool = False


class SequenceController:
    def __init__(self):
        self._lock = threading.Lock()
        self._mode = "parallel"
        self._order: List[str] = []
        self._reset_seconds = 2.0
        self._index = 0
        self._last_progress = time.monotonic()

    def update_config(self, mode: str, order: List[str], reset_seconds: float) -> None:
        with self._lock:
            self._mode = mode
            self._order = [target_id for target_id in order if target_id]
            self._reset_seconds = max(0.01, reset_seconds)
            if self._index >= len(self._order):
                self._index = 0

    def reset(self) -> None:
        with self._lock:
            self._index = 0
            self._last_progress = time.monotonic()

    def choose(self, hits: List[DetectionHit]) -> SequenceDecision:
        if not hits:
            with self._lock:
                if self._mode == "sequence" and self._order:
                    now = time.monotonic()
                    if now - self._last_progress >= self._reset_seconds:
                        self._index = 0
                        self._last_progress = now
                        return SequenceDecision([], reset_happened=True)
            return SequenceDecision([])

        best_by_target: Dict[str, DetectionHit] = {}
        for hit in sorted(hits, key=lambda item: item.score, reverse=True):
            if hit.target.id not in best_by_target:
                best_by_target[hit.target.id] = hit

        with self._lock:
            if self._mode != "sequence" or not self._order:
                return SequenceDecision(list(best_by_target.values()))

            expected_target = self._order[self._index]
            found = best_by_target.get(expected_target)
            if found is None:
                now = time.monotonic()
                if now - self._last_progress >= self._reset_seconds:
                    self._index = 0
                    self._last_progress = now
                    return SequenceDecision([], reset_happened=True)
                return SequenceDecision([])

            self._last_progress = time.monotonic()
            self._index = (self._index + 1) % len(self._order)
            return SequenceDecision([found])

