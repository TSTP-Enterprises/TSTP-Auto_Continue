import logging
import os
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import cv2

from app.core.models import TargetSpec


try:
    import pytesseract
except Exception:  # pragma: no cover
    pytesseract = None


@dataclass
class DetectionHit:
    target: TargetSpec
    score: float
    x: int
    y: int


class TargetMatcher:
    def __init__(self):
        self._template_cache: Dict[str, object] = {}
        self._cache_lock = threading.Lock()
        self._ocr_path = ""

    def set_ocr_path(self, ocr_path: str) -> None:
        self._ocr_path = ocr_path or ""
        if pytesseract is not None and self._ocr_path and os.path.exists(self._ocr_path):
            pytesseract.pytesseract.tesseract_cmd = self._ocr_path

    def detect_stop_reason(
        self,
        gray_frame,
        stop_targets: List[TargetSpec],
        monitor_index: int,
    ) -> Optional[str]:
        for target in [target for target in stop_targets if target.enabled]:
            if target.target_type == "image":
                template = self._load_template(target.value)
                if template is None:
                    continue
                _, max_score, _, _ = cv2.minMaxLoc(
                    cv2.matchTemplate(gray_frame, template, cv2.TM_CCOEFF_NORMED)
                )
                if max_score >= target.threshold:
                    return f"Stop target matched on monitor {monitor_index + 1}: {target.name}"
            elif target.target_type == "text":
                extracted = self._extract_text(gray_frame)
                if extracted and target.value.lower() in extracted.lower():
                    return f"Stop text detected on monitor {monitor_index + 1}: {target.name}"
        return None

    def detect_click_hits(
        self,
        gray_frame,
        click_targets: List[TargetSpec],
        monitor_left: int,
        monitor_top: int,
    ) -> List[DetectionHit]:
        hits: List[DetectionHit] = []
        for target in [target for target in click_targets if target.enabled]:
            if target.target_type != "image":
                continue
            template = self._load_template(target.value)
            if template is None:
                continue

            result = cv2.matchTemplate(gray_frame, template, cv2.TM_CCOEFF_NORMED)
            _, max_score, _, max_loc = cv2.minMaxLoc(result)
            if max_score < target.threshold:
                continue

            x = monitor_left + max_loc[0] + template.shape[1] // 2
            y = monitor_top + max_loc[1] + template.shape[0] // 2
            hits.append(DetectionHit(target=target, score=float(max_score), x=int(x), y=int(y)))
        return hits

    def _load_template(self, template_path: str):
        if not template_path:
            return None
        with self._cache_lock:
            if template_path in self._template_cache:
                return self._template_cache[template_path]

        if not os.path.exists(template_path):
            logging.error(f"Template path not found: {template_path}")
            template = None
        else:
            template = cv2.imread(template_path, 0)
            if template is None:
                logging.error(f"Failed to load template image: {template_path}")

        with self._cache_lock:
            self._template_cache[template_path] = template
        return template

    def _extract_text(self, gray_frame) -> str:
        if pytesseract is None:
            return ""
        try:
            return pytesseract.image_to_string(gray_frame)
        except Exception as exc:
            logging.error(f"OCR extraction failed: {exc}")
            return ""

