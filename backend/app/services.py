import io
import json
import os
import re
import uuid
import difflib
import time
import logging
from typing import Any, Dict, List, Optional, Tuple

from .db import db, utcnow_iso
from .normalize import normalize_answer
from .pdf_gen import ExerciseRow, render_dictation_pdf
from PIL import Image, ImageOps, ImageDraw, ImageFont, ImageStat
from fastapi import UploadFile
from .baidu_ocr import recognize_edu_test
import numpy as np


def _extract_date_from_ocr(ocr_raw: Dict[str, Any]) -> Optional[str]:
    """
    Extract date/time information from OCR results.

    Looks for patterns like:
    - 2024年1月15日
    - 2024-01-15
    - 2024/01/15
    - 1月15日
    - 01-15
    - 01/15

    Returns the first matched date string, or None if not found.
    """
    pages = ocr_raw.get("pages") or []
    all_text = []

    # Collect all OCR text from all pages
    for page in pages:
        raw = page.get("raw") or {}
        words = raw.get("words_result") or raw.get("data") or []
        for word in words:
            if isinstance(word, dict):
                text = word.get("words") or ""
                if text:
                    all_text.append(str(text))

    # Join all text with spaces
    full_text = " ".join(all_text)

    # Try various date patterns (in order of preference)
    patterns = [
        r"(\d{4}年\d{1,2}月\d{1,2}日)",  # 2024年1月15日
        r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})",  # 2024-01-15 or 2024/01/15
        r"(\d{1,2}月\d{1,2}日)",  # 1月15日
        r"(\d{1,2}[-/]\d{1,2})",  # 01-15 or 01/15 (need context to confirm it's a date)
    ]

    for pattern in patterns:
        match = re.search(pattern, full_text)
        if match:
            return match.group(1)

    return None


def apply_white_balance(img_bytes: bytes) -> bytes:
    """
    Apply white balance to image to correct color cast and improve clarity.

    Args:
        img_bytes: Original image bytes

    Returns:
        White balanced image bytes
    """
    try:
        img = Image.open(io.BytesIO(img_bytes))
        img = ImageOps.exif_transpose(img)

        # Convert to RGB if needed
        if img.mode != 'RGB':
            img = img.convert('RGB')

        # Calculate average values for each channel
        img_array = np.array(img, dtype=np.float32)
        avg_r = np.mean(img_array[:, :, 0])
        avg_g = np.mean(img_array[:, :, 1])
        avg_b = np.mean(img_array[:, :, 2])

        # Gray world assumption: scale each channel
        gray = (avg_r + avg_g + avg_b) / 3

        # Avoid division by zero
        scale_r = gray / avg_r if avg_r > 0 else 1.0
        scale_g = gray / avg_g if avg_g > 0 else 1.0
        scale_b = gray / avg_b if avg_b > 0 else 1.0

        # Apply scaling (clamped to prevent overflow)
        img_array[:, :, 0] = np.clip(img_array[:, :, 0] * scale_r, 0, 255)
        img_array[:, :, 1] = np.clip(img_array[:, :, 1] * scale_g, 0, 255)
        img_array[:, :, 2] = np.clip(img_array[:, :, 2] * scale_b, 0, 255)

        # Convert back to PIL Image
        balanced_img = Image.fromarray(img_array.astype(np.uint8))

        # Save to bytes
        output = io.BytesIO()
        balanced_img.save(output, format='JPEG', quality=95)
        return output.getvalue()

    except Exception as e:
        logging.getLogger("uvicorn.error").warning(f"White balance failed: {e}, using original image")
        return img_bytes


def _extract_question_number(text: str) -> Optional[int]:
    """Extract question number from text like '13.猪:' or '1.尾巴:' or '2农场;养殖场:'."""
    text = (text or "").strip()
    # Match patterns like "13.猪:" or "1.尾巴:" or "2农场;" (number followed by delimiter or chinese)
    m = re.match(r'^(\d+)[\s.．。]', text)
    if m:
        return int(m.group(1))
    # Also match "2农场" (number directly followed by chinese characters)
    m = re.match(r'^(\d+)(?=[\u4e00-\u9fff])', text)
    if m:
        return int(m.group(1))
    return None


def _extract_question_positions(words: List[Dict]) -> List[Dict]:
    """Extract question numbers and positions from print text in OCR results."""
    questions = []
    for w in words:
        if w.get("words_type") != "print":
            continue

        text = w.get("words", "")
        q_num = _extract_question_number(text)
        if q_num is not None:
            loc = w.get("location", {})
            questions.append({
                "q_num": q_num,
                "text": text,
                "top": loc.get("top", 0),
                "left": loc.get("left", 0),
                "location": loc
            })

    return sorted(questions, key=lambda x: x["top"])


def _merge_words_to_lines(words: List[Dict], merge_threshold: float = 0.4) -> List[Dict[str, Any]]:
    """Merge words into lines based on vertical proximity.

    Args:
        words: List of word dicts with 'text', 'top', 'left', 'width', 'height'
        merge_threshold: Fraction of line height to use as vertical merge threshold (default 0.4)

    Returns:
        List of line dicts with 'text', 'bbox', 'words'
    """
    if not words:
        return []

    words_sorted = sorted(words, key=lambda w: (w["top"], w["left"]))
    rows: List[Dict[str, Any]] = []

    for w in words_sorted:
        if not w.get("text"):
            continue

        if not rows:
            rows.append({"words": [w], "top": w["top"], "height": w["height"]})
            continue

        last = rows[-1]
        line_h = max(float(last["height"]), float(w["height"]), 1.0)
        top_diff = abs(float(w["top"]) - float(last["top"]))
        threshold = line_h * merge_threshold

        if top_diff <= threshold:
            # Merge to same row
            last["words"].append(w)
            last["top"] = min(float(last["top"]), float(w["top"]))
            last["height"] = max(float(last["height"]), float(w["height"]))
        else:
            # New row
            rows.append({"words": [w], "top": w["top"], "height": w["height"]})

    # Convert rows to lines
    lines: List[Dict[str, Any]] = []
    for row in rows:
        ws = row["words"]
        ws.sort(key=lambda w: w["left"])
        text = " ".join([str(w["text"]) for w in ws]).strip()
        if not text:
            continue

        left = min(float(w["left"]) for w in ws)
        top = min(float(w["top"]) for w in ws)
        right = max(float(w["left"]) + float(w["width"]) for w in ws)
        bottom = max(float(w["top"]) + float(w["height"]) for w in ws)
        lines.append({
            "text": text,
            "bbox": [left, top, right, bottom],
            "words": ws,
            "top": top,  # Add explicit top for sorting
        })

    return lines


def _attach_kb_matches(conn, base_id: int, items: List[Dict]) -> List[Dict]:
    """Attach knowledge base match info to AI-extracted items."""
    out: List[Dict] = []
    for it in items:
        student_text = str(it.get("student_text") or "").strip()
        zh_hint = str(it.get("zh_hint") or "").strip()
        cleaned_student = re.sub(r"^\s*(英文[:：]?\s*)", "", student_text)
        norm = normalize_answer(cleaned_student) if cleaned_student else ""
        row = None
        if norm or zh_hint:
            row = conn.execute(
                """
                SELECT * FROM knowledge_items
                WHERE base_id=?
                  AND (
                    (normalized_answer=? AND ?<>'')
                    OR (lower(en_text)=? AND ?<>'')
                    OR (trim(zh_hint)=? AND ?<>'')
                  )
                LIMIT 1
                """,
                (
                    base_id,
                    norm,
                    norm,
                    cleaned_student.lower(),
                    cleaned_student,
                    zh_hint,
                    zh_hint,
                ),
            ).fetchone()
        if not row and norm and len(norm) >= 6:
            row = conn.execute(
                """
                SELECT * FROM knowledge_items
                WHERE base_id=? AND normalized_answer LIKE ?
                LIMIT 1
                """,
                (base_id, f"%{norm}%"),
            ).fetchone()
        if not row and norm and len(norm) >= 6:
            row = conn.execute(
                """
                SELECT * FROM knowledge_items
                WHERE base_id=? AND ? LIKE '%' || normalized_answer || '%'
                LIMIT 1
                """,
                (base_id, norm),
            ).fetchone()
        hit = dict(row) if row else None
        item = dict(it)
        item["kb_hit"] = bool(hit)
        item["matched_item_id"] = int(hit["id"]) if hit else None
        item["matched_en_text"] = hit["en_text"] if hit else ""
        item["matched_type"] = hit["type"] if hit else ""
        out.append(item)
    return out


def _load_ai_config() -> Dict[str, Any]:
    path = os.environ.get("EL_AI_CONFIG_PATH") or os.path.join(os.path.dirname(__file__), "ai_config.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _is_header_hint(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    patterns = ("默写", "听写", "单词", "短语", "句子")
    if any(p in t for p in patterns) and ("个" in t or "句" in t or "：" in t or ":" in t):
        return True
    if re.match(r"^[一二三四五六七八九十]\s*[、.．]", t):
        return True
    return False


def _match_session_by_items(conn, student_id: int, base_id: int, items: List[Dict]) -> Optional[Dict]:
    """Try to match extracted items to an existing practice session."""
    matched_ids = []
    for it in items:
        mid = it.get("matched_item_id")
        if mid:
            matched_ids.append(int(mid))
    matched_ids = list(dict.fromkeys(matched_ids))[:200]
    if not matched_ids:
        return None

    placeholders = ",".join(["?"] * len(matched_ids))
    sql = f"""
    SELECT
      ps.id,
      ps.created_at,
      ps.status,
      COUNT(1) AS hit_count,
      (SELECT COUNT(1) FROM exercise_items ei2 WHERE ei2.session_id = ps.id) AS total_count
    FROM practice_sessions ps
    JOIN exercise_items ei ON ei.session_id = ps.id
    WHERE ps.student_id=?
      AND ps.base_id=?
      AND ei.item_id IN ({placeholders})
    GROUP BY ps.id
    ORDER BY hit_count DESC, ps.created_at DESC
    LIMIT 1
    """
    row = conn.execute(sql, [student_id, base_id] + matched_ids).fetchone()
    if not row:
        return None
    total = int(row["total_count"] or 0)
    hit = int(row["hit_count"] or 0)
    ratio = (hit / total) if total else 0.0
    return {
        "session_id": int(row["id"]),
        "status": row["status"],
        "created_at": row["created_at"],
        "hit_count": hit,
        "total_count": total,
        "match_ratio": ratio,
    }


def _bbox_to_abs(bbox: List[float], w: int, h: int) -> Optional[Tuple[int, int, int, int]]:
    try:
        x1, y1, x2, y2 = [float(v) for v in bbox]
    except Exception:
        return None
    # normalize if needed
    if all(0 <= v <= 1 for v in (x1, y1, x2, y2)):
        scale = 1.0
    elif all(0 <= v <= 100 for v in (x1, y1, x2, y2)):
        scale = 100.0
    elif all(0 <= v <= 1000 for v in (x1, y1, x2, y2)):
        scale = 1000.0
    elif all(0 <= v <= 10000 for v in (x1, y1, x2, y2)):
        scale = 10000.0
    else:
        scale = 0.0
    if scale > 0:
        x1 /= scale
        y1 /= scale
        x2 /= scale
        y2 /= scale
        if x2 <= x1 or y2 <= y1:
            x2 = x1 + x2
            y2 = y1 + y2
        x1 = max(0.0, min(1.0, x1))
        y1 = max(0.0, min(1.0, y1))
        x2 = max(0.0, min(1.0, x2))
        y2 = max(0.0, min(1.0, y2))
        left = int(x1 * w)
        top = int(y1 * h)
        right = int(x2 * w)
        bottom = int(y2 * h)
    else:
        left = int(max(0, min(w, x1)))
        top = int(max(0, min(h, y1)))
        right = int(max(0, min(w, x2)))
        bottom = int(max(0, min(h, y2)))
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def _save_debug_bundle(images: List[bytes], llm_result: Dict[str, Any], ocr_result: Dict[str, Any]) -> None:
    """
    Save debug bundle with original raw data from LLM and OCR services.

    Args:
        images: List of image bytes
        llm_result: Result from analyze_freeform_sheet with {"items": ..., "raw_llm": ...}
        ocr_result: Result from recognize_edu_test with {"pages": ...}
    """
    debug_dir = os.path.join(MEDIA_DIR, "uploads", "debug_last")
    os.makedirs(debug_dir, exist_ok=True)
    # overwrite last bundle
    for i, b in enumerate(images, start=1):
        with open(os.path.join(debug_dir, f"input_{i}.jpg"), "wb") as f:
            f.write(b)

    # Save LLM raw data (original JSON from LLM response)
    llm_raw = llm_result.get("raw_llm") if isinstance(llm_result, dict) else {}
    with open(os.path.join(debug_dir, "llm_raw.json"), "w", encoding="utf-8") as f:
        json.dump(llm_raw or {}, f, ensure_ascii=False, indent=2)

    # Save OCR raw data (original JSON from OCR API, one per page)
    ocr_raw = {"pages": []}
    if isinstance(ocr_result, dict) and "pages" in ocr_result:
        for page in ocr_result["pages"]:
            if isinstance(page, dict) and "raw" in page:
                ocr_raw["pages"].append({
                    "page_index": page.get("page_index", 0),
                    "raw": page["raw"]
                })
    with open(os.path.join(debug_dir, "ocr_raw.json"), "w", encoding="utf-8") as f:
        json.dump(ocr_raw, f, ensure_ascii=False, indent=2)

    with open(os.path.join(debug_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({"saved_at": utcnow_iso(), "image_count": len(images)}, f, ensure_ascii=False, indent=2)


def _bbox_top_norm(it: Dict) -> float:
    """Return normalized top y (0..1) for sorting."""
    bbox = it.get("handwriting_bbox") or it.get("line_bbox") or it.get("bbox")
    if not (isinstance(bbox, list) and len(bbox) == 4):
        return 1.0
    try:
        x1, y1, x2, y2 = [float(v) for v in bbox]
    except Exception:
        return 1.0
    # Normalize if looks like 0..100/1000/10000
    if all(0 <= v <= 1 for v in (y1, y2)):
        scale = 1.0
    elif all(0 <= v <= 100 for v in (y1, y2)):
        scale = 100.0
    elif all(0 <= v <= 1000 for v in (y1, y2)):
        scale = 1000.0
    elif all(0 <= v <= 10000 for v in (y1, y2)):
        scale = 10000.0
    else:
        return 1.0
    y1 /= scale
    y2 /= scale
    if y2 <= y1:
        return max(0.0, min(1.0, y1))
    return max(0.0, min(1.0, y1))

MEDIA_DIR = os.environ.get(
    "EL_MEDIA_DIR",
    os.path.join(os.path.dirname(__file__), "..", "media"),
)


def get_setting(key: str, default: str) -> str:
    with db() as conn:
        row = conn.execute("SELECT value FROM system_settings WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row else default


def set_setting(key: str, value: str) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO system_settings(key, value, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value, utcnow_iso()),
        )


def get_mastery_threshold() -> int:
    try:
        return max(1, int(get_setting("mastery_threshold", "2")))
    except Exception:
        return 2

def ensure_media_dir() -> None:
    os.makedirs(MEDIA_DIR, exist_ok=True)


def _save_crop_images(image_bytes_list: List[bytes], items: List[Dict]) -> None:
    """Attach crop_url to items if bbox/page_index provided."""
    if not items:
        return
    ensure_media_dir()
    crop_dir = os.path.join(MEDIA_DIR, "uploads", "crops")
    os.makedirs(crop_dir, exist_ok=True)

    import logging
    logger = logging.getLogger("uvicorn.error")
    debug_bbox = os.environ.get("EL_DEBUG_BBOX_PROCESSING", "0") == "1"

    images: List[Image.Image] = []
    for b in image_bytes_list:
        try:
            img = Image.open(io.BytesIO(b))
            img = ImageOps.exif_transpose(img)
            images.append(img.convert("RGB"))
        except Exception:
            images.append(None)  # type: ignore

    for it in items:
        # Try handwriting_bbox first (most accurate), then line_bbox, then bbox fallback
        bbox = it.get("handwriting_bbox") or it.get("line_bbox") or it.get("bbox")
        if not (isinstance(bbox, list) and len(bbox) == 4):
            continue
        try:
            page_index = int(it.get("page_index") or 0)
        except Exception:
            page_index = 0
        if page_index < 0 or page_index >= len(images) or images[page_index] is None:
            continue
        img = images[page_index]
        w, h = img.size
        x1 = float(bbox[0])
        y1 = float(bbox[1])
        x2 = float(bbox[2])
        y2 = float(bbox[3])

        if debug_bbox:
            logger.info(f"[BBOX DEBUG] Position {it.get('position')}: Original bbox={bbox}, image_size=({w},{h})")

        # Detect if bbox is in pixels or normalized coordinates
        # If all values > 1, assume pixels; otherwise assume normalized (0-1 or 0-100 or 0-1000)
        if all(abs(v) > 1 for v in (x1, y1, x2, y2)):
            # Pixel coordinates - use directly
            if debug_bbox:
                logger.info(f"[BBOX DEBUG] Detected pixel coordinates")

            # Check if bbox is in [x, y, width, height] format
            if x2 < x1 or y2 < y1:
                if debug_bbox:
                    logger.info(f"[BBOX DEBUG] Converting from w/h format to corner format")
                if x2 < x1:
                    x2 = x1 + x2
                if y2 < y1:
                    y2 = y1 + y2

            # Clamp to image bounds
            left = int(max(0, min(w, x1)))
            top = int(max(0, min(h, y1)))
            right = int(max(0, min(w, x2)))
            bottom = int(max(0, min(h, y2)))

            if debug_bbox:
                logger.info(f"[BBOX DEBUG] Position {it.get('position')}: Direct pixels=({left},{top},{right},{bottom})")
        else:
            # Normalized coordinates (0-1 or 0-100 or 0-1000 or 0-10000)
            if debug_bbox:
                logger.info(f"[BBOX DEBUG] Detected normalized coordinates")

            if all(0 <= v <= 1 for v in (x1, y1, x2, y2)):
                scale = 1.0
            elif all(0 <= v <= 100 for v in (x1, y1, x2, y2)):
                scale = 100.0
            elif all(0 <= v <= 1000 for v in (x1, y1, x2, y2)):
                scale = 1000.0
            elif all(0 <= v <= 10000 for v in (x1, y1, x2, y2)):
                scale = 10000.0
            else:
                scale = 0.0

            if scale > 0:
                x1 /= scale
                y1 /= scale
                x2 /= scale
                y2 /= scale

                # Check if bbox is in [x, y, width, height] format instead of [x1, y1, x2, y2]
                # Use AND condition: both x2 and y2 should be smaller to confidently detect w/h format
                if x2 <= x1 and y2 <= y1:
                    if debug_bbox:
                        logger.info(f"[BBOX DEBUG] Detected w/h format: converting ({x1},{y1},{x2},{y2}) to corner format")
                    x2 = x1 + x2
                    y2 = y1 + y2
                elif x2 < x1 or y2 < y1:
                    # Likely invalid bbox from AI, try to fix
                    if debug_bbox:
                        logger.warning(f"[BBOX DEBUG] Invalid bbox detected: x2={x2} < x1={x1} or y2={y2} < y1={y1}, attempting fix")
                    # Swap if needed
                    if x2 < x1:
                        x1, x2 = x2, x1
                    if y2 < y1:
                        y1, y2 = y2, y1

                x1 = max(0.0, min(1.0, x1))
                y1 = max(0.0, min(1.0, y1))
                x2 = max(0.0, min(1.0, x2))
                y2 = max(0.0, min(1.0, y2))

                # 添加边距以避免截断（X方向扩展更多，Y方向略微扩展）
                margin_x = (x2 - x1) * 0.15  # X方向扩展15%
                margin_y = (y2 - y1) * 0.10  # Y方向扩展10%
                x1 = max(0.0, x1 - margin_x)
                y1 = max(0.0, y1 - margin_y)
                x2 = min(1.0, x2 + margin_x)
                y2 = min(1.0, y2 + margin_y)

                left = int(x1 * w)
                top = int(y1 * h)
                right = int(x2 * w)
                bottom = int(y2 * h)
            else:
                # Assume absolute pixels, clamp to image size.
                left = int(max(0, min(w, x1)))
                top = int(max(0, min(h, y1)))
                right = int(max(0, min(w, x2)))
                bottom = int(max(0, min(h, y2)))

        if debug_bbox:
            logger.info(f"[BBOX DEBUG] Position {it.get('position')}: Final pixels=({left},{top},{right},{bottom}), size=({right-left}x{bottom-top})")
        if right <= left or bottom <= top:
            continue
        # Avoid huge crops when answer is blank and line bbox is noisy.
        if not str(it.get("student_text") or "").strip():
            if (bottom - top) > int(h * 0.18) or (right - left) > int(w * 0.9):
                continue
        try:
            crop = img.crop((left, top, right, bottom))
        except Exception:
            continue
        # tighten crop to actual ink area when possible
        try:
            gray = crop.convert("L")
            mask = gray.point(lambda p: 255 if p < 230 else 0)
            bbox2 = mask.getbbox()
            if bbox2:
                pad = 6
                l2, t2, r2, b2 = bbox2
                l2 = max(0, l2 - pad)
                t2 = max(0, t2 - pad)
                r2 = min(crop.width, r2 + pad)
                b2 = min(crop.height, b2 + pad)
                crop = crop.crop((l2, t2, r2, b2))
                # Remove underline-like horizontal strokes near bottom.
                mask2 = mask.crop((l2, t2, r2, b2))
                w2, h2 = mask2.size
                pixels = mask2.load()
                underline_y = None
                for y in range(h2 - 1, int(h2 * 0.4), -1):
                    dark = 0
                    for x in range(w2):
                        if pixels[x, y] != 0:
                            dark += 1
                    if dark / max(1, w2) > 0.75:
                        underline_y = y
                        break
                if underline_y is not None and underline_y > 3:
                    crop = crop.crop((0, 0, w2, max(1, underline_y - 2)))
        except Exception:
            pass
        fname = f"crop_{uuid.uuid4().hex}.jpg"
        out_path = os.path.join(crop_dir, fname)
        try:
            crop.save(out_path, format="JPEG", quality=90)
        except Exception:
            continue
        it["crop_url"] = f"/media/uploads/crops/{fname}"


def _save_debug_overlay(image_bytes_list: List[bytes], items: List[Dict]) -> List[str]:
    """Save debug overlay images with bbox markers."""
    if not items:
        return []
    ensure_media_dir()
    debug_dir = os.path.join(MEDIA_DIR, "uploads", "debug")
    os.makedirs(debug_dir, exist_ok=True)
    mode = (os.environ.get("EL_AI_DEBUG_BBOX_MODE") or "active").lower()

    import logging
    logger = logging.getLogger("uvicorn.error")
    debug_bbox = os.environ.get("EL_DEBUG_BBOX_PROCESSING", "0") == "1"

    images: List[Image.Image] = []
    for b in image_bytes_list:
        try:
            img = Image.open(io.BytesIO(b))
            img = ImageOps.exif_transpose(img)
            images.append(img.convert("RGB"))
        except Exception:
            images.append(None)  # type: ignore

    try:
        font = ImageFont.load_default()
    except Exception:
        font = None

    debug_urls: List[str] = []
    for page_index, img in enumerate(images):
        if img is None:
            continue
        draw = ImageDraw.Draw(img)
        w, h = img.size
        for it in items:
            try:
                pidx = int(it.get("page_index") or 0)
            except Exception:
                pidx = 0
            if pidx != page_index:
                continue
            keys = []
            if mode == "all":
                keys = [("handwriting_bbox", "green"), ("line_bbox", "red"), ("bbox", "blue")]
            else:
                kind = it.get("bbox_kind")
                if kind == "handwriting":
                    keys = [("handwriting_bbox", "green")]
                elif kind == "line":
                    keys = [("line_bbox", "red")]
                elif kind == "fallback":
                    keys = [("bbox", "blue")]
            for key, color in keys:
                bbox = it.get(key)
                if not (isinstance(bbox, list) and len(bbox) == 4):
                    continue
                x1, y1, x2, y2 = [float(v) for v in bbox]

                if debug_bbox and key == "bbox":
                    logger.info(f"[BBOX DEBUG OVERLAY] Position {it.get('position')}, key={key}: Original={bbox}")

                # Detect if bbox is in pixels or normalized coordinates
                if all(abs(v) > 1 for v in (x1, y1, x2, y2)):
                    # Pixel coordinates - use directly
                    if x2 < x1 or y2 < y1:
                        if x2 < x1:
                            x2 = x1 + x2
                        if y2 < y1:
                            y2 = y1 + y2
                    left = int(max(0, min(w, x1)))
                    top = int(max(0, min(h, y1)))
                    right = int(max(0, min(w, x2)))
                    bottom = int(max(0, min(h, y2)))
                else:
                    # Normalized coordinates
                    scale = 1.0
                    if not all(0 <= v <= 1 for v in (x1, y1, x2, y2)):
                        if all(0 <= v <= 100 for v in (x1, y1, x2, y2)):
                            scale = 100.0
                        elif all(0 <= v <= 1000 for v in (x1, y1, x2, y2)):
                            scale = 1000.0
                        elif all(0 <= v <= 10000 for v in (x1, y1, x2, y2)):
                            scale = 10000.0
                        else:
                            scale = 0.0
                    if scale > 0:
                        x1, y1, x2, y2 = x1 / scale, y1 / scale, x2 / scale, y2 / scale

                        # Check if bbox is in [x, y, width, height] format instead of [x1, y1, x2, y2]
                        # Use AND condition: both x2 and y2 should be smaller to confidently detect w/h format
                        if x2 <= x1 and y2 <= y1:
                            if debug_bbox and key == "bbox":
                                logger.info(f"[BBOX DEBUG OVERLAY] Detected w/h format: converting ({x1},{y1},{x2},{y2}) to corner format")
                            x2 = x1 + x2
                            y2 = y1 + y2
                        elif x2 < x1 or y2 < y1:
                            # Likely invalid bbox from AI, try to fix
                            if debug_bbox and key == "bbox":
                                logger.warning(f"[BBOX DEBUG OVERLAY] Invalid bbox: x2={x2} < x1={x1} or y2={y2} < y1={y1}, attempting fix")
                            # Swap if needed
                            if x2 < x1:
                                x1, x2 = x2, x1
                            if y2 < y1:
                                y1, y2 = y2, y1

                        x1 = max(0.0, min(1.0, x1))
                        y1 = max(0.0, min(1.0, y1))
                        x2 = max(0.0, min(1.0, x2))
                        y2 = max(0.0, min(1.0, y2))
                        left = int(x1 * w)
                        top = int(y1 * h)
                        right = int(x2 * w)
                        bottom = int(y2 * h)
                    else:
                        left = int(max(0, min(w, x1)))
                        top = int(max(0, min(h, y1)))
                        right = int(max(0, min(w, x2)))
                        bottom = int(max(0, min(h, y2)))

                if debug_bbox and key == "bbox":
                    logger.info(f"[BBOX DEBUG OVERLAY] Position {it.get('position')}, key={key}: Final pixels=({left},{top},{right},{bottom})")

                if right <= left or bottom <= top:
                    continue
                draw.rectangle([left, top, right, bottom], outline=color, width=2)
                label = f"{it.get('position')}"
                if font:
                    draw.text((left + 2, max(0, top - 12)), label, fill=color, font=font)
        fname = f"debug_{page_index}_{uuid.uuid4().hex}.jpg"
        out_path = os.path.join(debug_dir, fname)
        try:
            img.save(out_path, format="JPEG", quality=88)
            debug_urls.append(f"/media/uploads/debug/{fname}")
        except Exception:
            continue
    return debug_urls


def analyze_ai_photos_from_debug(student_id: int, base_id: int) -> Dict:
    """Load debug data from disk and process (for UI testing without calling LLM/OCR)."""
    debug_dir = os.path.join(MEDIA_DIR, "uploads", "debug_last")

    logger = logging.getLogger("uvicorn.error")
    logger.info(f"[AI GRADING DEBUG] Loading from {debug_dir}")

    # Check if debug files exist
    if not os.path.exists(debug_dir):
        raise ValueError("调试目录不存在，请先运行一次正常识别")

    llm_path = os.path.join(debug_dir, "llm_raw.json")
    ocr_path = os.path.join(debug_dir, "ocr_raw.json")
    meta_path = os.path.join(debug_dir, "meta.json")

    if not os.path.exists(llm_path) or not os.path.exists(ocr_path):
        raise ValueError("调试数据不完整，请先运行一次正常识别")

    # Load JSON files
    with open(llm_path, "r", encoding="utf-8") as f:
        llm_raw = json.load(f)
    with open(ocr_path, "r", encoding="utf-8") as f:
        ocr_raw = json.load(f)
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    # Load images
    img_bytes_list: List[bytes] = []
    image_count = meta.get("image_count", 0)
    for i in range(1, image_count + 1):
        img_path = os.path.join(debug_dir, f"input_{i}.jpg")
        if os.path.exists(img_path):
            with open(img_path, "rb") as f:
                img_bytes_list.append(f.read())

    # Apply white balance for grading/cropping (same as normal mode)
    logger.info("[AI GRADING DEBUG] Applying white balance...")
    wb_img_bytes_list: List[bytes] = []
    for img_bytes in img_bytes_list:
        wb_bytes = apply_white_balance(img_bytes)
        wb_img_bytes_list.append(wb_bytes)
    logger.info(f"[AI GRADING DEBUG] White balance applied to {len(wb_img_bytes_list)} images")

    # Parse LLM raw data (which is now in the original sections format)
    items_raw = []
    sections = llm_raw.get("sections")
    if isinstance(sections, list):
        # Flatten sections into items (preserve section order and titles)
        for sec in sections:
            if not isinstance(sec, dict):
                continue
            sec_title = sec.get("title") or ""
            sec_type = sec.get("type") or ""
            sec_items = sec.get("items") or []
            # Mark first item of this section with title
            for idx, it in enumerate(sec_items):
                if not isinstance(it, dict):
                    continue
                # Convert short field names to long names
                items_raw.append({
                    "q": it.get("q"),
                    "section_title": sec_title if idx == 0 else "",  # Only first item has title
                    "section_type": sec_type,
                    "zh_hint": it.get("hint") or "",
                    "student_text": it.get("ans") or "",
                    "is_correct": it.get("ok"),
                    "confidence": it.get("conf"),
                    "page_index": it.get("pg") or 0,
                    "note": it.get("note") or "",
                })
    else:
        # Fallback to old items format if sections not found
        items_raw = llm_raw.get("items") or []

    logger.info(f"[AI GRADING DEBUG] Loaded {len(img_bytes_list)} images, LLM items: {len(items_raw)}")

    logger.info(f"[AI GRADING] LLM items: {len(items_raw)}; OCR pages: {len(ocr_raw.get('pages', []))}")

    # Parse LLM items
    items: List[Dict] = []
    for idx, it in enumerate(items_raw, start=1):
        if not isinstance(it, dict):
            continue
        zh_hint = it.get("zh_hint") or ""
        if _is_header_hint(str(zh_hint)):
            continue
        # Use LLM's question number, fallback to large number to sort at end
        position = int(it.get("q") or 9000 + idx)
        conf_val = it.get("confidence")
        items.append(
            {
                "position": position,
                "section_type": it.get("section_type") or "",
                "section_title": it.get("section_title") or "",
                "zh_hint": zh_hint,
                "llm_text": it.get("student_text") or "",
                "is_correct": it.get("is_correct") if "is_correct" in it else None,
                "confidence": float(conf_val) if conf_val is not None else None,
                "page_index": int(it.get("page_index") or 0),
                "handwriting_bbox": it.get("handwriting_bbox"),
                "line_bbox": it.get("line_bbox"),
                "note": it.get("note") or "",
            }
        )

    # Don't sort - preserve section order from LLM output
    # (Each section's position/q starts from 1, so sorting by position would mix sections)
    # Log section information for debugging
    last_section_type = None
    section_count = 0
    for it in items:
        current_section_type = it.get("section_type") or ""
        if current_section_type != last_section_type and it.get("section_title"):
            last_section_type = current_section_type
            section_count += 1
            logger.info(f"[AI GRADING] Section {section_count}: {it.get('section_title')} (type={current_section_type}, first_q={it.get('position')})")

    logger.info(f"[AI GRADING] Total sections: {section_count}, total items: {len(items)}")

    # Build OCR words per page
    ocr_pages = ocr_raw.get("pages") or []
    ocr_by_page: Dict[int, List[Dict]] = {}
    for p in ocr_pages:
        idx = int(p.get("page_index") or 0)
        raw = p.get("raw") or {}
        words = raw.get("words_result") or raw.get("data") or []
        if isinstance(words, list):
            ocr_by_page[idx] = words

    # OCR matching (same as analyze_ai_photos)
    def _build_ocr_lines(words: List[Dict[str, Any]], items: List[Dict] = None) -> List[Dict[str, Any]]:
        handwriting_words = []
        for wobj in words:
            if wobj.get("words_type") != "handwriting":
                continue
            loc = wobj.get("location") or {}
            handwriting_words.append({
                "text": wobj.get("words") or "",
                "left": float(loc.get("left", 0)),
                "top": float(loc.get("top", 0)),
                "width": float(loc.get("width", 0)),
                "height": float(loc.get("height", 0)),
            })
        has_multiword = False
        if items:
            for it in items:
                student_text = str(it.get("llm_text") or it.get("student_text") or "")
                if len(student_text.split()) >= 2:
                    has_multiword = True
                    break
        if has_multiword:
            merge_threshold = float(os.environ.get("EL_OCR_PHRASE_MERGE_THRESHOLD", "0.5"))
        else:
            merge_threshold = float(os.environ.get("EL_OCR_WORD_MERGE_THRESHOLD", "0.1"))
        lines = _merge_words_to_lines(handwriting_words, merge_threshold=merge_threshold)
        lines.sort(key=lambda ln: (ln.get("top", 0), ln["bbox"][0]))
        return lines

    def _abs_to_norm_bbox(bbox: List[float], w: int, h: int) -> Optional[List[float]]:
        if not w or not h:
            return None
        left, top, right, bottom = bbox
        return [
            max(0.0, min(1.0, left / w)),
            max(0.0, min(1.0, top / h)),
            max(0.0, min(1.0, right / w)),
            max(0.0, min(1.0, bottom / h)),
        ]

    ocr_match_thr = float(os.environ.get("EL_OCR_MATCH_THRESHOLD", "0.6"))
    question_positions_by_page: Dict[int, Dict[int, float]] = {}
    for page_idx, words in ocr_by_page.items():
        questions = _extract_question_positions(words)
        question_positions_by_page[page_idx] = {q["q_num"]: q["top"] for q in questions}

    ocr_lines_by_page: Dict[int, List[Dict[str, Any]]] = {}
    for page_idx, words in ocr_by_page.items():
        lines = _build_ocr_lines(words, items=items)
        lines = [ln for ln in lines if re.search(r"[A-Za-z]", ln["text"])]
        lines.sort(key=lambda ln: (ln["bbox"][1], ln["bbox"][0]))
        ocr_lines_by_page[page_idx] = lines

    ocr_used: Dict[int, set] = {page_idx: set() for page_idx in ocr_lines_by_page.keys()}

    for it in items:
        page_idx = int(it.get("page_index") or 0)
        lines = ocr_lines_by_page.get(page_idx) or []
        q_num = int(it.get("q") or 0)
        it["ocr_text"] = ""
        it["match_method"] = "no_match"

        if not lines:
            continue

        llm_text_norm = normalize_answer(str(it.get("llm_text") or ""))

        if not llm_text_norm:
            continue

        best_idx = None
        best_ratio = 0.0
        match_method = "no_match"

        for idx_ln, ln in enumerate(lines):
            if idx_ln in ocr_used.get(page_idx, set()):
                continue
            eng_words = [w for w in (ln.get("words") or []) if re.search(r"[A-Za-z]", str(w.get("text") or ""))]
            cand_text = " ".join([str(w.get("text") or "") for w in eng_words]).strip() if eng_words else ln["text"]
            cand_norm = normalize_answer(cand_text)
            if not cand_norm:
                continue
            ratio = difflib.SequenceMatcher(None, llm_text_norm, cand_norm).ratio() if llm_text_norm else 0.0
            if ratio > best_ratio:
                best_ratio = ratio
                best_idx = idx_ln

        if best_ratio >= ocr_match_thr:
            match_method = f"text_sim_{best_ratio:.2f}"
        else:
            q_positions = question_positions_by_page.get(page_idx, {})
            if q_num in q_positions:
                expected_top = q_positions[q_num]
                closest_idx = None
                closest_dist = float('inf')
                for idx_ln, ln in enumerate(lines):
                    if idx_ln in ocr_used.get(page_idx, set()):
                        continue
                    ln_top = ln.get("top", ln["bbox"][1])
                    dist = abs(ln_top - expected_top)
                    if dist < closest_dist and dist < 100:
                        closest_dist = dist
                        closest_idx = idx_ln
                if closest_idx is not None:
                    best_idx = closest_idx
                    best_ratio = 0.0
                    match_method = f"position_{closest_dist:.0f}px"

        if best_idx is None:
            for idx_ln, ln in enumerate(lines):
                if idx_ln in ocr_used.get(page_idx, set()):
                    continue
                best_idx = idx_ln
                best_ratio = 0.0
                match_method = "sequential_fallback"
                break

        if best_idx is None:
            continue

        ocr_used.setdefault(page_idx, set()).add(best_idx)
        best = lines[best_idx]
        eng_words = [w for w in (best.get("words") or []) if re.search(r"[A-Za-z]", str(w.get("text") or ""))]
        if eng_words:
            it["ocr_text"] = " ".join([str(w.get("text") or "") for w in eng_words]).strip()
            left = min(float(w["left"]) for w in eng_words)
            top = min(float(w["top"]) for w in eng_words)
            right = max(float(w["left"]) + float(w["width"]) for w in eng_words)
            bottom = max(float(w["top"]) + float(w["height"]) for w in eng_words)
            best_bbox = [left, top, right, bottom]
        else:
            it["ocr_text"] = best["text"]
            best_bbox = best["bbox"]
        it["ocr_match_ratio"] = best_ratio
        it["match_method"] = match_method
        if best_ratio < ocr_match_thr and not match_method.startswith("position"):
            it["note"] = (it.get("note") or "") + " ocr_match_low"
        try:
            img = Image.open(io.BytesIO(img_bytes_list[page_idx]))
            img = ImageOps.exif_transpose(img)
            w, h = img.size
        except Exception:
            w, h = 1, 1
        norm_bbox = _abs_to_norm_bbox(best_bbox, w, h)
        if norm_bbox and not (isinstance(it.get("handwriting_bbox"), list) and len(it.get("handwriting_bbox")) == 4):
            it["handwriting_bbox"] = norm_bbox
        if norm_bbox and not (isinstance(it.get("line_bbox"), list) and len(it.get("line_bbox")) == 4):
            it["line_bbox"] = norm_bbox

    # Attach KB matches
    for it in items:
        it["student_text"] = it.get("llm_text") or ""
    with db() as conn:
        items = _attach_kb_matches(conn, base_id, items)

    # Compare LLM vs OCR
    sim_thr = float(os.environ.get("EL_MATCH_SIM_THRESHOLD", "0.88"))
    for it in items:
        llm_text = normalize_answer(str(it.get("llm_text") or ""))
        ocr_text = normalize_answer(str(it.get("ocr_text") or ""))

        if llm_text and ocr_text:
            ratio = difflib.SequenceMatcher(None, llm_text, ocr_text).ratio()
            it["consistency_ok"] = ratio >= sim_thr
        elif not llm_text and not ocr_text:
            ratio = 1.0
            it["consistency_ok"] = True
        else:
            ratio = 0.0
            it["consistency_ok"] = False

        it["consistency_ratio"] = ratio

        if not it["consistency_ok"] and (llm_text or ocr_text):
            if it.get("confidence") is not None:
                it["confidence"] = max(0.0, float(it.get("confidence")) * 0.6)
            else:
                it["note"] = (it.get("note") or "") + " missing_confidence"

    # Generate graded images (same as analyze_ai_photos)
    graded_image_urls: List[str] = []

    def draw_checkmark(draw, bbox, color="#19c37d", size=40, width=6):
        """Draw a checkmark (✓) to the right of the answer bbox."""
        x1, y1, x2, y2 = bbox
        bbox_w = x2 - x1
        bbox_h = y2 - y1
        start_x = x2 + 8
        start_y = y1 - 6
        auto_size = max(30, min(50, int(bbox_h * 0.8)))
        p1 = (start_x, start_y + int(auto_size * 0.55))
        p2 = (start_x + int(auto_size * 0.35), start_y + auto_size)
        p3 = (start_x + auto_size, start_y)
        draw.line([p1, p2], fill=color, width=width)
        draw.line([p2, p3], fill=color, width=width)

    def draw_red_circle(draw, bbox, color="#ef4444", width=6):
        """Draw an ellipse around the answer bbox (slightly larger than bbox)."""
        x1, y1, x2, y2 = bbox
        bbox_w = x2 - x1
        bbox_h = y2 - y1
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        radius_x = bbox_w / 2 + 6
        radius_y = bbox_h / 2 + 6
        ellipse_bbox = [cx - radius_x, cy - radius_y, cx + radius_x, cy + radius_y]
        draw.ellipse(ellipse_bbox, outline=color, width=width)

    # Use white-balanced images for graded output
    for page_idx, img_bytes in enumerate(wb_img_bytes_list):
        try:
            img = Image.open(io.BytesIO(img_bytes))
            img = ImageOps.exif_transpose(img)
            draw = ImageDraw.Draw(img)
            w, h = img.size
            for it in items:
                if int(it.get("page_index") or 0) != page_idx:
                    continue
                bbox = it.get("handwriting_bbox") or it.get("line_bbox")
                if not (isinstance(bbox, list) and len(bbox) == 4):
                    continue
                abs_bbox = _bbox_to_abs(bbox, w, h)
                if not abs_bbox:
                    continue
                is_correct = it.get("is_correct")
                if is_correct is None:
                    color = "#f59e0b"
                    draw.rectangle(abs_bbox, outline=color, width=3)
                elif is_correct:
                    draw_checkmark(draw, abs_bbox, color="#19c37d", width=6)
                else:
                    draw_red_circle(draw, abs_bbox, color="#ef4444", width=6)
            graded_fname = f"graded_{student_id}_{page_idx + 1}_{uuid.uuid4().hex}.jpg"
            graded_path = os.path.join(MEDIA_DIR, "uploads", "graded", graded_fname)
            img.save(graded_path, format="JPEG", quality=90)
            graded_image_urls.append(f"/media/uploads/graded/{graded_fname}")
        except Exception as e:
            logger.error(f"[AI GRADING] Failed to generate graded image: {e}")
            graded_image_urls.append("")

    # Save debug overlay
    debug_overlay_urls = _save_debug_overlay(img_bytes_list, items)

    # Save crop images
    _save_crop_images(wb_img_bytes_list, items)

    # Match session
    matched_session = None
    with db() as conn:
        matched_session = _match_session_by_items(conn, student_id, base_id, items)

    # Extract date from OCR results
    extracted_date = _extract_date_from_ocr(ocr_raw)
    if extracted_date:
        logger.info(f"[AI GRADING DEBUG] Extracted date from OCR: {extracted_date}")

    return {
        "items": items,
        "image_urls": [],
        "graded_image_urls": graded_image_urls,
        "debug_overlay_urls": debug_overlay_urls,
        "image_count": len(img_bytes_list),
        "matched_session": matched_session,
        "extracted_date": extracted_date,
    }


def analyze_ai_photos(student_id: int, base_id: int, uploads: List[UploadFile]) -> Dict:
    """LLM analysis + Baidu OCR recognition with merging."""
    if not uploads:
        raise ValueError("no files uploaded")

    from .openai_vision import analyze_freeform_sheet, is_configured  # type: ignore

    if not is_configured():
        raise ValueError("AI 配置不可用（缺少 API KEY）")

    ensure_media_dir()
    os.makedirs(os.path.join(MEDIA_DIR, "uploads"), exist_ok=True)
    os.makedirs(os.path.join(MEDIA_DIR, "uploads", "graded"), exist_ok=True)

    logger = logging.getLogger("uvicorn.error")

    img_bytes_list: List[bytes] = []
    saved_paths: List[str] = []
    for idx, upload in enumerate(uploads, start=1):
        ext = os.path.splitext(upload.filename or "")[1].lower() or ".jpg"
        fname = f"ai_sheet_{student_id}_{idx}_{uuid.uuid4().hex}{ext}"
        out_path = os.path.join(MEDIA_DIR, "uploads", fname)
        img_bytes = upload.file.read()
        img_bytes_list.append(img_bytes)
        saved_paths.append(out_path)
        with open(out_path, "wb") as f:
            f.write(img_bytes)

    # Apply white balance for grading/cropping (LLM/OCR use original)
    logger.info("[AI GRADING] Applying white balance...")
    wb_img_bytes_list: List[bytes] = []
    for img_bytes in img_bytes_list:
        wb_bytes = apply_white_balance(img_bytes)
        wb_img_bytes_list.append(wb_bytes)
    logger.info(f"[AI GRADING] White balance applied to {len(wb_img_bytes_list)} images")

    # parallel LLM + OCR
    import concurrent.futures
    timeout_llm = int(os.environ.get("EL_AI_TIMEOUT_SECONDS", "30"))
    timeout_ocr = int(os.environ.get("EL_OCR_TIMEOUT_SECONDS", "30"))
    logger.info(f"[AI GRADING] Timeout settings: LLM={timeout_llm}s, OCR={timeout_ocr}s")
    cfg = _load_ai_config()
    ocr_cfg = cfg.get("ocr", {}) or {}
    endpoint = ocr_cfg.get("endpoint") or "https://aip.baidubce.com/rest/2.0/ocr/v1/doc_analysis"
    ocr_params = ocr_cfg.get("params") or {}

    llm_raw: Dict[str, Any] = {}
    ocr_raw: Dict[str, Any] = {}

    def _run_llm():
        return analyze_freeform_sheet(img_bytes_list, return_raw=True)

    def _run_ocr():
        return recognize_edu_test(img_bytes_list, timeout=timeout_ocr, endpoint=endpoint, params=ocr_params)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        fut_llm = ex.submit(_run_llm)
        fut_ocr = ex.submit(_run_ocr)
        llm_start = time.time()
        try:
            llm_raw = fut_llm.result(timeout=timeout_llm)
            llm_elapsed = time.time() - llm_start
            logger.info(f"[AI GRADING] LLM completed in {llm_elapsed:.1f}s")
        except Exception as e:
            llm_elapsed = time.time() - llm_start
            logger.error(f"[AI GRADING] LLM failed after {llm_elapsed:.1f}s: {e}")
            raise ValueError(f"LLM 识别失败: {e}")
        ocr_start = time.time()
        try:
            ocr_raw = fut_ocr.result(timeout=timeout_ocr)
            ocr_elapsed = time.time() - ocr_start
            logger.info(f"[AI GRADING] OCR completed in {ocr_elapsed:.1f}s")
        except Exception as e:
            ocr_elapsed = time.time() - ocr_start
            logger.error(f"[AI GRADING] OCR failed after {ocr_elapsed:.1f}s: {e}")
            raise ValueError(f"OCR 识别失败: {e}")

    items_raw = llm_raw.get("items") or []

    logger.info(f"[AI GRADING] LLM items: {len(items_raw)}; OCR pages: {len(ocr_raw.get('pages', []))}")

    # Parse LLM items
    items: List[Dict] = []
    for idx, it in enumerate(items_raw, start=1):
        if not isinstance(it, dict):
            continue
        zh_hint = it.get("zh_hint") or ""
        if _is_header_hint(str(zh_hint)):
            continue
        # Use LLM's question number, fallback to large number to sort at end
        position = int(it.get("q") or 9000 + idx)
        conf_val = it.get("confidence")
        items.append(
            {
                "position": position,
                "section_type": it.get("section_type") or "",
                "section_title": it.get("section_title") or "",
                "zh_hint": zh_hint,
                "llm_text": it.get("student_text") or "",
                "is_correct": it.get("is_correct") if "is_correct" in it else None,
                "confidence": float(conf_val) if conf_val is not None else None,
                "page_index": int(it.get("page_index") or 0),
                "handwriting_bbox": it.get("handwriting_bbox"),
                "line_bbox": it.get("line_bbox"),
                "note": it.get("note") or "",
            }
        )

    # Don't sort - preserve section order from LLM output
    # (Each section's position/q starts from 1, so sorting by position would mix sections)
    # Log section information for debugging
    last_section_type = None
    section_count = 0
    for it in items:
        current_section_type = it.get("section_type") or ""
        if current_section_type != last_section_type and it.get("section_title"):
            last_section_type = current_section_type
            section_count += 1
            logger.info(f"[AI GRADING] Section {section_count}: {it.get('section_title')} (type={current_section_type}, first_q={it.get('position')})")

    logger.info(f"[AI GRADING] Total sections: {section_count}, total items: {len(items)}")

    # Build OCR words per page
    ocr_pages = ocr_raw.get("pages") or []
    ocr_by_page: Dict[int, List[Dict]] = {}
    for p in ocr_pages:
        idx = int(p.get("page_index") or 0)
        raw = p.get("raw") or {}
        words = raw.get("words_result") or raw.get("data") or []
        if isinstance(words, list):
            ocr_by_page[idx] = words

    # Map OCR lines to each item (bbox comes from OCR; fuzzy match to LLM text).
    def _build_ocr_lines(words: List[Dict[str, Any]], items: List[Dict] = None) -> List[Dict[str, Any]]:
        """Build OCR lines from handwriting words.

        For single-word questions (WORD type), keep each word separate.
        For multi-word questions (PHRASE/SENTENCE), allow limited merging.

        Returns lines sorted by vertical position.
        """
        # Separate handwriting from print
        handwriting_words = []
        for wobj in words:
            # Only process handwriting (student answers), skip print (questions)
            if wobj.get("words_type") != "handwriting":
                continue

            loc = wobj.get("location") or {}
            handwriting_words.append({
                "text": wobj.get("words") or "",
                "left": float(loc.get("left", 0)),
                "top": float(loc.get("top", 0)),
                "width": float(loc.get("width", 0)),
                "height": float(loc.get("height", 0)),
            })

        # Detect if we have multi-word answers in LLM results
        has_multiword = False
        if items:
            for it in items:
                student_text = str(it.get("llm_text") or it.get("student_text") or "")
                # Check if any answer has 2+ words
                if len(student_text.split()) >= 2:
                    has_multiword = True
                    break

        # For single-word sections: use very strict threshold (almost no merge)
        # For multi-word sections: use moderate threshold
        if has_multiword:
            merge_threshold = float(os.environ.get("EL_OCR_PHRASE_MERGE_THRESHOLD", "0.5"))
        else:
            # Single words: use very small threshold to prevent any merging
            merge_threshold = float(os.environ.get("EL_OCR_WORD_MERGE_THRESHOLD", "0.1"))

        lines = _merge_words_to_lines(handwriting_words, merge_threshold=merge_threshold)

        # Sort by vertical position
        lines.sort(key=lambda ln: (ln.get("top", 0), ln["bbox"][0]))
        return lines


    def _abs_to_norm_bbox(bbox: List[float], w: int, h: int) -> Optional[List[float]]:
        if not w or not h:
            return None
        left, top, right, bottom = bbox
        return [
            max(0.0, min(1.0, left / w)),
            max(0.0, min(1.0, top / h)),
            max(0.0, min(1.0, right / w)),
            max(0.0, min(1.0, bottom / h)),
        ]

    ocr_match_thr = float(os.environ.get("EL_OCR_MATCH_THRESHOLD", "0.6"))

    # Extract question positions from print text (NEW: for position-based matching)
    question_positions_by_page: Dict[int, Dict[int, float]] = {}
    for page_idx, words in ocr_by_page.items():
        questions = _extract_question_positions(words)
        # Build map: question_number -> top position
        question_positions_by_page[page_idx] = {q["q_num"]: q["top"] for q in questions}

    # Precompute OCR lines by page and track usage to avoid duplicates.
    ocr_lines_by_page: Dict[int, List[Dict[str, Any]]] = {}
    for page_idx, words in ocr_by_page.items():
        lines = _build_ocr_lines(words, items=items)
        # Only keep lines that look like English answers
        lines = [ln for ln in lines if re.search(r"[A-Za-z]", ln["text"])]
        lines.sort(key=lambda ln: (ln["bbox"][1], ln["bbox"][0]))
        ocr_lines_by_page[page_idx] = lines

    ocr_used: Dict[int, set] = {page_idx: set() for page_idx in ocr_lines_by_page.keys()}

    for it in items:
        page_idx = int(it.get("page_index") or 0)
        lines = ocr_lines_by_page.get(page_idx) or []
        q_num = int(it.get("q") or 0)
        it["ocr_text"] = ""
        it["match_method"] = "no_match"

        if not lines:
            continue

        llm_text_norm = normalize_answer(str(it.get("llm_text") or ""))

        # Skip empty answers (student didn't write anything)
        if not llm_text_norm:
            continue

        best_idx = None
        best_ratio = 0.0
        match_method = "no_match"

        # Strategy 1: Text similarity match (highest priority)
        for idx_ln, ln in enumerate(lines):
            if idx_ln in ocr_used.get(page_idx, set()):
                continue
            eng_words = [w for w in (ln.get("words") or []) if re.search(r"[A-Za-z]", str(w.get("text") or ""))]
            cand_text = " ".join([str(w.get("text") or "") for w in eng_words]).strip() if eng_words else ln["text"]
            cand_norm = normalize_answer(cand_text)
            if not cand_norm:
                continue
            ratio = difflib.SequenceMatcher(None, llm_text_norm, cand_norm).ratio() if llm_text_norm else 0.0
            if ratio > best_ratio:
                best_ratio = ratio
                best_idx = idx_ln

        if best_ratio >= ocr_match_thr:
            match_method = f"text_sim_{best_ratio:.2f}"
        else:
            # Strategy 2: Position-based match (medium priority, NEW)
            q_positions = question_positions_by_page.get(page_idx, {})
            if q_num in q_positions:
                expected_top = q_positions[q_num]
                closest_idx = None
                closest_dist = float('inf')

                # Find OCR line closest to expected question position
                for idx_ln, ln in enumerate(lines):
                    if idx_ln in ocr_used.get(page_idx, set()):
                        continue

                    ln_top = ln.get("top", ln["bbox"][1])
                    # Answer should be at or below question (within ~100px)
                    dist = abs(ln_top - expected_top)

                    # Prefer answers near the question
                    if dist < closest_dist and dist < 100:
                        closest_dist = dist
                        closest_idx = idx_ln

                if closest_idx is not None:
                    best_idx = closest_idx
                    best_ratio = 0.0  # Position-based, not text-based
                    match_method = f"position_{closest_dist:.0f}px"

        # Strategy 3: Sequential fallback (lowest priority)
        if best_idx is None:
            for idx_ln, ln in enumerate(lines):
                if idx_ln in ocr_used.get(page_idx, set()):
                    continue
                best_idx = idx_ln
                best_ratio = 0.0
                match_method = "sequential_fallback"
                break

        if best_idx is None:
            continue

        ocr_used.setdefault(page_idx, set()).add(best_idx)
        best = lines[best_idx]
        eng_words = [w for w in (best.get("words") or []) if re.search(r"[A-Za-z]", str(w.get("text") or ""))]
        if eng_words:
            it["ocr_text"] = " ".join([str(w.get("text") or "") for w in eng_words]).strip()
            left = min(float(w["left"]) for w in eng_words)
            top = min(float(w["top"]) for w in eng_words)
            right = max(float(w["left"]) + float(w["width"]) for w in eng_words)
            bottom = max(float(w["top"]) + float(w["height"]) for w in eng_words)
            best_bbox = [left, top, right, bottom]
        else:
            it["ocr_text"] = best["text"]
            best_bbox = best["bbox"]
        it["ocr_match_ratio"] = best_ratio
        it["match_method"] = match_method
        if best_ratio < ocr_match_thr and not match_method.startswith("position"):
            it["note"] = (it.get("note") or "") + " ocr_match_low"
        try:
            img = Image.open(io.BytesIO(img_bytes_list[page_idx]))
            img = ImageOps.exif_transpose(img)
            w, h = img.size
        except Exception:
            w, h = 1, 1
        norm_bbox = _abs_to_norm_bbox(best_bbox, w, h)
        if norm_bbox and not (isinstance(it.get("handwriting_bbox"), list) and len(it.get("handwriting_bbox")) == 4):
            it["handwriting_bbox"] = norm_bbox
        if norm_bbox and not (isinstance(it.get("line_bbox"), list) and len(it.get("line_bbox")) == 4):
            it["line_bbox"] = norm_bbox


    # Attach KB matches based on chosen (default LLM) text
    for it in items:
        it["student_text"] = it.get("llm_text") or ""
    with db() as conn:
        items = _attach_kb_matches(conn, base_id, items)

    # Compare LLM vs OCR
    sim_thr = float(os.environ.get("EL_MATCH_SIM_THRESHOLD", "0.88"))
    for it in items:
        llm_text = normalize_answer(str(it.get("llm_text") or ""))
        ocr_text = normalize_answer(str(it.get("ocr_text") or ""))

        # Calculate similarity
        if llm_text and ocr_text:
            ratio = difflib.SequenceMatcher(None, llm_text, ocr_text).ratio()
            it["consistency_ok"] = ratio >= sim_thr
        elif not llm_text and not ocr_text:
            # Both empty (unanswered) - consistent
            ratio = 1.0
            it["consistency_ok"] = True
        else:
            # One empty, one not - inconsistent
            ratio = 0.0
            it["consistency_ok"] = False

        it["consistency_ratio"] = ratio

        # Lower confidence if inconsistent
        if not it["consistency_ok"] and (llm_text or ocr_text):
            if it.get("confidence") is not None:
                it["confidence"] = max(0.0, float(it.get("confidence")) * 0.6)
            else:
                it["note"] = (it.get("note") or "") + " missing_confidence"

    # Anomaly detection and error isolation
    logger.info("[AI GRADING] Running anomaly detection...")

    # 1. Detect duplicate answers (same student_text in multiple questions)
    answer_positions: Dict[str, List[int]] = {}
    for it in items:
        text = normalize_answer(str(it.get("student_text") or ""))
        if text:  # Ignore empty answers
            pos = it.get("position", 0)
            answer_positions.setdefault(text, []).append(pos)

    # Mark duplicates with low confidence
    for text, positions in answer_positions.items():
        if len(positions) > 1:
            logger.warning(f"[AI GRADING] Duplicate answer '{text}' at positions: {positions}")

            # Find items with this duplicate answer and sort by confidence
            dup_items = []
            for it in items:
                if normalize_answer(str(it.get("student_text") or "")) == text:
                    dup_items.append(it)

            # Sort by confidence (None treated as 0.0), keep the highest confidence one
            dup_items.sort(key=lambda x: x.get("confidence") or 0.0, reverse=True)

            for idx, it in enumerate(dup_items):
                # Lower confidence for all duplicates
                if it.get("confidence") is not None:
                    it["confidence"] = max(0.0, float(it.get("confidence")) * 0.5)
                # Add warning note
                if "重复答案" not in (it.get("note") or ""):
                    it["note"] = (it.get("note") or "") + f" 重复答案(出现{len(positions)}次)"

                # Clear bbox for all except the highest confidence one to prevent wrong crop display
                if idx > 0:  # Not the first (highest confidence) one
                    it["handwriting_bbox"] = None
                    it["line_bbox"] = None
                    it["bbox"] = None
                    if "bbox已清除" not in (it.get("note") or ""):
                        it["note"] = (it.get("note") or "") + " bbox已清除(低置信度重复)"

    # 2. Detect answer-hint type mismatch
    for it in items:
        section_type = it.get("section_type") or ""
        student_text = str(it.get("student_text") or "").strip()

        if student_text and section_type:
            word_count = len(student_text.split())

            # WORD section should have 1-2 words
            if section_type == "WORD" and word_count > 2:
                logger.warning(f"[AI GRADING] Q{it.get('position')}: WORD section has multi-word answer '{student_text}'")
                if it.get("confidence") is not None:
                    it["confidence"] = max(0.0, float(it.get("confidence")) * 0.7)
                if "类型异常" not in (it.get("note") or ""):
                    it["note"] = (it.get("note") or "") + " 类型异常(单词题出现短语)"

            # PHRASE section should have 2+ words
            elif section_type == "PHRASE" and word_count == 1:
                logger.warning(f"[AI GRADING] Q{it.get('position')}: PHRASE section has single-word answer '{student_text}'")
                if it.get("confidence") is not None:
                    it["confidence"] = max(0.0, float(it.get("confidence")) * 0.8)
                if "类型异常" not in (it.get("note") or ""):
                    it["note"] = (it.get("note") or "") + " 类型异常(短语题只有单词)"

    # 3. Prefer OCR over LLM when inconsistent and OCR has better position match
    for it in items:
        if not it.get("consistency_ok"):
            match_method = it.get("match_method", "")
            llm_text = str(it.get("llm_text") or "")
            ocr_text = str(it.get("ocr_text") or "")

            # If OCR matched by position (high confidence), prefer OCR
            if match_method.startswith("position_") and ocr_text:
                logger.info(f"[AI GRADING] Q{it.get('position')}: Using OCR '{ocr_text}' over LLM '{llm_text}' (position-based match)")
                it["student_text"] = ocr_text
                if "OCR纠错" not in (it.get("note") or ""):
                    it["note"] = (it.get("note") or "") + f" OCR纠错(LLM误识别为'{llm_text}')"

    # Re-match KB after OCR correction
    with db() as conn:
        items = _attach_kb_matches(conn, base_id, items)

    logger.info("[AI GRADING] Anomaly detection complete")

    # Generate overlay images (green checkmark for correct, red circle for incorrect)
    graded_image_urls: List[str] = []

    def draw_checkmark(draw, bbox, color="#19c37d", size=40, width=6):
        """Draw a checkmark (✓) to the right of the answer bbox."""
        x1, y1, x2, y2 = bbox
        bbox_w = x2 - x1
        bbox_h = y2 - y1

        # Position checkmark to the right of bbox (similar to reference code)
        # x + w + 8, y - 6
        start_x = x2 + 8
        start_y = y1 - 6

        # Auto-scale size based on bbox height (but with min/max limits)
        auto_size = max(30, min(50, int(bbox_h * 0.8)))

        # Three points forming a checkmark (similar to reference code)
        # p1: left point
        # p2: bottom point
        # p3: top-right point
        p1 = (start_x, start_y + int(auto_size * 0.55))
        p2 = (start_x + int(auto_size * 0.35), start_y + auto_size)
        p3 = (start_x + auto_size, start_y)

        # Draw two lines forming the checkmark
        draw.line([p1, p2], fill=color, width=width)
        draw.line([p2, p3], fill=color, width=width)

    def draw_red_circle(draw, bbox, color="#ef4444", width=6):
        """Draw an ellipse around the answer bbox (slightly larger than bbox)."""
        x1, y1, x2, y2 = bbox
        bbox_w = x2 - x1
        bbox_h = y2 - y1

        # Calculate center
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2

        # Ellipse semi-axes (slightly larger than bbox: +6px on each side)
        # Similar to reference: axes = (w // 2 + 6, h // 2 + 6)
        radius_x = bbox_w / 2 + 6
        radius_y = bbox_h / 2 + 6

        # PIL ellipse bbox: [left, top, right, bottom]
        ellipse_bbox = [
            cx - radius_x,
            cy - radius_y,
            cx + radius_x,
            cy + radius_y
        ]

        draw.ellipse(ellipse_bbox, outline=color, width=width)

    # Use white-balanced images for graded output
    for page_idx, img_bytes in enumerate(wb_img_bytes_list):
        try:
            img = Image.open(io.BytesIO(img_bytes))
            img = ImageOps.exif_transpose(img)
            draw = ImageDraw.Draw(img)
            w, h = img.size
            for it in items:
                if int(it.get("page_index") or 0) != page_idx:
                    continue
                bbox = it.get("handwriting_bbox") or it.get("line_bbox")
                if not (isinstance(bbox, list) and len(bbox) == 4):
                    continue
                abs_bbox = _bbox_to_abs(bbox, w, h)
                if not abs_bbox:
                    continue
                is_correct = it.get("is_correct")
                if is_correct is None:
                    # Unknown: draw orange rectangle
                    color = "#f59e0b"
                    draw.rectangle(abs_bbox, outline=color, width=3)
                elif is_correct:
                    # Correct: draw green checkmark to the right
                    draw_checkmark(draw, abs_bbox, color="#19c37d", width=6)
                else:
                    # Incorrect: draw red ellipse around the answer
                    draw_red_circle(draw, abs_bbox, color="#ef4444", width=6)
            graded_fname = f"graded_{student_id}_{page_idx + 1}_{uuid.uuid4().hex}.jpg"
            graded_path = os.path.join(MEDIA_DIR, "uploads", "graded", graded_fname)
            img.save(graded_path, format="JPEG", quality=90)
            graded_image_urls.append(f"/media/uploads/graded/{graded_fname}")
        except Exception as e:
            logger.error(f"[AI GRADING] Failed to generate graded image: {e}")
            graded_image_urls.append("")

    # Match to existing session
    matched_session = None
    with db() as conn:
        matched_session = _match_session_by_items(conn, student_id, base_id, items)

    # Extract date from OCR results
    extracted_date = _extract_date_from_ocr(ocr_raw)
    if extracted_date:
        logger.info(f"[AI GRADING] Extracted date from OCR: {extracted_date}")

    if os.environ.get("EL_AI_DEBUG_SAVE", "1") == "1":
        _save_debug_bundle(img_bytes_list, llm_raw or {}, ocr_raw or {})

    image_urls = [f"/media/uploads/{os.path.basename(p)}" for p in saved_paths]
    return {
        "items": items,
        "image_urls": image_urls,
        "graded_image_urls": graded_image_urls,
        "image_count": len(saved_paths),
        "matched_session": matched_session,
        "extracted_date": extracted_date,
    }


def confirm_ai_extracted(student_id: int, base_id: int, items: List[Dict]) -> Dict:
    """Create session/submission from AI-extracted items and update stats."""
    use_items = [it for it in items if bool(it.get("include", True))]
    if not use_items:
        raise ValueError("没有可入库的题目")

    params_json = json.dumps(
        {"mode": "EXTERNAL_AI", "source": "AI_EXTRACT"},
        ensure_ascii=False,
    )
    submitted_at = utcnow_iso()

    with db() as conn:
        cur = conn.execute(
            """
            INSERT INTO practice_sessions(student_id, base_id, status, params_json, created_at, completed_at)
            VALUES(?,?,?,?,?,?)
            """,
            (student_id, base_id, "COMPLETED", params_json, submitted_at, submitted_at),
        )
        session_id = int(cur.lastrowid)

        submission_cur = conn.execute(
            """
            INSERT INTO submissions(session_id, submitted_at, image_path, text_raw, source)
            VALUES(?,?,?,?,?)
            """,
            (session_id, submitted_at, None, None, "AI_EXTRACT"),
        )
        submission_id = int(submission_cur.lastrowid)

        # store raw ai/ocr choices for audit
        try:
            conn.execute(
                "UPDATE submissions SET text_raw=? WHERE id=?",
                (json.dumps({"items": use_items}, ensure_ascii=False), submission_id),
            )
        except Exception:
            pass

        results = []
        for idx, it in enumerate(use_items, start=1):
            # Always use enumeration index for position in the new session
            position = idx
            matched_item_id = it.get("matched_item_id")
            item_row = None
            if matched_item_id:
                item_row = conn.execute(
                    "SELECT * FROM knowledge_items WHERE id=?",
                    (int(matched_item_id),),
                ).fetchone()

            en_text = ""
            zh_hint = str(it.get("zh_hint") or "")
            typ = "WORD"
            normalized = ""
            if item_row:
                en_text = item_row["en_text"]
                zh_hint = item_row["zh_hint"] or zh_hint
                typ = item_row["type"]
                normalized = item_row["normalized_answer"]
            else:
                en_text = str(it.get("student_text") or "")
                normalized = normalize_answer(en_text)

            cur = conn.execute(
                """
                INSERT INTO exercise_items(session_id, item_id, position, type, en_text, zh_hint, normalized_answer)
                VALUES(?,?,?,?,?,?,?)
                """,
                (
                    session_id,
                    int(item_row["id"]) if item_row else None,
                    position,
                    typ,
                    en_text,
                    zh_hint,
                    normalized,
                ),
            )
            exercise_item_id = int(cur.lastrowid)

            is_correct = 1 if bool(it.get("is_correct", True)) else 0
            conn.execute(
                """
                INSERT INTO practice_results(submission_id, session_id, exercise_item_id,
                                           answer_raw, answer_norm, is_correct, error_type, created_at)
                VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    submission_id,
                    session_id,
                    exercise_item_id,
                    it.get("student_text"),
                    normalize_answer(str(it.get("student_text") or "")),
                    is_correct,
                    "AI_EXTRACT",
                    submitted_at,
                ),
            )

            _update_stats(
                conn,
                student_id,
                int(item_row["id"]) if item_row else None,
                is_correct,
                submitted_at,
            )

            results.append({"position": position, "is_correct": bool(is_correct)})

    correct = sum(1 for r in results if r["is_correct"])
    total = len(results)
    return {
        "session_id": session_id,
        "submission_id": submission_id,
        "total": total,
        "correct": correct,
        "accuracy": (correct / total) if total else 0.0,
    }


def bootstrap_single_child(student_name: str, grade_code: str) -> Dict[str, int]:
    """第一次使用初始化：创建默认学生与默认资料库。

    返回：student_id, base_id
    """
    with db() as conn:
        # create student
        cur = conn.execute(
            "INSERT INTO students(name, grade_code, created_at) VALUES(?,?,?)",
            (student_name, grade_code, utcnow_iso()),
        )
        student_id = cur.lastrowid

        # create default base
        base_name = f"Default ({grade_code})"
        cur = conn.execute(
            "INSERT INTO knowledge_bases(name, grade_code, is_system, created_at) VALUES(?,?,0,?)",
            (base_name, grade_code, utcnow_iso()),
        )
        base_id = cur.lastrowid

        conn.execute(
            "INSERT OR REPLACE INTO student_base_progress(student_id, base_id, current_unit_code) VALUES(?,?,NULL)",
            (student_id, base_id),
        )

    return {"student_id": student_id, "base_id": base_id}


def list_bases(grade_code: Optional[str] = None) -> List[Dict]:
    with db() as conn:
        if grade_code:
            rows = conn.execute(
                "SELECT * FROM knowledge_bases WHERE grade_code=? ORDER BY id DESC",
                (grade_code,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM knowledge_bases ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


def create_base(name: str, grade_code: str, is_system: bool = False) -> int:
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO knowledge_bases(name, grade_code, is_system, created_at) VALUES(?,?,?,?)",
            (name, grade_code, 1 if is_system else 0, utcnow_iso()),
        )
        return int(cur.lastrowid)


def upsert_items(base_id: int, items: List[Dict], mode: str = "skip") -> Dict[str, int]:
    """批量导入知识点。

    mode:
      - skip: 若唯一键冲突则跳过（文档默认）
      - update: 允许更新 zh_hint / difficulty_tag / normalized_answer

    注意：MVP 不做 silent overwrite，update 仍会保留 updated_at 供追溯。
    """
    inserted = 0
    skipped = 0
    updated = 0

    with db() as conn:
        for it in items:
            unit_code = it.get("unit_code")
            typ = it["type"].upper()
            en_text = it["en_text"].strip()
            zh_hint = it.get("zh_hint")
            difficulty_tag = it.get("difficulty_tag", "write").lower()
            if difficulty_tag not in ("write", "recognize"):
                difficulty_tag = "write"

            normalized = it.get("normalized_answer") or normalize_answer(en_text)

            try:
                conn.execute(
                    """
                    INSERT INTO knowledge_items(
                      base_id, unit_code, type, en_text, zh_hint, difficulty_tag,
                      normalized_answer, is_enabled, source, created_at, updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        base_id,
                        unit_code,
                        typ,
                        en_text,
                        zh_hint,
                        difficulty_tag,
                        normalized,
                        1,
                        it.get("source", "IMPORT"),
                        utcnow_iso(),
                        utcnow_iso(),
                    ),
                )
                inserted += 1
            except Exception:
                # unique constraint likely
                if mode == "update":
                    conn.execute(
                        """
                        UPDATE knowledge_items
                        SET zh_hint=?, difficulty_tag=?, normalized_answer=?, updated_at=?
                        WHERE base_id=? AND unit_code IS ? AND type=? AND en_text=?
                        """,
                        (
                            zh_hint,
                            difficulty_tag,
                            normalized,
                            utcnow_iso(),
                            base_id,
                            unit_code,
                            typ,
                            en_text,
                        ),
                    )
                    updated += 1
                else:
                    skipped += 1

    return {"inserted": inserted, "updated": updated, "skipped": skipped}


def _select_items_for_session(
    student_id: int,
    base_id: int,
    unit_scope: Optional[List[str]],
    mix_ratio: Dict[str, int],
    total_count: int,
) -> List[Dict]:
    """按规则优先：最近错 > 长期未练 > 新引入。"""
    # expand ratio to per type counts
    ratio_total = sum(mix_ratio.values()) or 1
    counts = {
        t: max(0, int(round(total_count * (mix_ratio.get(t, 0) / ratio_total))))
        for t in ("WORD", "PHRASE", "SENTENCE", "GRAMMAR")
    }
    # adjust rounding so sum == total_count
    while sum(counts.values()) < total_count:
        for t in ("WORD", "PHRASE", "SENTENCE"):
            counts[t] += 1
            if sum(counts.values()) == total_count:
                break

    selected: List[Dict] = []
    with db() as conn:
        for typ, need in counts.items():
            if need <= 0:
                continue

            params = [student_id, base_id, typ]
            where_unit = ""
            if unit_scope:
                placeholders = ",".join(["?"] * len(unit_scope))
                where_unit = f" AND ki.unit_code IN ({placeholders})"
                params.extend(unit_scope)

            # only write items are eligible
            q = f"""
            SELECT
              ki.*, sis.wrong_attempts, sis.consecutive_wrong, sis.last_attempt_at
            FROM knowledge_items ki
            LEFT JOIN student_item_stats sis
              ON sis.item_id = ki.id AND sis.student_id = ?
            WHERE ki.base_id=?
              AND ki.type=?
              AND ki.difficulty_tag='write'
              AND ki.is_enabled=1
              {where_unit}
            ORDER BY
              COALESCE(sis.consecutive_wrong, 0) DESC,
              COALESCE(sis.wrong_attempts, 0) DESC,
              CASE WHEN sis.last_attempt_at IS NULL THEN 0 ELSE 1 END ASC,
              COALESCE(sis.last_attempt_at, '0000') ASC,
              ki.id DESC
            LIMIT ?
            """
            cur = conn.execute(q, params + [need * 3])
            rows = [dict(r) for r in cur.fetchall()]

            # remove duplicates across types/session by en_text
            for r in rows:
                if len([x for x in selected if x["en_text"] == r["en_text"]]) > 0:
                    continue
                selected.append(r)
                if len([x for x in selected if x["type"] == typ]) >= need:
                    break

    # if still short, backfill from any type (except grammar by default)
    if len(selected) < total_count:
        with db() as conn:
            need = total_count - len(selected)
            params = [student_id, base_id]
            where_unit = ""
            if unit_scope:
                placeholders = ",".join(["?"] * len(unit_scope))
                where_unit = f" AND ki.unit_code IN ({placeholders})"
                params.extend(unit_scope)
            q = f"""
            SELECT ki.*, sis.wrong_attempts, sis.consecutive_wrong, sis.last_attempt_at
            FROM knowledge_items ki
            LEFT JOIN student_item_stats sis
              ON sis.item_id = ki.id AND sis.student_id = ?
            WHERE ki.base_id=?
              AND ki.difficulty_tag='write'
              AND ki.is_enabled=1
              {where_unit}
            ORDER BY
              COALESCE(sis.consecutive_wrong, 0) DESC,
              COALESCE(sis.wrong_attempts, 0) DESC,
              CASE WHEN sis.last_attempt_at IS NULL THEN 0 ELSE 1 END ASC,
              COALESCE(sis.last_attempt_at, '0000') ASC,
              ki.id DESC
            LIMIT ?
            """
            rows = [dict(r) for r in conn.execute(q, params + [need * 5]).fetchall()]
            for r in rows:
                if any(x["en_text"] == r["en_text"] for x in selected):
                    continue
                selected.append(r)
                if len(selected) >= total_count:
                    break

    return selected[:total_count]

def normalize_unit_scope(unit_scope: Any) -> Optional[List[str]]:
    """Normalize unit scope input.

    Accepts:
      - None / "" -> None
      - "U1,U2" / "U1，U2" / "1,2" / "Unit1 Unit2" -> ["U1","U2"]
      - ["U1","U2"] or ["U1,U2"] -> ["U1","U2"]

    Returns:
      - None if empty
      - List of normalized unit codes like ["U1","U2"] (deduped, order preserved)
    """
    if unit_scope is None:
        return None

    parts: List[str] = []

    if isinstance(unit_scope, str):
        s = unit_scope.strip()
        if not s:
            return None
        parts = re.split(r"[，,;；\s]+", s)
    elif isinstance(unit_scope, (list, tuple, set)):
        for x in unit_scope:
            if x is None:
                continue
            if isinstance(x, str):
                s = x.strip()
                if not s:
                    continue
                parts.extend(re.split(r"[，,;；\s]+", s))
            else:
                parts.append(str(x))
    else:
        parts = [str(unit_scope)]

    out: List[str] = []
    for p in parts:
        p = (p or "").strip()
        if not p:
            continue
        up = p.upper().replace(" ", "")
        # "1" or "UNIT1" -> "U1"
        m = re.match(r"^(?:UNIT)?(\d+)$", up)
        if m:
            out.append("U" + m.group(1))
            continue
        # "U 1" or "U1" -> "U1"
        m = re.match(r"^U(\d+)$", up)
        if m:
            out.append("U" + m.group(1))
            continue
        # fallback: keep uppercase token
        out.append(up)

    # dedupe preserve order
    seen = set()
    res: List[str] = []
    for u in out:
        if u not in seen:
            seen.add(u)
            res.append(u)

    return res or None

def generate_practice_session(
    student_id: int,
    base_id: int,
    unit_scope: Optional[List[str]],
    total_count: int,
    mix_ratio: Dict[str, int],
    title: str = "四年级英语默写单",
) -> Dict:
    ensure_media_dir()

    unit_scope = normalize_unit_scope(unit_scope)

    with db() as conn:
        student = conn.execute("SELECT id FROM students WHERE id=?", (student_id,)).fetchone()
        if not student:
            raise ValueError(f"student_id {student_id} 不存在，请先完成初始化/创建学生。")
        base = conn.execute("SELECT id FROM knowledge_bases WHERE id=?", (base_id,)).fetchone()
        if not base:
            raise ValueError(f"base_id {base_id} 不存在，请先导入或创建知识库。")

    items = _select_items_for_session(
        student_id=student_id,
        base_id=base_id,
        unit_scope=unit_scope,
        mix_ratio=mix_ratio,
        total_count=total_count,
    )

    if not items:
        raise ValueError("所选出题范围内没有可用知识点（请检查 Unit 代码、或先导入知识库）。")

    params_json = json.dumps(
        {
            "unit_scope": unit_scope,
            "total_count": total_count,
            "mix_ratio": mix_ratio,
            "title": title,
        },
        ensure_ascii=False,
    )

    with db() as conn:
        cur = conn.execute(
            """
            INSERT INTO practice_sessions(student_id, base_id, status, params_json, created_at)
            VALUES(?,?,?,?,?)
            """,
            (student_id, base_id, "DRAFT", params_json, utcnow_iso()),
        )
        session_id = int(cur.lastrowid)

        # store exercise items (keep global position order)
        rows_all: List[ExerciseRow] = []
        for idx, it in enumerate(items, start=1):
            conn.execute(
                """
                INSERT INTO exercise_items(session_id, item_id, position, type, en_text, zh_hint, normalized_answer)
                VALUES(?,?,?,?,?,?,?)
                """,
                (
                    session_id,
                    it.get("id"),
                    idx,
                    it.get("type"),
                    it.get("en_text"),
                    it.get("zh_hint"),
                    it.get("normalized_answer"),
                ),
            )
            rows_all.append(
                ExerciseRow(
                    position=idx,
                    zh_hint=it.get("zh_hint") or "",
                    answer_en=it.get("en_text") or "",
                    item_type=it.get("type") or "",
                )
            )

        # group into sections for PDF template
        sections: Dict[str, List[ExerciseRow]] = {"WORD": [], "PHRASE": [], "SENTENCE": []}
        for r in rows_all:
            if r.item_type in sections:
                sections[r.item_type].append(r)
            else:
                # ignore other types in MVP
                pass

        pdf_path = os.path.join(MEDIA_DIR, f"session_{session_id}_practice.pdf")
        ans_path = os.path.join(MEDIA_DIR, f"session_{session_id}_answer.pdf")

        render_dictation_pdf(
            pdf_path,
            title,
            sections,
            show_answers=False,
            footer=f"Session #{session_id}",
        )
        render_dictation_pdf(
            ans_path,
            title + "（答案）",
            sections,
            show_answers=True,
            footer=f"Session #{session_id}",
        )

        conn.execute(
            "UPDATE practice_sessions SET pdf_path=?, answer_pdf_path=? WHERE id=?",
            (pdf_path, ans_path, session_id),
        )

    return {"session_id": session_id, "pdf_path": pdf_path, "answer_pdf_path": ans_path}


def correct_session_manually(
    session_id: int,
    answers_by_pos: Dict[int, str],
    image_path: Optional[str] = None,
    text_raw: Optional[str] = None,
    source: str = "MANUAL",
) -> Dict:
    """家长参与批改：MVP 直接按 position 对齐答案。

    这与文档“规则优先、AI辅助、允许人工兜底”的思路一致。
    """
    submitted_at = utcnow_iso()

    with db() as conn:
        # create submission
        cur = conn.execute(
            """
            INSERT INTO submissions(session_id, submitted_at, image_path, text_raw, source)
            VALUES(?,?,?,?,?)
            """,
            (session_id, submitted_at, image_path, text_raw, source),
        )
        submission_id = int(cur.lastrowid)

        student_row = conn.execute(
            "SELECT student_id FROM practice_sessions WHERE id=?",
            (session_id,),
        ).fetchone()
        student_id = int(student_row["student_id"]) if student_row else 0

        ex_rows = conn.execute(
            "SELECT * FROM exercise_items WHERE session_id=? ORDER BY position ASC",
            (session_id,),
        ).fetchall()

        results = []
        for ex in ex_rows:
            pos = int(ex["position"])
            ans_raw = answers_by_pos.get(pos, "")
            ans_norm = normalize_answer(ans_raw)
            expected = ex["normalized_answer"]
            is_correct = 1 if ans_norm == expected else 0

            error_type = None
            if not is_correct:
                error_type = _infer_error_type(ans_norm, expected)

            conn.execute(
                """
                INSERT INTO practice_results(submission_id, session_id, exercise_item_id,
                                           answer_raw, answer_norm, is_correct, error_type)
                VALUES(?,?,?,?,?,?,?)
                """,
                (
                    submission_id,
                    session_id,
                    ex["id"],
                    ans_raw,
                    ans_norm,
                    is_correct,
                    error_type,
                ),
            )

            _update_stats(conn, student_id, int(ex["item_id"]) if ex["item_id"] is not None else None, is_correct, submitted_at)

            results.append(
                {
                    "position": pos,
                    "expected_en": ex["en_text"],
                    "zh_hint": ex["zh_hint"],
                    "answer_raw": ans_raw,
                    "is_correct": bool(is_correct),
                    "error_type": error_type,
                }
            )

        conn.execute(
            "UPDATE practice_sessions SET status='CORRECTED', corrected_at=? WHERE id=?",
            (submitted_at, session_id),
        )

    correct = sum(1 for r in results if r["is_correct"])
    total = len(results)
    wrong_positions = [r["position"] for r in results if not r["is_correct"]]
    return {
        "submission_id": submission_id,
        "session_id": session_id,
        "total": total,
        "correct": correct,
        "accuracy": (correct / total) if total else 0.0,
        "wrong_positions": wrong_positions,
        "results": results,
    }


def _infer_error_type(answer_norm: str, expected_norm: str) -> str:
    # simplified attribution aligned with doc
    if not answer_norm:
        return "UNKNOWN"

    # word order (for sentence-like answers)
    a_words = answer_norm.split()
    e_words = expected_norm.split()
    if len(a_words) > 1 and sorted(a_words) == sorted(e_words) and a_words != e_words:
        return "WORD_ORDER"

    # spelling: large edit distance / obvious char diff
    if abs(len(answer_norm) - len(expected_norm)) >= 2:
        return "SPELLING"

    # grammar catch-all for sentence mismatch
    if len(e_words) > 2:
        return "GRAMMAR"

    return "SPELLING"




def _update_stats(conn, student_id: int, item_id: Optional[int], is_correct: int, ts: str) -> None:
    """更新 StudentItemStats（MVP 字段集）"""
    if not item_id or not student_id:
        return

    row = conn.execute(
        "SELECT * FROM student_item_stats WHERE student_id=? AND item_id=?",
        (student_id, item_id),
    ).fetchone()

    if row is None:
        conn.execute(
            """
            INSERT INTO student_item_stats(
              student_id, item_id, total_attempts, correct_attempts, wrong_attempts,
              consecutive_correct, consecutive_wrong, last_attempt_at
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                student_id,
                item_id,
                1,
                1 if is_correct else 0,
                0 if is_correct else 1,
                1 if is_correct else 0,
                0 if is_correct else 1,
                ts,
            ),
        )
        return

    total_attempts = int(row["total_attempts"]) + 1
    correct_attempts = int(row["correct_attempts"]) + (1 if is_correct else 0)
    wrong_attempts = int(row["wrong_attempts"]) + (0 if is_correct else 1)

    consecutive_correct = int(row["consecutive_correct"])
    consecutive_wrong = int(row["consecutive_wrong"])
    if is_correct:
        consecutive_correct += 1
        consecutive_wrong = 0
    else:
        consecutive_wrong += 1
        consecutive_correct = 0

    conn.execute(
        """
        UPDATE student_item_stats
        SET total_attempts=?, correct_attempts=?, wrong_attempts=?,
            consecutive_correct=?, consecutive_wrong=?, last_attempt_at=?
        WHERE student_id=? AND item_id=?
        """,
        (
            total_attempts,
            correct_attempts,
            wrong_attempts,
            consecutive_correct,
            consecutive_wrong,
            ts,
            student_id,
            item_id,
        ),
    )


def list_sessions(student_id: int, base_id: int, limit: int = 30) -> List[Dict]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id, status, created_at, pdf_path, answer_pdf_path, corrected_at
            FROM practice_sessions
            WHERE student_id=? AND base_id=?
            ORDER BY id DESC
            LIMIT ?
            """,
            (student_id, base_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def upload_submission_image(session_id: int, upload: UploadFile) -> Dict:
    """拍照上传：MVP 只保存原图，不做自动OCR。"""
    ensure_media_dir()
    import uuid

    ext = os.path.splitext(upload.filename or "")[1].lower() or ".jpg"
    fname = f"submission_{session_id}_{uuid.uuid4().hex}{ext}"
    out_path = os.path.join(MEDIA_DIR, "uploads", fname)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    content = upload.file.read()
    with open(out_path, "wb") as f:
        f.write(content)

    with db() as conn:
        cur = conn.execute(
            """
            INSERT INTO submissions(session_id, submitted_at, image_path, text_raw, source)
            VALUES(?,?,?,?,?)
            """,
            (session_id, utcnow_iso(), out_path, None, "PHOTO"),
        )
        submission_id = int(cur.lastrowid)

    return {"submission_id": submission_id, "image_path": out_path, "note": "MVP 未自动OCR，请在页面中手工录入答案后批改。"}

def upload_marked_submission_image(
    session_id: int,
    uploads: List[UploadFile],
    confirm_mismatch: bool = False,
    allow_external: bool = False,
) -> Dict:
    """Deprecated: kept for compatibility. AI-only extraction, no local OCR fallback."""
    with db() as conn:
        sess = conn.execute(
            "SELECT student_id, base_id FROM practice_sessions WHERE id=?",
            (session_id,),
        ).fetchone()
        if not sess:
            raise ValueError("session not found")
        student_id = int(sess["student_id"])
        base_id = int(sess["base_id"])

    return analyze_ai_photos(student_id, base_id, uploads)



def confirm_mark_grading(submission_id: int, final_by_pos: Dict[int, bool]) -> Dict:
    """将家长确认后的对错入库，并更新统计。"""
    submitted_at = utcnow_iso()
    with db() as conn:
        sub = conn.execute("SELECT session_id FROM submissions WHERE id=?", (submission_id,)).fetchone()
        if not sub:
            raise ValueError("submission not found")
        session_id = int(sub["session_id"])

        student_row = conn.execute("SELECT student_id FROM practice_sessions WHERE id=?", (session_id,)).fetchone()
        student_id = int(student_row["student_id"]) if student_row else 0

        ex_rows = conn.execute(
            "SELECT * FROM exercise_items WHERE session_id=? ORDER BY position ASC",
            (session_id,),
        ).fetchall()

        # clear previous results for this submission if re-confirmed
        conn.execute("DELETE FROM practice_results WHERE submission_id=?", (submission_id,))

        results = []
        for ex in ex_rows:
            pos = int(ex["position"])
            is_correct = 1 if bool(final_by_pos.get(pos, True)) else 0
            error_type = None if is_correct else "WRONG_MARKED"

            conn.execute(
                """
                INSERT INTO practice_results(submission_id, session_id, exercise_item_id,
                                           answer_raw, answer_norm, is_correct, error_type)
                VALUES(?,?,?,?,?,?,?)
                """,
                (submission_id, session_id, ex["id"], None, None, is_correct, error_type),
            )

            _update_stats(
                conn,
                student_id,
                int(ex["item_id"]) if ex["item_id"] is not None else None,
                is_correct,
                submitted_at,
            )

            results.append({"position": pos, "is_correct": bool(is_correct), "error_type": error_type})

        conn.execute(
            "UPDATE practice_sessions SET status='CORRECTED', corrected_at=? WHERE id=?",
            (submitted_at, session_id),
        )

    correct = sum(1 for r in results if r["is_correct"])
    total = len(results)
    return {"submission_id": submission_id, "session_id": session_id, "total": total, "correct": correct, "accuracy": (correct/total) if total else 0.0}



def manual_correct_session(session_id: int, answers: Dict[str, str]) -> Dict:
    answers_by_pos = {int(k): v for k, v in answers.items()}
    data = correct_session_manually(session_id, answers_by_pos)
    return {
        "submission_id": data["submission_id"],
        "session_id": data["session_id"],
        "summary": {
            "total": data["total"],
            "correct": data["correct"],
            "accuracy": data["accuracy"],
            "wrong_positions": data["wrong_positions"],
        },
        "results": data["results"],
    }


def get_system_status(student_id: int, base_id: int) -> Dict:
    with db() as conn:
        latest = conn.execute(
            """
            SELECT id, status, created_at, corrected_at
            FROM practice_sessions
            WHERE student_id=? AND base_id=?
            ORDER BY id DESC
            LIMIT 1
            """,
            (student_id, base_id),
        ).fetchone()

        pending = conn.execute(
            """
            SELECT COUNT(1) AS c
            FROM practice_sessions
            WHERE student_id=? AND base_id=? AND status IN ('DRAFT','PUBLISHED','COMPLETED')
            """,
            (student_id, base_id),
        ).fetchone()

    return {
        "latest_session": dict(latest) if latest else None,
        "pending_correction": int(pending["c"]) if pending else 0,
    }


def get_dashboard(student_id: int, base_id: int, days: int = 30) -> Dict:
    """家长看板（基础版）：已学/已掌握/易错/最近练习/日历"""
    with db() as conn:
        learned = conn.execute(
            """
            SELECT COUNT(1) AS c
            FROM student_item_stats sis
            JOIN knowledge_items ki ON ki.id = sis.item_id
            WHERE sis.student_id=? AND ki.base_id=?
            """,
            (student_id, base_id),
        ).fetchone()

        mastered = conn.execute(
            """
            SELECT COUNT(1) AS c
            FROM student_item_stats sis
            JOIN knowledge_items ki ON ki.id = sis.item_id
            WHERE sis.student_id=? AND ki.base_id=? AND sis.consecutive_correct >= ?
            """,
            (student_id, base_id, get_mastery_threshold()),
        ).fetchone()

        wrong_top = conn.execute(
            """
            SELECT ki.type, ki.en_text, ki.zh_hint, sis.wrong_attempts, sis.last_attempt_at
            FROM student_item_stats sis
            JOIN knowledge_items ki ON ki.id = sis.item_id
            WHERE sis.student_id=? AND ki.base_id=? AND sis.wrong_attempts > 0
            ORDER BY sis.wrong_attempts DESC, sis.last_attempt_at DESC
            LIMIT 10
            """,
            (student_id, base_id),
        ).fetchall()

        recent_sessions = conn.execute(
            """
            SELECT
              ps.id,
              ps.status,
              ps.created_at,
              ps.corrected_at,
              ps.pdf_path,
              ps.answer_pdf_path,
              (SELECT COUNT(1) FROM exercise_items ei WHERE ei.session_id = ps.id) AS item_count
            FROM practice_sessions ps
            WHERE ps.student_id=? AND ps.base_id=?
            ORDER BY ps.id DESC
            LIMIT 10
            """,
            (student_id, base_id),
        ).fetchall()

        cal = conn.execute(
            """
            SELECT substr(created_at, 1, 10) AS d, COUNT(1) AS c
            FROM practice_sessions
            WHERE student_id=? AND base_id=? AND created_at >= datetime('now', ?)
            GROUP BY substr(created_at, 1, 10)
            ORDER BY d ASC
            """,
            (student_id, base_id, f"-{int(days)} days"),
        ).fetchall()

    cal_rows = [dict(r) for r in cal]
    practice_days = sum(1 for r in cal_rows if int(r.get("c") or 0) > 0)

    sessions_out: List[Dict[str, Any]] = []
    for r in recent_sessions:
        row = dict(r)
        pdf_path = row.get("pdf_path")
        ans_path = row.get("answer_pdf_path")
        row["pdf_url"] = f"/media/{os.path.basename(pdf_path)}" if pdf_path else None
        row["answer_pdf_url"] = f"/media/{os.path.basename(ans_path)}" if ans_path else None
        sessions_out.append(row)

    return {
        "learned_count": int(learned["c"]) if learned else 0,
        "mastered_count": int(mastered["c"]) if mastered else 0,
        "practice_days": practice_days,
        "top_wrong": [dict(r) for r in wrong_top],
        "recent_sessions": sessions_out,
        "calendar_days": cal_rows,
    }
