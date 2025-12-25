"""
Detect parent markings on a printed dictation sheet photo.

MVP assumption (to reduce OCR pressure):
- Parent only marks WRONG items using red pen (× / circle / underline) near the answer line.
- Correct items are left unmarked.
- We warp the photo to an A4-like rectangle, then sample fixed ROIs based on our PDF layout.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import cv2
import numpy as np


A4_W_MM = 210.0
A4_H_MM = 297.0


@dataclass
class MarkPrediction:
    position: int
    is_correct: bool
    confidence: float
    red_ratio: float


def _order_points(pts: np.ndarray) -> np.ndarray:
    # pts: (4,2)
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]  # tl
    rect[2] = pts[np.argmax(s)]  # br
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]  # tr
    rect[3] = pts[np.argmax(diff)]  # bl
    return rect


def _warp_to_a4(img_bgr: np.ndarray, target_w: int = 1240) -> np.ndarray:
    target_h = int(round(target_w * (A4_H_MM / A4_W_MM)))
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, 50, 150)

    cnts, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    cnts = sorted(cnts, key=cv2.contourArea, reverse=True)[:10]

    doc = None
    for c in cnts:
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4:
            doc = approx.reshape(4, 2)
            break

    if doc is None:
        # fallback: just resize (no warp). Still usable if photo is neat.
        return cv2.resize(img_bgr, (target_w, target_h))

    rect = _order_points(doc.astype("float32"))
    dst = np.array([[0, 0], [target_w - 1, 0], [target_w - 1, target_h - 1], [0, target_h - 1]], dtype="float32")
    M = cv2.getPerspectiveTransform(rect, dst)
    warped = cv2.warpPerspective(img_bgr, M, (target_w, target_h))
    return warped


def _red_mask(img_bgr: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    # two red ranges
    lower1 = np.array([0, 60, 60])
    upper1 = np.array([10, 255, 255])
    lower2 = np.array([170, 60, 60])
    upper2 = np.array([180, 255, 255])
    m1 = cv2.inRange(hsv, lower1, upper1)
    m2 = cv2.inRange(hsv, lower2, upper2)
    mask = cv2.bitwise_or(m1, m2)
    return mask


def detect_marks_on_practice_sheet(
    image_bytes: bytes,
    positions: List[int],
    per_page_capacity: int = 23,
) -> List[MarkPrediction]:
    """
    Return predictions for given positions (1..N).
    If positions exceed first-page capacity, we still return predictions for the first page subset.
    """
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Invalid image")

    warped = _warp_to_a4(img)
    mask = _red_mask(warped)

    h, w = mask.shape[:2]
    px_per_mm_x = w / A4_W_MM
    px_per_mm_y = h / A4_H_MM

    # Layout constants must match pdf_gen.py
    margin_x = 18.0
    margin_y = 18.0
    header_drop = 22.0  # title(12mm)+date(10mm)
    line_h = 11.0
    underline_x0 = margin_x + 90.0
    # We look for marks near the start of underline (a bit left)
    roi_x0 = underline_x0 - 10.0
    roi_x1 = underline_x0 + 25.0

    preds: List[MarkPrediction] = []

    for pos in positions:
        if pos < 1:
            continue
        # only first page for MVP
        if pos > per_page_capacity:
            continue

        y_mm = (A4_H_MM - margin_y - header_drop) - (pos - 1) * line_h  # row text baseline, from bottom
        underline_y_mm = y_mm - 2.0

        # convert to top-left coord system (mm)
        underline_y_from_top_mm = A4_H_MM - underline_y_mm

        # ROI rectangle (mm)
        roi_y0 = underline_y_from_top_mm - 8.0
        roi_y1 = underline_y_from_top_mm + 4.0

        x0 = int(max(0, roi_x0 * px_per_mm_x))
        x1 = int(min(w - 1, roi_x1 * px_per_mm_x))
        y0 = int(max(0, roi_y0 * px_per_mm_y))
        y1 = int(min(h - 1, roi_y1 * px_per_mm_y))
        if x1 <= x0 or y1 <= y0:
            continue

        roi = mask[y0:y1, x0:x1]
        red_ratio = float(np.count_nonzero(roi)) / float(roi.size)

        # Heuristic thresholds
        marked_wrong = red_ratio >= 0.0015  # ~0.15% pixels
        is_correct = not marked_wrong

        # confidence is higher when far from threshold
        if marked_wrong:
            confidence = min(1.0, (red_ratio - 0.0015) / 0.01 + 0.5)
        else:
            confidence = min(1.0, (0.0015 - red_ratio) / 0.0015 * 0.5 + 0.5)

        preds.append(MarkPrediction(position=pos, is_correct=is_correct, confidence=confidence, red_ratio=red_ratio))

    return preds
