import logging
from typing import Callable

from PyQt5.QtCore import QObject, QTimer


class EngineWatchdog(QObject):
    def __init__(
        self,
        parent,
        should_be_running: Callable[[], bool],
        is_alive: Callable[[], bool],
        recover: Callable[[], None],
        interval_ms: int = 4000,
    ):
        super().__init__(parent)
        self._should_be_running = should_be_running
        self._is_alive = is_alive
        self._recover = recover
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(interval_ms)

    def _tick(self):
        if self._should_be_running() and not self._is_alive():
            logging.warning("Watchdog detected stopped worker while monitoring expected. Recovering.")
            self._recover()

