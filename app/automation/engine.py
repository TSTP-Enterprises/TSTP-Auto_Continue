import copy
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Empty, Full, Queue
from typing import List, Optional

import cv2
import mss
import numpy as np
import pyautogui
from PyQt5.QtCore import QThread, pyqtSignal
from screeninfo import get_monitors

from app.automation.matching import DetectionHit, TargetMatcher
from app.automation.sequence import SequenceController
from app.core.models import AppConfig
from app.core.time_units import to_seconds


pyautogui.FAILSAFE = True


def move_cursor_visibly(target_x: int, target_y: int, duration: float) -> None:
    if duration <= 0:
        pyautogui.moveTo(target_x, target_y, duration=0)
        return

    start_x, start_y = pyautogui.position()
    steps = max(2, int(duration * 120))
    step_sleep = duration / steps
    for step in range(1, steps + 1):
        progress = step / steps
        next_x = int(start_x + (target_x - start_x) * progress)
        next_y = int(start_y + (target_y - start_y) * progress)
        pyautogui.moveTo(next_x, next_y, duration=0)
        time.sleep(step_sleep)


class AutomationEngine(QThread):
    status_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    emergency_signal = pyqtSignal(str)
    cycle_click_count_signal = pyqtSignal(int)
    click_executed_signal = pyqtSignal(str, int, int)

    def __init__(self, config: AppConfig):
        super().__init__()
        self._stop_event = threading.Event()
        self._config_lock = threading.Lock()
        self._config = copy.deepcopy(config)
        self._matcher = TargetMatcher()
        self._sequence = SequenceController()
        self._apply_config(self._config)
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="scan-worker")
        self._click_queue: Queue[DetectionHit] = Queue(maxsize=4000)
        self._click_thread: threading.Thread | None = None

    def _apply_config(self, config: AppConfig) -> None:
        self._matcher.set_ocr_path(config.ocr_path)
        self._sequence.update_config(
            mode=config.mode,
            order=config.sequence_order,
            reset_seconds=to_seconds(config.sequence_reset_value, config.sequence_reset_unit),
        )

    def update_config(self, config: AppConfig) -> None:
        with self._config_lock:
            self._config = copy.deepcopy(config)
            self._apply_config(self._config)

    def _snapshot(self) -> AppConfig:
        with self._config_lock:
            return copy.deepcopy(self._config)

    def stop(self) -> None:
        self._stop_event.set()

    def run(self):
        try:
            self._click_thread = threading.Thread(target=self._click_worker, daemon=True, name="click-dispatcher")
            self._click_thread.start()
            with mss.mss() as capture:
                self.status_signal.emit("Monitoring started")
                while not self._stop_event.is_set():
                    config = self._snapshot()
                    cycle_start = time.monotonic()
                    stop_reason, hits = self._scan_cycle(capture, config)
                    if stop_reason:
                        self.emergency_signal.emit(stop_reason)
                        break

                    decision = self._sequence.choose(hits)
                    if decision.reset_happened:
                        self.status_signal.emit("Sequence timeout reached. Resetting to first target.")

                    queued = self._enqueue_clicks(decision.hits_to_click, config.max_clicks_per_cycle)
                    self.cycle_click_count_signal.emit(queued)

                    interval_seconds = max(0.001, to_seconds(config.scan_interval_value, config.scan_interval_unit))
                    elapsed = time.monotonic() - cycle_start
                    remaining = interval_seconds - elapsed
                    if remaining > 0:
                        time.sleep(remaining)
        except Exception as exc:
            logging.exception("Automation engine crashed.")
            self.error_signal.emit(str(exc))
        finally:
            self._stop_event.set()
            if self._click_thread is not None and self._click_thread.is_alive():
                self._click_thread.join(timeout=5)
            self._pool.shutdown(wait=False, cancel_futures=True)
            self.status_signal.emit("Monitoring stopped")

    def _scan_cycle(self, capture: mss.mss, config: AppConfig) -> tuple[Optional[str], List[DetectionHit]]:
        all_hits: List[DetectionHit] = []
        futures = []
        monitors = get_monitors()

        selected_indices = []
        for index, _monitor in enumerate(monitors):
            if -1 in config.selected_monitors or index in config.selected_monitors:
                selected_indices.append(index)

        for index in selected_indices:
            monitor = monitors[index]
            monitor_dict = {
                "top": monitor.y,
                "left": monitor.x,
                "width": monitor.width,
                "height": monitor.height,
            }
            screenshot = np.array(capture.grab(monitor_dict))
            gray = cv2.cvtColor(screenshot, cv2.COLOR_BGRA2GRAY)
            futures.append(
                self._pool.submit(
                    self._process_frame,
                    gray,
                    monitor_dict,
                    index,
                    config,
                )
            )

        for future in as_completed(futures):
            stop_reason, hits = future.result()
            if stop_reason:
                return stop_reason, []
            all_hits.extend(hits)

        return None, all_hits

    def _process_frame(self, gray, monitor_dict, monitor_index: int, config: AppConfig):
        stop_reason = self._matcher.detect_stop_reason(gray, config.stop_targets, monitor_index)
        if stop_reason:
            return stop_reason, []

        hits = self._matcher.detect_click_hits(
            gray,
            config.click_targets,
            monitor_dict["left"],
            monitor_dict["top"],
        )
        return None, hits

    def _enqueue_clicks(self, hits: List[DetectionHit], max_clicks: int) -> int:
        if not hits:
            return 0
        queued_count = 0
        for hit in hits[: max(1, max_clicks)]:
            if self._stop_event.is_set():
                break
            try:
                self._click_queue.put_nowait(hit)
                queued_count += 1
            except Full:
                logging.warning("Click queue is full; dropping click event to maintain responsiveness.")
                break
        return queued_count

    def _click_worker(self):
        while not self._stop_event.is_set() or not self._click_queue.empty():
            try:
                hit = self._click_queue.get(timeout=0.1)
            except Empty:
                continue

            config = self._snapshot()
            try:
                if config.show_mouse_movement:
                    duration = max(0.0, to_seconds(config.mouse_move_duration_value, config.mouse_move_duration_unit))
                    move_cursor_visibly(hit.x, hit.y, duration)
                pyautogui.click(hit.x, hit.y)
                self.click_executed_signal.emit(hit.target.id, hit.x, hit.y)
            except pyautogui.FailSafeException:
                fail_safe_message = (
                    "Emergency stop: PyAutoGUI fail-safe triggered (mouse moved to screen corner)."
                )
                logging.warning(fail_safe_message)
                self.emergency_signal.emit(fail_safe_message)
                self._stop_event.set()
            except Exception as exc:
                logging.exception("Click dispatcher crashed.")
                self.error_signal.emit(str(exc))
                self._stop_event.set()
            finally:
                self._click_queue.task_done()

