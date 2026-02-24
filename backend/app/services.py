import io
import json
import os
import re
import uuid
import difflib
import time
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

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
        # Prefer 'results' (detailed) over 'words_result' (simplified)
        words = raw.get("results") or raw.get("words_result") or raw.get("data") or []
        for word in words:
            if isinstance(word, dict):
                # Handle both formats
                words_obj = word.get("words", {})
                if isinstance(words_obj, dict):
                    # Detailed format: word.words.word
                    text = words_obj.get("word") or ""
                elif isinstance(words_obj, str):
                    # Simplified format: word.words
                    text = words_obj
                else:
                    continue

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


def _extract_uuid_from_ocr(ocr_raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract worksheet UUID from OCR results with multi-page consistency check.

    UUID format: ES-XXXX-XXXXXX (e.g., ES-0055-CF12D2)
    - First part: ES-XXXX (barcode, easier to recognize)
    - Second part: XXXXXX (alphanumeric characters, harder to recognize)

    Returns:
        {
            "uuid": str or None,  # Final adopted UUID
            "page_uuids": List[Dict],  # Per-page UUID results with confidence
            "consistent": bool,  # Whether all pages have the same UUID
            "confidence": float,  # Overall confidence (0-1)
            "warning": str or None  # Warning message if inconsistent
        }
    """
    import re
    import logging

    logger = logging.getLogger("uvicorn.error")
    pages = ocr_raw.get("pages") or []

    # UUID pattern: ES-XXXX-XXXXXX
    uuid_pattern = r'ES-(\d{4})-([A-Z0-9]{6})'
    barcode_pattern = r'ES-(\d{4})'
    suffix_pattern = r'([A-Z0-9]{6})'

    page_results = []

    for page_idx, page in enumerate(pages):
        raw = page.get("raw") or {}
        # Prefer 'results' (detailed with confidence) over 'words_result' (simplified)
        words = raw.get("results") or raw.get("words_result") or raw.get("data") or []

        page_uuid = None
        page_confidence = 0.0
        barcode_part = None
        suffix_part = None
        barcode_conf = 0.0
        suffix_conf = 0.0

        for word in words:
            if not isinstance(word, dict):
                continue

            # Handle both OCR data formats:
            # 1. results format: word.words.word (dict with confidence)
            # 2. words_result format: word.words (string, no confidence)
            words_obj = word.get("words", {})
            if isinstance(words_obj, dict):
                # Detailed format (results): has word, line_probability
                text = str(words_obj.get("word") or "")
                probability = words_obj.get("line_probability", {})
            elif isinstance(words_obj, str):
                # Simplified format (words_result): direct string
                text = str(words_obj)
                probability = {}
            else:
                # Unknown format, skip
                continue

            # Get confidence (百度OCR返回的是字典，包含average/min等)
            if isinstance(probability, dict):
                conf = float(probability.get("average", 0) or 0)
            else:
                conf = float(probability or 0) if probability else 0.0

            # Try to match full UUID first
            full_match = re.search(uuid_pattern, text)
            if full_match:
                matched_uuid = f"ES-{full_match.group(1)}-{full_match.group(2)}"
                if conf > page_confidence:
                    page_uuid = matched_uuid
                    page_confidence = conf
                    barcode_part = f"ES-{full_match.group(1)}"
                    suffix_part = full_match.group(2)
                    barcode_conf = conf
                    suffix_conf = conf
                continue

            # Try barcode part (higher confidence, easier to recognize)
            barcode_match = re.search(barcode_pattern, text)
            if barcode_match and conf > barcode_conf:
                barcode_part = f"ES-{barcode_match.group(1)}"
                barcode_conf = conf

            # Try suffix part (lower confidence, harder to recognize)
            if len(text) == 6 and re.match(suffix_pattern, text):
                if conf > suffix_conf:
                    suffix_part = text
                    suffix_conf = conf

        # Combine barcode and suffix if we have both
        if not page_uuid and barcode_part and suffix_part:
            page_uuid = f"{barcode_part}-{suffix_part}"
            # Weight barcode more heavily (80% barcode, 20% suffix)
            page_confidence = barcode_conf * 0.8 + suffix_conf * 0.2

        page_results.append({
            "page": page_idx,
            "uuid": page_uuid,
            "confidence": page_confidence,
            "barcode_part": barcode_part,
            "suffix_part": suffix_part,
            "barcode_confidence": barcode_conf,
            "suffix_confidence": suffix_conf
        })

        logger.info(f"[UUID EXTRACT] Page {page_idx}: {page_uuid} (conf={page_confidence:.2f})")

    # Check consistency across pages
    valid_uuids = [p["uuid"] for p in page_results if p["uuid"]]

    if not valid_uuids:
        return {
            "uuid": None,
            "page_uuids": page_results,
            "consistent": True,
            "confidence": 0.0,
            "warning": "未识别到试卷编号"
        }

    # Check if all pages have the same UUID
    unique_uuids = set(valid_uuids)
    consistent = len(unique_uuids) == 1

    if consistent:
        # All pages have same UUID, use the one with highest confidence
        best_page = max(page_results, key=lambda p: p["confidence"])
        return {
            "uuid": best_page["uuid"],
            "page_uuids": page_results,
            "consistent": True,
            "confidence": best_page["confidence"],
            "warning": None
        }
    else:
        # Inconsistent UUIDs across pages
        # Use majority vote with confidence weighting
        uuid_scores = {}
        for p in page_results:
            if p["uuid"]:
                uuid_scores[p["uuid"]] = uuid_scores.get(p["uuid"], 0) + p["confidence"]

        best_uuid = max(uuid_scores.items(), key=lambda x: x[1])[0] if uuid_scores else None
        avg_confidence = sum(p["confidence"] for p in page_results) / len(page_results)

        warning = f"⚠️ 多页试卷编号不一致！识别到: {', '.join(unique_uuids)}。请检查是否上传了不同试卷的照片。"
        logger.warning(f"[UUID EXTRACT] Inconsistent UUIDs: {unique_uuids}")

        return {
            "uuid": best_uuid,
            "page_uuids": page_results,
            "consistent": False,
            "confidence": avg_confidence,
            "warning": warning
        }


def _normalize_ocr_words(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Normalize OCR data to simplified words_result format for matching.

    Supports both formats:
    - words_result: {words: str, location: {...}, words_type: str}
    - results: {words: {word: str, words_location: {...}}, words_type: str}

    Returns: List of dicts in simplified format
    """
    # Try simplified format first (faster)
    words_result = raw.get("words_result")
    if words_result and isinstance(words_result, list):
        return words_result

    # Convert detailed format to simplified format
    results = raw.get("results") or raw.get("data") or []
    if not results:
        return []

    normalized = []
    for item in results:
        if not isinstance(item, dict):
            continue

        words_obj = item.get("words", {})
        if isinstance(words_obj, dict):
            # Detailed format: convert to simplified
            text = words_obj.get("word") or ""
            location = words_obj.get("words_location") or {}
        elif isinstance(words_obj, str):
            # Already simplified (shouldn't happen in results)
            text = words_obj
            location = item.get("location") or {}
        else:
            continue

        normalized.append({
            "words": text,
            "location": {
                "left": location.get("left", 0),
                "top": location.get("top", 0),
                "width": location.get("width", 0),
                "height": location.get("height", 0),
            },
            "words_type": item.get("words_type", ""),
        })

    return normalized


def _detect_page_number(ocr_words: List[Dict[str, Any]]) -> Optional[int]:
    """
    从 OCR 识别结果中检测页码。

    支持的格式:
    - "第1页", "第2页", "第 1 页"
    - "1/2", "2/2"
    - "Page 1", "Page 2"
    - "- 1 -", "- 2 -"

    Returns:
        检测到的页码 (1-based)，未检测到返回 None
    """
    import re

    page_patterns = [
        r'第\s*(\d+)\s*页',           # 第1页, 第 1 页
        r'^(\d+)\s*/\s*\d+$',          # 1/2, 2/2
        r'[Pp]age\s*(\d+)',            # Page 1, page 1
        r'^-\s*(\d+)\s*-$',            # - 1 -
        r'^(\d+)$',                     # 单独的数字 (通常在页面底部)
    ]

    candidates = []

    for word_obj in ocr_words:
        text = (word_obj.get("words") or "").strip()
        if not text:
            continue

        # 获取位置信息，页码通常在页面底部
        loc = word_obj.get("location") or {}
        top = loc.get("top", 0)

        for pattern in page_patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    page_num = int(match.group(1))
                    if 1 <= page_num <= 100:  # 合理的页码范围
                        candidates.append({
                            "page_num": page_num,
                            "top": top,
                            "text": text
                        })
                except (ValueError, IndexError):
                    pass

    if not candidates:
        return None

    # 优先选择位置最靠下的页码（通常是页脚）
    candidates.sort(key=lambda x: -x["top"])
    return candidates[0]["page_num"]


def _reorder_by_page_numbers(
    ocr_raw: Dict[str, Any],
    img_bytes_list: List[bytes],
    logger: Any = None
) -> Tuple[Dict[str, Any], List[bytes], Dict[int, int]]:
    """
    根据 OCR 检测到的页码重新排序页面。

    Args:
        ocr_raw: OCR 识别结果 {"pages": [...]}
        img_bytes_list: 原始图片字节列表
        logger: 日志记录器

    Returns:
        Tuple of:
        - 重排后的 ocr_raw
        - 重排后的 img_bytes_list
        - 页码映射 {原始索引: 新索引}
    """
    if logger is None:
        logger = logging.getLogger("uvicorn.error")

    ocr_pages = ocr_raw.get("pages") or []
    if len(ocr_pages) <= 1:
        # 单页无需重排
        return ocr_raw, img_bytes_list, {0: 0} if ocr_pages else {}

    # 检测每页的页码
    page_info = []
    for idx, page in enumerate(ocr_pages):
        raw = page.get("raw") or {}
        words = _normalize_ocr_words(raw)
        detected_num = _detect_page_number(words)
        page_info.append({
            "original_index": idx,
            "detected_page": detected_num,
            "page_data": page
        })
        logger.info(f"[PAGE REORDER] Page index {idx}: detected page number = {detected_num}")

    # 检查是否所有页面都检测到了页码
    detected_pages = [p["detected_page"] for p in page_info if p["detected_page"] is not None]

    if len(detected_pages) != len(page_info):
        # 不是所有页面都检测到页码，保持原顺序
        logger.warning(f"[PAGE REORDER] Not all pages have page numbers detected ({len(detected_pages)}/{len(page_info)}), keeping original order")
        return ocr_raw, img_bytes_list, {i: i for i in range(len(ocr_pages))}

    # 检查页码是否连续且唯一
    if len(set(detected_pages)) != len(detected_pages):
        logger.warning(f"[PAGE REORDER] Duplicate page numbers detected: {detected_pages}, keeping original order")
        return ocr_raw, img_bytes_list, {i: i for i in range(len(ocr_pages))}

    # 按检测到的页码排序
    page_info.sort(key=lambda x: x["detected_page"])

    # 检查是否需要重排
    original_order = [p["original_index"] for p in page_info]
    if original_order == list(range(len(page_info))):
        logger.info("[PAGE REORDER] Pages are already in correct order")
        return ocr_raw, img_bytes_list, {i: i for i in range(len(ocr_pages))}

    # 执行重排
    logger.info(f"[PAGE REORDER] Reordering pages: original indices {original_order} -> new indices {list(range(len(page_info)))}")

    # 创建映射: 原始索引 -> 新索引
    index_mapping = {}
    for new_idx, info in enumerate(page_info):
        index_mapping[info["original_index"]] = new_idx

    # 重排 OCR 数据
    new_ocr_pages = []
    for new_idx, info in enumerate(page_info):
        new_page = info["page_data"].copy()
        new_page["page_index"] = new_idx
        new_page["original_page_index"] = info["original_index"]
        new_ocr_pages.append(new_page)

    new_ocr_raw = {"pages": new_ocr_pages}

    # 重排图片
    new_img_bytes_list = [img_bytes_list[info["original_index"]] for info in page_info]

    logger.info(f"[PAGE REORDER] Reorder complete. Mapping: {index_mapping}")

    return new_ocr_raw, new_img_bytes_list, index_mapping


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


def _normalize_upload_image(img_bytes: bytes, filename: str) -> Tuple[bytes, str]:
    max_long_side = int(os.environ.get("EL_AI_MAX_LONG_SIDE", "3508") or 3508)
    jpeg_quality = int(os.environ.get("EL_AI_JPEG_QUALITY", "85") or 85)
    try:
        img = Image.open(io.BytesIO(img_bytes))
    except Exception:
        ext = os.path.splitext(filename or "")[1].lower() or ".jpg"
        return img_bytes, ext

    img = ImageOps.exif_transpose(img)
    if img.mode != "RGB":
        img = img.convert("RGB")
    if max_long_side > 0:
        w, h = img.size
        max_dim = max(w, h)
        if max_dim > max_long_side:
            scale = max_long_side / max_dim
            new_w = max(1, int(w * scale))
            new_h = max(1, int(h * scale))
            img = img.resize((new_w, new_h), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=jpeg_quality, optimize=True)
    return buf.getvalue(), ".jpg"


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


def _detect_section_key(text: str) -> Optional[str]:
    text = text or ""
    if "单词默写" in text:
        return "WORD"
    if "短语默写" in text:
        return "PHRASE"
    if "句子默写" in text:
        return "SENTENCE"
    return None


def _llm_pages_zero_based(objects: List[Dict[str, Any]]) -> bool:
    """Heuristic: if any pg == 0, treat LLM page indices as 0-based."""
    for obj in objects or []:
        if not isinstance(obj, dict):
            continue
        if isinstance(obj.get("items"), list):
            for it in obj.get("items") or []:
                try:
                    pg = int(it.get("pg") if "pg" in it else it.get("page_index"))
                except Exception:
                    continue
                if pg == 0:
                    return True
        else:
            try:
                pg = int(obj.get("pg") if "pg" in obj else obj.get("page_index"))
            except Exception:
                continue
            if pg == 0:
                return True
    return False


def _llm_pg_to_zero_based(pg_raw: Any, zero_based: bool) -> int:
    try:
        pg = int(pg_raw)
    except Exception:
        return 0
    if zero_based:
        return max(0, pg)
    return max(0, pg - 1)


def _ocr_section_keys_by_page(ocr_raw: Dict[str, Any]) -> Dict[int, Set[str]]:
    keys_by_page: Dict[int, Set[str]] = {}
    for page in ocr_raw.get("pages") or []:
        idx0 = int(page.get("page_index") or 0)
        raw = page.get("raw") or {}
        words = _normalize_ocr_words(raw)
        keys: Set[str] = set()
        for w in words:
            if w.get("words_type") == "handwriting":
                continue
            sec = _detect_section_key(str(w.get("words") or ""))
            if sec:
                keys.add(sec)
        keys_by_page[idx0 + 1] = keys
    return keys_by_page


def _llm_section_keys_by_page(
    sections: List[Dict[str, Any]],
    zero_based: bool,
    page_reorder_mapping: Dict[int, int],
) -> Dict[int, Set[str]]:
    keys_by_page: Dict[int, Set[str]] = {}
    for sec in sections or []:
        if not isinstance(sec, dict):
            continue
        sec_type = sec.get("type") or ""
        for it in sec.get("items") or []:
            pg_raw = it.get("pg") if "pg" in it else it.get("page_index")
            pg0 = _llm_pg_to_zero_based(pg_raw, zero_based)
            pg0 = page_reorder_mapping.get(pg0, pg0)
            pg1 = pg0 + 1
            keys_by_page.setdefault(pg1, set()).add(sec_type)
    return keys_by_page


def _build_page_mapping_by_sections(
    llm_keys_by_page: Dict[int, Set[str]],
    ocr_keys_by_page: Dict[int, Set[str]],
    total_pages: int,
    logger: Any,
) -> Dict[int, int]:
    pages = list(range(1, total_pages + 1))
    if not pages:
        return {}
    if any(not ocr_keys_by_page.get(p) for p in pages):
        return {p: p for p in pages}
    if any(not llm_keys_by_page.get(p) for p in pages):
        return {p: p for p in pages}

    llm_key = {p: "+".join(sorted(llm_keys_by_page.get(p) or [])) for p in pages}
    ocr_key = {p: "+".join(sorted(ocr_keys_by_page.get(p) or [])) for p in pages}
    if all(llm_key[p] == ocr_key[p] for p in pages):
        return {p: p for p in pages}

    mapping: Dict[int, int] = {}
    used: Set[int] = set()
    for p in pages:
        candidates = [op for op in pages if ocr_key[op] == llm_key[p]]
        if len(candidates) != 1 or candidates[0] in used:
            return {p: p for p in pages}
        mapping[p] = candidates[0]
        used.add(candidates[0])

    if any(mapping[p] != p for p in pages):
        logger.info(f"[PAGE REORDER] Remap LLM pages by section headers: {mapping}")
    return mapping


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


def _build_question_anchors(words: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Set[str]]:
    """Build question anchors from OCR print text with inferred section keys."""
    anchors: List[Dict[str, Any]] = []
    section_headers: List[Dict[str, Any]] = []
    for w in words:
        if w.get("words_type") == "handwriting":
            continue
        text = str(w.get("words") or "")
        loc = w.get("location") or {}
        top = float(loc.get("top", 0))
        left = float(loc.get("left", 0))
        width = float(loc.get("width", 0))
        height = float(loc.get("height", 0))
        sec = _detect_section_key(text)
        if sec:
            section_headers.append({"section": sec, "top": top})
        q_num = _extract_question_number(text)
        if q_num is not None:
            anchors.append({
                "q_num": q_num,
                "section": "",
                "top": top,
                "left": left,
                "bottom": top + height,
                "right": left + width,
            })

    section_headers.sort(key=lambda x: x["top"])

    def _section_for(y: float) -> str:
        best = ""
        for h in section_headers:
            if h["top"] <= y + 8:
                best = h["section"]
            else:
                break
        return best

    for a in anchors:
        a["section"] = _section_for(a["top"])

    # Deduplicate by (section, q_num), keep earliest (top-most) anchor
    dedup: Dict[Tuple[str, int], Dict[str, Any]] = {}
    for a in anchors:
        key = (a["section"], a["q_num"])
        if key not in dedup or a["top"] < dedup[key]["top"]:
            dedup[key] = a

    anchors = list(dedup.values())
    anchors.sort(key=lambda x: (x["top"], x["left"]))
    section_keys = {h["section"] for h in section_headers}
    return anchors, section_keys


def _group_handwriting_by_question_geo(
    words: List[Dict[str, Any]]
) -> Tuple[Dict[Tuple[str, int], List[Dict[str, Any]]], Set[str], Set[int]]:
    """Group handwriting words by nearest question anchor above them (geometry-based)."""
    anchors, section_keys = _build_question_anchors(words)
    question_numbers = {a["q_num"] for a in anchors}
    groups: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}

    if not anchors:
        return groups, section_keys, question_numbers

    for w in words:
        if w.get("words_type") != "handwriting":
            continue
        loc = w.get("location") or {}
        top = float(loc.get("top", 0))
        # Pick nearest anchor by vertical distance (handles handwriting slightly above/below print line).
        idx = None
        for i, a in enumerate(anchors):
            if a["top"] > top:
                idx = i
                break
        if idx is None:
            best = anchors[-1]
        elif idx == 0:
            best = anchors[0]
        else:
            prev = anchors[idx - 1]
            nxt = anchors[idx]
            if abs(top - prev["top"]) <= abs(nxt["top"] - top):
                best = prev
            else:
                best = nxt

        key = (best["section"], best["q_num"])
        groups.setdefault(key, []).append(w)

    return groups, section_keys, question_numbers


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


def _get_active_base_ids(conn, student_id: int) -> List[int]:
    """Get all active knowledge base IDs for a student.

    Args:
        conn: Database connection
        student_id: Student ID

    Returns:
        List of base_ids from active learning bases
    """
    rows = conn.execute(
        """
        SELECT base_id FROM student_learning_bases
        WHERE student_id = ? AND is_active = 1
        ORDER BY id
        """,
        (student_id,)
    ).fetchall()
    return [row[0] for row in rows] if rows else []


def _attach_kb_matches(conn, base_ids: List[int], items: List[Dict]) -> List[Dict]:
    """Attach knowledge base match info to AI-extracted items.

    Args:
        conn: Database connection
        base_ids: List of knowledge base IDs to search in (from student's active learning bases)
        items: Items to match

    Returns:
        Items with matched_en_text, matched_item_id, etc. populated
    """
    out: List[Dict] = []
    for it in items:
        student_text = str(it.get("student_text") or "").strip()
        zh_hint = str(it.get("zh_hint") or "").strip()
        cleaned_student = re.sub(r"^\s*(英文[:：]?\s*)", "", student_text)
        norm = normalize_answer(cleaned_student) if cleaned_student else ""
        row = None

        if norm or zh_hint:
            # Search across all active knowledge bases
            placeholders = ','.join('?' * len(base_ids))
            query = f"""
                SELECT * FROM items
                WHERE base_id IN ({placeholders})
                  AND (
                    (LOWER(en_text)=? AND ?<>'')
                    OR (zh_text=? AND ?<>'')
                  )
                LIMIT 1
            """
            row = conn.execute(
                query,
                (*base_ids, cleaned_student.lower(), cleaned_student, zh_hint, zh_hint)
            ).fetchone()

        # Fuzzy matching if no exact match
        if not row and norm and len(norm) >= 6:
            placeholders = ','.join('?' * len(base_ids))
            query = f"""
                SELECT * FROM items
                WHERE base_id IN ({placeholders})
                  AND LOWER(en_text) LIKE ?
                LIMIT 1
            """
            row = conn.execute(
                query,
                (*base_ids, f"%{norm.lower()}%")
            ).fetchone()
        hit = dict(row) if row else None
        item = dict(it)
        item["kb_hit"] = bool(hit)
        item["matched_item_id"] = int(hit["id"]) if hit else None
        item["matched_en_text"] = hit["en_text"] if hit else ""
        item["matched_type"] = hit["item_type"] if hit else ""
        out.append(item)
    return out


def _load_ai_config() -> Dict[str, Any]:
    path = os.environ.get("EL_AI_CONFIG_PATH") or os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "ai_config.json")
    )
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


def _resolve_session_by_uuid(conn, worksheet_uuid: str, account_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        """
        SELECT
          ps.id,
          ps.student_id,
          ps.base_id,
          s.name AS student_name,
          b.name AS base_name
        FROM practice_sessions ps
        LEFT JOIN students s ON s.id = ps.student_id
        LEFT JOIN bases b ON b.id = ps.base_id
        WHERE ps.practice_uuid = ?
          AND s.account_id = ?
        ORDER BY ps.id DESC
        LIMIT 1
        """,
        (worksheet_uuid, account_id),
    ).fetchone()
    return dict(row) if row else None


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


def _extract_llm_raw(llm_result: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(llm_result, dict):
        return {}
    raw = llm_result.get("raw_llm")
    if isinstance(raw, dict):
        return raw
    return llm_result


def _extract_ocr_raw(ocr_result: Dict[str, Any]) -> Dict[str, Any]:
    ocr_raw = {"pages": []}
    if isinstance(ocr_result, dict) and "pages" in ocr_result:
        for page in ocr_result["pages"]:
            if isinstance(page, dict) and "raw" in page:
                ocr_raw["pages"].append({
                    "page_index": page.get("page_index", 0),
                    "raw": page["raw"],
                })
    return ocr_raw


def _save_ai_bundle(
    bundle_id: str,
    llm_result: Dict[str, Any],
    ocr_result: Dict[str, Any],
    image_urls: List[str],
    graded_image_urls: List[str],
    items: Optional[List[Dict[str, Any]]] = None,
) -> None:
    base_dir = os.path.join(MEDIA_DIR, "uploads", "ai_bundles", bundle_id)
    os.makedirs(base_dir, exist_ok=True)
    with open(os.path.join(base_dir, "llm_raw.json"), "w", encoding="utf-8") as f:
        json.dump(_extract_llm_raw(llm_result), f, ensure_ascii=False, indent=2)
    with open(os.path.join(base_dir, "ocr_raw.json"), "w", encoding="utf-8") as f:
        json.dump(_extract_ocr_raw(ocr_result), f, ensure_ascii=False, indent=2)
    with open(os.path.join(base_dir, "meta.json"), "w", encoding="utf-8") as f:
        crop_items: List[Dict[str, Any]] = []
        for it in (items or []):
            if not isinstance(it, dict):
                continue
            crop_bbox = it.get("crop_bbox")
            if not isinstance(crop_bbox, dict):
                continue
            try:
                crop_items.append(
                    {
                        "position": int(it.get("position")),
                        "page_index": int(crop_bbox.get("page_index") or it.get("page_index") or 1),
                        "left": int(crop_bbox.get("left")),
                        "top": int(crop_bbox.get("top")),
                        "right": int(crop_bbox.get("right")),
                        "bottom": int(crop_bbox.get("bottom")),
                    }
                )
            except Exception:
                continue
        json.dump(
            {
                "saved_at": utcnow_iso(),
                "image_urls": image_urls or [],
                "graded_image_urls": graded_image_urls or [],
                "crop_items": crop_items,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )


def _load_ai_bundle_meta(bundle_id: str) -> Optional[Dict[str, Any]]:
    if not bundle_id:
        return None
    base_dir = os.path.join(MEDIA_DIR, "uploads", "ai_bundles", bundle_id)
    meta_path = os.path.join(base_dir, "meta.json")
    if not os.path.exists(meta_path):
        return None
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


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

def get_weekly_target_days(student_id: int = None) -> int:
    """
    获取周练习目标天数

    Args:
        student_id: 学生ID，如果提供则优先使用学生的个性化设置

    Returns:
        周练习目标天数（1-7）
    """
    # 如果提供了学生ID，优先使用学生的个性化设置
    if student_id is not None:
        try:
            with db() as conn:
                row = conn.execute(
                    "SELECT weekly_target_days FROM students WHERE id = ?",
                    (student_id,)
                ).fetchone()
                if row and row["weekly_target_days"] is not None:
                    value = int(row["weekly_target_days"])
                    return max(1, min(7, value))
        except Exception:
            pass

    # 使用全局默认设置
    try:
        value = int(get_setting("weekly_target_days", "4"))
        return max(1, min(7, value))
    except Exception:
        return 4

def ensure_media_dir() -> None:
    os.makedirs(MEDIA_DIR, exist_ok=True)


def _save_crop_images(image_bytes_list: List[bytes], items: List[Dict], force_save: bool = False) -> None:
    """Attach crop_url to items if bbox/page_index provided.

    By default, crop images are NOT saved to disk to prevent filesystem bloat.
    Only bbox information is attached to items for on-demand generation.
    Set environment variable SAVE_CROP_IMAGES=1 to enable saving.
    """
    if not items:
        return

    import logging
    logger = logging.getLogger("uvicorn.error")
    debug_bbox = os.environ.get("EL_DEBUG_BBOX_PROCESSING", "0") == "1"
    save_crops = force_save or (os.environ.get("SAVE_CROP_IMAGES", "0") == "1")

    if save_crops:
        ensure_media_dir()
        crop_dir = os.path.join(MEDIA_DIR, "uploads", "crops")
        os.makedirs(crop_dir, exist_ok=True)

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
            page_index = int(it.get("page_index") or 1)
        except Exception:
            page_index = 1
        page_idx0 = max(0, page_index - 1)
        if page_idx0 < 0 or page_idx0 >= len(images) or images[page_idx0] is None:
            continue
        img = images[page_idx0]
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

        # Store bbox information for on-demand crop generation
        it["crop_bbox"] = {
            "left": left,
            "top": top,
            "right": right,
            "bottom": bottom,
            "page_index": page_index
        }

        # Only save crop image if explicitly enabled
        if save_crops:
            try:
                crop = img.crop((left, top, right, bottom))
            except Exception:
                continue
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
                pidx = int(it.get("page_index") or 1)
            except Exception:
                pidx = 1
            if (pidx - 1) != page_index:
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


def analyze_ai_photos_from_debug(account_id: int, student_id: int, base_id: int) -> Dict:
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
    meta = {}
    if os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    else:
        logger.warning("[AI GRADING DEBUG] meta.json not found, falling back to input_*.jpg scan")

    # Load images
    img_bytes_list: List[bytes] = []
    image_urls: List[str] = []
    image_count = int(meta.get("image_count", 0) or 0)
    if image_count > 0:
        for i in range(1, image_count + 1):
            img_path = os.path.join(debug_dir, f"input_{i}.jpg")
            if os.path.exists(img_path):
                with open(img_path, "rb") as f:
                    img_bytes_list.append(f.read())
                image_urls.append(f"/media/uploads/debug_last/input_{i}.jpg")
    else:
        for name in sorted(os.listdir(debug_dir)):
            if not (name.startswith("input_") and name.endswith(".jpg")):
                continue
            img_path = os.path.join(debug_dir, name)
            with open(img_path, "rb") as f:
                img_bytes_list.append(f.read())
            image_urls.append(f"/media/uploads/debug_last/{name}")

    if not img_bytes_list:
        raise ValueError("调试目录中未找到 input_*.jpg 图片，请先运行一次正常识别")

    # Apply white balance for grading/cropping (same as normal mode)
    logger.info("[AI GRADING DEBUG] Applying white balance...")
    wb_img_bytes_list: List[bytes] = []
    for img_bytes in img_bytes_list:
        wb_bytes = apply_white_balance(img_bytes)
        wb_img_bytes_list.append(wb_bytes)
    logger.info(f"[AI GRADING DEBUG] White balance applied to {len(wb_img_bytes_list)} images")

    # ========== 页码检测与重排 ==========
    page_reorder_mapping: Dict[int, int] = {}
    page_order = list(range(len(img_bytes_list)))
    try:
        ocr_raw, wb_img_bytes_list, page_reorder_mapping = _reorder_by_page_numbers(
            ocr_raw, wb_img_bytes_list, logger
        )
        if page_reorder_mapping and any(k != v for k, v in page_reorder_mapping.items()):
            order = sorted(page_reorder_mapping.keys(), key=lambda x: page_reorder_mapping[x])
            img_bytes_list = [img_bytes_list[info] for info in order]
            image_urls = [image_urls[info] for info in order]
            page_order = order
    except Exception as e:
        logger.warning(f"[PAGE REORDER] Error during page reordering: {e}, continuing with original order")
        page_reorder_mapping = {i: i for i in range(len(ocr_raw.get("pages", [])))}

    # Parse LLM raw data (which is now in the original sections format)
    items_raw = []
    sections = llm_raw.get("sections")
    if isinstance(sections, list):
        llm_zero_based = _llm_pages_zero_based(sections)
    else:
        llm_zero_based = _llm_pages_zero_based(llm_raw.get("items") or [])
    total_pages = len(ocr_raw.get("pages") or []) or len(img_bytes_list)
    ocr_section_keys = _ocr_section_keys_by_page(ocr_raw)
    llm_section_keys = _llm_section_keys_by_page(
        sections if isinstance(sections, list) else [],
        llm_zero_based,
        page_reorder_mapping,
    )
    page_map_by_section = _build_page_mapping_by_sections(
        llm_section_keys, ocr_section_keys, total_pages, logger
    )
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
                # 应用页码映射（1-based）
                llm_pg_raw = it.get("pg") if "pg" in it else it.get("page_index")
                llm_pg0 = _llm_pg_to_zero_based(llm_pg_raw, llm_zero_based)
                mapped_pg0 = page_reorder_mapping.get(llm_pg0, llm_pg0)
                mapped_pg1 = mapped_pg0 + 1
                mapped_pg1 = page_map_by_section.get(mapped_pg1, mapped_pg1)
                # Convert short field names to long names
                items_raw.append({
                    "q": it.get("q"),
                    "section_title": sec_title if idx == 0 else "",  # Only first item has title
                    "section_type": sec_type,
                    "zh_hint": it.get("hint") or "",
                    "student_text": it.get("ans") or "",
                    "is_correct": it.get("ok"),
                    "confidence": it.get("conf"),
                    "page_index": mapped_pg1,
                    "original_page_index": llm_pg0 + 1,
                    "note": it.get("note") or "",
                })
    else:
        # Fallback to old items format if sections not found
        raw_items = llm_raw.get("items") or []
        for it in raw_items:
            if not isinstance(it, dict):
                items_raw.append(it)
                continue
            llm_pg_raw = it.get("page_index") if "page_index" in it else it.get("pg")
            llm_pg0 = _llm_pg_to_zero_based(llm_pg_raw, llm_zero_based)
            mapped_pg0 = page_reorder_mapping.get(llm_pg0, llm_pg0)
            mapped_pg1 = mapped_pg0 + 1
            mapped_pg1 = page_map_by_section.get(mapped_pg1, mapped_pg1)
            new_it = dict(it)
            new_it["page_index"] = mapped_pg1
            new_it["original_page_index"] = llm_pg0 + 1
            items_raw.append(new_it)

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
        # FIXED: Use global sequential index as position to avoid duplicates across sections
        # Store original question number in 'q' field for display purposes
        position = idx
        conf_val = it.get("confidence")
        items.append(
            {
                "position": position,
                "q": it.get("q"),  # Original question number within section
                "section_type": it.get("section_type") or "",
                "section_title": it.get("section_title") or "",
                "zh_hint": zh_hint,
                "llm_text": it.get("student_text") or "",
                "is_correct": it.get("is_correct") if "is_correct" in it else None,
                "confidence": float(conf_val) if conf_val is not None else None,
                "page_index": int(it.get("page_index") or 1),
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
        words = _normalize_ocr_words(raw)
        if words:
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

    # LLM section keys per page (used to avoid cross-section fallback)
    llm_section_keys_by_page: Dict[int, set] = {}
    for it in items:
        sec = str(it.get("section_type") or "")
        if not sec:
            continue
        page_idx0 = max(0, int(it.get("page_index") or 1) - 1)
        llm_section_keys_by_page.setdefault(page_idx0, set()).add(sec)

    # Geometry-based OCR grouping (robust to OCR order)
    handwriting_groups_by_page: Dict[int, Dict[Tuple[str, int], List[Dict[str, Any]]]] = {}
    section_keys_by_page: Dict[int, set] = {}
    question_numbers_by_page: Dict[int, set] = {}
    for page_idx, words in ocr_by_page.items():
        groups, sec_keys, q_nums = _group_handwriting_by_question_geo(words)
        handwriting_groups_by_page[page_idx] = groups
        section_keys_by_page[page_idx] = sec_keys
        question_numbers_by_page[page_idx] = q_nums

    ocr_lines_by_page: Dict[int, List[Dict[str, Any]]] = {}
    for page_idx, words in ocr_by_page.items():
        lines = _build_ocr_lines(words, items=items)
        lines = [ln for ln in lines if re.search(r"[A-Za-z]", ln["text"])]
        lines.sort(key=lambda ln: (ln["bbox"][1], ln["bbox"][0]))
        ocr_lines_by_page[page_idx] = lines

    ocr_used: Dict[int, set] = {page_idx: set() for page_idx in ocr_lines_by_page.keys()}

    for it in items:
        page_idx = max(0, int(it.get("page_index") or 1) - 1)
        q_num = int(it.get("q") or 0)
        it["ocr_text"] = ""
        it["match_method"] = "no_match"

        section_key = str(it.get("section_type") or "")
        group_key = (section_key, q_num)
        groups_for_page = handwriting_groups_by_page.get(page_idx, {}) or {}
        group = groups_for_page.get(group_key) if q_num else None

        lines = ocr_lines_by_page.get(page_idx) or []

        if not group and q_num:
            same_q_keys = [key for key in groups_for_page.keys() if key[1] == q_num]
            llm_sections = llm_section_keys_by_page.get(page_idx, set())
            if len(same_q_keys) == 1 and len(llm_sections) <= 1:
                group = groups_for_page[same_q_keys[0]]
            elif same_q_keys:
                continue
        if not group and q_num and q_num in question_numbers_by_page.get(page_idx, set()):
            continue
        if not group and not lines:
            continue
        if group:
            merged_lines = _build_ocr_lines(group, items=items)
            candidate_texts = [ln.get("text") for ln in merged_lines if ln.get("text")]
            if not candidate_texts:
                candidate_texts = [str(w.get("words") or "").strip() for w in group if str(w.get("words") or "").strip()]
            llm_text_norm = normalize_answer(str(it.get("llm_text") or ""))
            best_text = candidate_texts[0] if candidate_texts else ""
            best_ratio_group = 0.0
            if llm_text_norm and candidate_texts:
                for cand in candidate_texts:
                    cand_norm = normalize_answer(cand)
                    if not cand_norm:
                        continue
                    ratio = difflib.SequenceMatcher(None, llm_text_norm, cand_norm).ratio()
                    if ratio > best_ratio_group:
                        best_ratio_group = ratio
                        best_text = cand
            if not llm_text_norm or best_ratio_group >= ocr_match_thr:
                it["ocr_text"] = best_text
                it["ocr_text_candidates"] = candidate_texts
                it["ocr_match_ratio"] = best_ratio_group
                it["match_method"] = "question_group"

                lefts: List[float] = []
                tops: List[float] = []
                rights: List[float] = []
                bottoms: List[float] = []
                for w in group:
                    loc = w.get("location") or {}
                    left = float(loc.get("left", 0))
                    top = float(loc.get("top", 0))
                    width = float(loc.get("width", 0))
                    height = float(loc.get("height", 0))
                    lefts.append(left)
                    tops.append(top)
                    rights.append(left + width)
                    bottoms.append(top + height)
                if lefts and tops:
                    best_bbox = [min(lefts), min(tops), max(rights), max(bottoms)]
                    try:
                        img = Image.open(io.BytesIO(img_bytes_list[page_idx]))
                        img = ImageOps.exif_transpose(img)
                        w, h = img.size
                    except Exception:
                        w, h = 1, 1
                    norm_bbox = _abs_to_norm_bbox(best_bbox, w, h)
                    if norm_bbox:
                        it["handwriting_bbox"] = norm_bbox
                        it["line_bbox"] = norm_bbox
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

        if best_idx is None:
            continue

        def _line_text_bbox(line: Dict[str, Any]) -> Tuple[str, List[float]]:
            eng_words = [w for w in (line.get("words") or []) if re.search(r"[A-Za-z]", str(w.get("text") or ""))]
            if eng_words:
                text = " ".join([str(w.get("text") or "") for w in eng_words]).strip()
                left = min(float(w["left"]) for w in eng_words)
                top = min(float(w["top"]) for w in eng_words)
                right = max(float(w["left"]) + float(w["width"]) for w in eng_words)
                bottom = max(float(w["top"]) + float(w["height"]) for w in eng_words)
                return text, [left, top, right, bottom]
            return str(line.get("text") or ""), list(line.get("bbox") or [0, 0, 0, 0])

        def _is_related_bbox(base_bbox: List[float], other_bbox: List[float]) -> bool:
            base_h = base_bbox[3] - base_bbox[1]
            other_h = other_bbox[3] - other_bbox[1]
            pad = max(8, int(max(base_h, other_h) * 0.2))
            return not (
                other_bbox[2] < base_bbox[0] - pad
                or other_bbox[0] > base_bbox[2] + pad
                or other_bbox[3] < base_bbox[1] - pad
                or other_bbox[1] > base_bbox[3] + pad
            )

        base_text, base_bbox = _line_text_bbox(lines[best_idx])
        used_set = ocr_used.get(page_idx, set())
        group_indices: List[int] = []
        group_texts: List[str] = []
        group_bboxes: List[List[float]] = []
        for idx_ln, ln in enumerate(lines):
            if idx_ln in used_set:
                continue
            text, bbox = _line_text_bbox(ln)
            if idx_ln == best_idx or _is_related_bbox(base_bbox, bbox):
                group_indices.append(idx_ln)
                if text:
                    group_texts.append(text)
                group_bboxes.append(bbox)

        for idx_ln in group_indices:
            ocr_used.setdefault(page_idx, set()).add(idx_ln)

        llm_text_norm = normalize_answer(str(it.get("llm_text") or ""))
        best_text = base_text
        best_ratio_group = best_ratio
        if group_texts:
            if llm_text_norm:
                for text in group_texts:
                    cand_norm = normalize_answer(text)
                    if not cand_norm:
                        continue
                    ratio = difflib.SequenceMatcher(None, llm_text_norm, cand_norm).ratio()
                    if ratio > best_ratio_group:
                        best_ratio_group = ratio
                        best_text = text
            else:
                best_text = group_texts[0]

        it["ocr_text"] = best_text
        it["ocr_text_candidates"] = group_texts
        it["ocr_match_ratio"] = best_ratio_group
        if llm_text_norm and best_ratio_group >= ocr_match_thr:
            match_method = f"text_sim_{best_ratio_group:.2f}"
        it["match_method"] = match_method
        # Low OCR match is tracked in fields, but not appended to note.

        if group_bboxes:
            left = min(b[0] for b in group_bboxes)
            top = min(b[1] for b in group_bboxes)
            right = max(b[2] for b in group_bboxes)
            bottom = max(b[3] for b in group_bboxes)
            best_bbox = [left, top, right, bottom]
        else:
            best_bbox = base_bbox
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
    # Match against all active learning bases for this student
    for it in items:
        it["student_text"] = it.get("llm_text") or ""
    with db() as conn:
        active_base_ids = _get_active_base_ids(conn, student_id)
        if not active_base_ids:
            logger.warning(f"[AI GRADING DEBUG] Student {student_id} has no active learning bases")
            active_base_ids = []
        else:
            logger.info(f"[AI GRADING DEBUG] Matching against {len(active_base_ids)} active knowledge bases: {active_base_ids}")
        items = _attach_kb_matches(conn, active_base_ids, items)

    # Compare LLM vs OCR
    sim_thr = float(os.environ.get("EL_MATCH_SIM_THRESHOLD", "0.88"))
    for it in items:
        llm_text = normalize_answer(str(it.get("llm_text") or ""))
        candidates = it.get("ocr_text_candidates") or []
        if not candidates:
            candidates = [str(it.get("ocr_text") or "")]

        cand_norms: List[Tuple[str, str]] = []
        for cand in candidates:
            norm = normalize_answer(str(cand))
            if norm:
                cand_norms.append((str(cand), norm))

        if llm_text and cand_norms:
            best_ratio = 0.0
            best_text = cand_norms[0][0]
            for raw_text, norm_text in cand_norms:
                ratio = difflib.SequenceMatcher(None, llm_text, norm_text).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_text = raw_text
            it["ocr_text"] = best_text
            it["consistency_ok"] = best_ratio >= sim_thr
            ratio = best_ratio
        elif not llm_text and not cand_norms:
            ratio = 1.0
            it["consistency_ok"] = True
        else:
            ratio = 0.0
            it["consistency_ok"] = False

        it["consistency_ratio"] = ratio

        if not it["consistency_ok"] and (llm_text or cand_norms):
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

    def needs_review_mark(item: Dict[str, Any]) -> bool:
        """Match frontend 'warn' logic for inconsistent answers."""
        if item.get("is_correct") is not True:
            return False
        if item.get("consistency_ok") is False:
            return True
        llm_text = normalize_answer(str(item.get("llm_text") or ""))
        ref_text = normalize_answer(str(item.get("matched_en_text") or ""))
        return bool(llm_text and ref_text and llm_text != ref_text)

    def draw_question_mark(draw, bbox, color="#f59e0b"):
        """Draw a question mark to the right of the bbox."""
        x1, y1, x2, y2 = bbox
        bbox_h = y2 - y1
        font = ImageFont.load_default()
        mark = "?"
        if hasattr(draw, "textbbox"):
            left, top, right, bottom = draw.textbbox((0, 0), mark, font=font)
            text_w = right - left
            text_h = bottom - top
        elif hasattr(font, "getbbox"):
            left, top, right, bottom = font.getbbox(mark)
            text_w = right - left
            text_h = bottom - top
        else:
            text_w, text_h = font.getsize(mark)
        x = x2 + 8
        y = y1 + max(0, int((bbox_h - text_h) / 2))
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            draw.text((x + dx, y + dy), mark, font=font, fill="#000000")
        draw.text((x, y), mark, font=font, fill=color)

    def draw_warning_ellipse(draw, bbox, color="#f59e0b", width=6):
        """Draw a yellow ellipse around the answer bbox."""
        draw_red_circle(draw, bbox, color=color, width=width)

    # Use white-balanced images for graded output
    for page_idx, img_bytes in enumerate(wb_img_bytes_list):
        try:
            img = Image.open(io.BytesIO(img_bytes))
            img = ImageOps.exif_transpose(img)
            draw = ImageDraw.Draw(img)
            w, h = img.size
            for it in items:
                if int(it.get("page_index") or 1) != (page_idx + 1):
                    continue
                bbox = it.get("handwriting_bbox") or it.get("line_bbox")
                if not (isinstance(bbox, list) and len(bbox) == 4):
                    continue
                abs_bbox = _bbox_to_abs(bbox, w, h)
                if not abs_bbox:
                    continue
                is_correct = it.get("is_correct")
                is_uncertain = (is_correct is None) or needs_review_mark(it)
                if is_uncertain:
                    draw_warning_ellipse(draw, abs_bbox, color="#f59e0b", width=6)
                    draw_question_mark(draw, abs_bbox, color="#f59e0b")
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
    _save_crop_images(wb_img_bytes_list, items, force_save=True)

    # Match session
    matched_session = None
    with db() as conn:
        matched_session = _match_session_by_items(conn, student_id, base_id, items)

    # Extract date from OCR results
    extracted_date = _extract_date_from_ocr(ocr_raw)
    if extracted_date:
        logger.info(f"[AI GRADING DEBUG] Extracted date from OCR: {extracted_date}")

    # Extract UUID from OCR results
    uuid_info = _extract_uuid_from_ocr(ocr_raw)
    if uuid_info.get("uuid"):
        logger.info(f"[AI GRADING DEBUG] Extracted UUID: {uuid_info['uuid']} (conf={uuid_info['confidence']:.2f}, consistent={uuid_info['consistent']})")

    bundle_id = f"debug_{uuid.uuid4().hex}"
    if os.environ.get("EL_AI_BUNDLE_SAVE", "1") == "1":
        _save_ai_bundle(bundle_id, llm_raw or {}, ocr_raw or {}, [], graded_image_urls, items)
    return {
        "items": items,
        "image_urls": image_urls,
        "graded_image_urls": graded_image_urls,
        "debug_overlay_urls": debug_overlay_urls,
        "image_count": len(img_bytes_list),
        "page_order": page_order,
        "matched_session": matched_session,
        "extracted_date": extracted_date,
        "worksheet_uuid": uuid_info.get("uuid"),
        "uuid_info": uuid_info,
        "bundle_id": bundle_id,
    }


def analyze_ai_photos(account_id: int, student_id: Optional[int], base_id: Optional[int] = None, uploads: List[UploadFile] = None) -> Dict:
    """LLM analysis + Baidu OCR recognition with merging.

    Args:
        student_id: Student ID
        base_id: (Deprecated) Legacy parameter, now ignored. Matching uses all active learning bases.
        uploads: List of uploaded image files

    Returns:
        Dict with items, image_urls, etc.
    """
    if not uploads:
        raise ValueError("no files uploaded")

    from .openai_vision import analyze_freeform_sheet, is_configured  # type: ignore

    if not is_configured():
        raise ValueError("AI 配置不可用（缺少 API KEY）")

    ensure_media_dir()
    os.makedirs(os.path.join(MEDIA_DIR, "uploads"), exist_ok=True)
    os.makedirs(os.path.join(MEDIA_DIR, "uploads", "graded"), exist_ok=True)

    logger = logging.getLogger("uvicorn.error")

    student_id = int(student_id) if student_id else None
    base_id = int(base_id) if base_id else None
    resolved_student_id = student_id
    resolved_base_id = base_id
    resolved_student_name = None
    resolved_base_name = None
    resolved_session_id = None

    img_bytes_list: List[bytes] = []
    saved_paths: List[str] = []
    file_student_id = resolved_student_id or 0
    for idx, upload in enumerate(uploads, start=1):
        raw_bytes = upload.file.read()
        img_bytes, ext = _normalize_upload_image(raw_bytes, upload.filename or "")
        fname = f"ai_sheet_{file_student_id}_{idx}_{uuid.uuid4().hex}{ext}"
        out_path = os.path.join(MEDIA_DIR, "uploads", fname)
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
    timeout_llm = int(os.environ.get("EL_AI_TIMEOUT_SECONDS", "90"))  # Increased from 30 to 90 seconds
    timeout_ocr = int(os.environ.get("EL_OCR_TIMEOUT_SECONDS", "60"))  # Increased from 30 to 60 seconds
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

    ex = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    fut_llm = ex.submit(_run_llm)
    fut_ocr = ex.submit(_run_ocr)
    try:
        llm_start = time.time()
        try:
            llm_raw = fut_llm.result(timeout=timeout_llm)
            llm_elapsed = time.time() - llm_start
            logger.info(f"[AI GRADING] LLM completed in {llm_elapsed:.1f}s")
        except concurrent.futures.TimeoutError:
            llm_elapsed = time.time() - llm_start
            logger.error(f"[AI GRADING] LLM timeout after {llm_elapsed:.1f}s (limit: {timeout_llm}s)")
            fut_llm.cancel()
            if not fut_ocr.done():
                fut_ocr.cancel()
            raise ValueError(f"LLM 识别超时（{llm_elapsed:.0f}秒），请稍后重试或增加超时限制")
        except Exception as e:
            llm_elapsed = time.time() - llm_start
            error_msg = str(e)
            logger.error(f"[AI GRADING] LLM failed after {llm_elapsed:.1f}s: {e}")
            if not fut_ocr.done():
                fut_ocr.cancel()

            # Provide user-friendly error messages
            if "Connection error" in error_msg or "ConnectionError" in str(type(e).__name__):
                raise ValueError(f"LLM 识别网络连接失败，请检查网络连接后重试。如果问题持续出现，可能是 API 服务暂时不可用。(耗时: {llm_elapsed:.1f}秒)")
            elif "timeout" in error_msg.lower():
                raise ValueError(f"LLM 识别超时（{llm_elapsed:.0f}秒），图片可能过大或网络较慢，请重试")
            else:
                raise ValueError(f"LLM 识别失败: {error_msg} (耗时: {llm_elapsed:.1f}秒)")

        ocr_start = time.time()
        try:
            ocr_raw = fut_ocr.result(timeout=timeout_ocr)
            ocr_elapsed = time.time() - ocr_start
            logger.info(f"[AI GRADING] OCR completed in {ocr_elapsed:.1f}s")
        except concurrent.futures.TimeoutError:
            ocr_elapsed = time.time() - ocr_start
            logger.error(f"[AI GRADING] OCR timeout after {ocr_elapsed:.1f}s (limit: {timeout_ocr}s)")
            if not fut_llm.done():
                fut_llm.cancel()
            raise ValueError(f"OCR 识别超时（{ocr_elapsed:.0f}秒），请稍后重试或增加超时限制")
        except Exception as e:
            ocr_elapsed = time.time() - ocr_start
            logger.error(f"[AI GRADING] OCR failed after {ocr_elapsed:.1f}s: {e}")
            if not fut_llm.done():
                fut_llm.cancel()
            raise ValueError(f"OCR 识别失败: {e}")
    finally:
        ex.shutdown(wait=False, cancel_futures=True)

    # ========== 页码检测与重排 ==========
    # 根据 OCR 检测到的页码（如"第1页"、"第2页"）自动重排页面顺序
    # 这解决了用户上传照片顺序错误导致的匹配问题
    page_reorder_mapping: Dict[int, int] = {}
    page_order = list(range(len(img_bytes_list)))
    try:
        ocr_raw, wb_img_bytes_list, page_reorder_mapping = _reorder_by_page_numbers(
            ocr_raw, wb_img_bytes_list, logger
        )
        # 同时重排原始图片列表（用于保存和调试）
        if page_reorder_mapping and any(k != v for k, v in page_reorder_mapping.items()):
            order = sorted(page_reorder_mapping.keys(), key=lambda x: page_reorder_mapping[x])
            img_bytes_list = [img_bytes_list[info] for info in order]
            # 重排保存路径
            saved_paths = [saved_paths[info] for info in order]
            page_order = order
    except Exception as e:
        logger.warning(f"[PAGE REORDER] Error during page reordering: {e}, continuing with original order")
        page_reorder_mapping = {i: i for i in range(len(ocr_raw.get("pages", [])))}

    # Parse LLM raw data (handle both sections format and flat items format)
    items_raw = []

    # Get the actual LLM response (may be wrapped in raw_llm)
    llm_data = llm_raw.get("raw_llm") if "raw_llm" in llm_raw else llm_raw
    sections = llm_data.get("sections") if isinstance(llm_data, dict) else None
    if isinstance(sections, list):
        llm_zero_based = _llm_pages_zero_based(sections)
    else:
        llm_zero_based = _llm_pages_zero_based(llm_raw.get("items") or [])
    total_pages = len(ocr_raw.get("pages") or []) or len(img_bytes_list)
    ocr_section_keys = _ocr_section_keys_by_page(ocr_raw)
    llm_section_keys = _llm_section_keys_by_page(
        sections if isinstance(sections, list) else [],
        llm_zero_based,
        page_reorder_mapping,
    )
    page_map_by_section = _build_page_mapping_by_sections(
        llm_section_keys, ocr_section_keys, total_pages, logger
    )

    if isinstance(sections, list):
        logger.info(f"[AI GRADING] Found {len(sections)} sections in LLM response")
        # Flatten sections into items (preserve section order and titles)
        for sec in sections:
            if not isinstance(sec, dict):
                continue
            sec_title = sec.get("title") or ""
            sec_type = sec.get("type") or ""
            sec_items = sec.get("items") or []
            logger.info(f"[AI GRADING] Processing section: '{sec_title}' (type={sec_type}, items={len(sec_items)})")
            # Mark first item of this section with title
            for idx, it in enumerate(sec_items):
                if not isinstance(it, dict):
                    continue
                # 获取 LLM 返回的原始页码并映射（1-based）
                llm_pg_raw = it.get("pg") if "pg" in it else it.get("page_index")
                llm_pg0 = _llm_pg_to_zero_based(llm_pg_raw, llm_zero_based)
                mapped_pg0 = page_reorder_mapping.get(llm_pg0, llm_pg0)
                mapped_pg1 = mapped_pg0 + 1
                mapped_pg1 = page_map_by_section.get(mapped_pg1, mapped_pg1)
                # Convert short field names to long names
                items_raw.append({
                    "q": it.get("q"),
                    "section_title": sec_title if idx == 0 else "",  # Only first item has title
                    "section_type": sec_type,
                    "zh_hint": it.get("hint") or "",
                    "student_text": it.get("ans") or "",
                    "is_correct": it.get("ok"),
                    "confidence": it.get("conf"),
                    "page_index": mapped_pg1,
                    "original_page_index": llm_pg0 + 1,  # 保留原始页码用于调试（1-based）
                    "note": it.get("note") or "",
                })
    else:
        logger.warning("[AI GRADING] No sections found in LLM response, using flat items format")
        # Fallback to pre-flattened items from analyze_freeform_sheet
        raw_items = llm_raw.get("items") or []
        # 应用页码映射
        items_raw = []
        for it in raw_items:
            if not isinstance(it, dict):
                items_raw.append(it)
                continue
            llm_pg_raw = it.get("page_index") if "page_index" in it else it.get("pg")
            llm_pg0 = _llm_pg_to_zero_based(llm_pg_raw, llm_zero_based)
            mapped_pg0 = page_reorder_mapping.get(llm_pg0, llm_pg0)
            mapped_pg1 = mapped_pg0 + 1
            mapped_pg1 = page_map_by_section.get(mapped_pg1, mapped_pg1)
            new_it = dict(it)
            new_it["page_index"] = mapped_pg1
            new_it["original_page_index"] = llm_pg0 + 1
            items_raw.append(new_it)

    logger.info(f"[AI GRADING] LLM items_raw: {len(items_raw)}; OCR pages: {len(ocr_raw.get('pages', []))}")

    # Parse LLM items
    items: List[Dict] = []
    for idx, it in enumerate(items_raw, start=1):
        if not isinstance(it, dict):
            continue
        zh_hint = it.get("zh_hint") or ""
        if _is_header_hint(str(zh_hint)):
            continue
        # FIXED: Use global sequential index as position to avoid duplicates across sections
        # Store original question number in 'q' field for display purposes
        position = idx
        conf_val = it.get("confidence")
        items.append(
            {
                "position": position,
                "q": it.get("q"),  # Original question number within section
                "section_type": it.get("section_type") or "",
                "section_title": it.get("section_title") or "",
                "zh_hint": zh_hint,
                "llm_text": it.get("student_text") or "",
                "is_correct": it.get("is_correct") if "is_correct" in it else None,
                "confidence": float(conf_val) if conf_val is not None else None,
                "page_index": int(it.get("page_index") or 1),
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
        words = _normalize_ocr_words(raw)
        if words:
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

    # LLM section keys per page (used to avoid cross-section fallback)
    llm_section_keys_by_page: Dict[int, set] = {}
    for it in items:
        sec = str(it.get("section_type") or "")
        if not sec:
            continue
        page_idx0 = max(0, int(it.get("page_index") or 1) - 1)
        llm_section_keys_by_page.setdefault(page_idx0, set()).add(sec)

    # Geometry-based OCR grouping (robust to OCR order)
    handwriting_groups_by_page: Dict[int, Dict[Tuple[str, int], List[Dict[str, Any]]]] = {}
    question_numbers_by_page: Dict[int, set] = {}
    section_keys_by_page: Dict[int, set] = {}
    for page_idx, words in ocr_by_page.items():
        groups, sec_keys, q_nums = _group_handwriting_by_question_geo(words)
        handwriting_groups_by_page[page_idx] = groups
        question_numbers_by_page[page_idx] = q_nums
        section_keys_by_page[page_idx] = sec_keys

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
        page_idx = max(0, int(it.get("page_index") or 1) - 1)
        q_num = int(it.get("q") or 0)
        it["ocr_text"] = ""
        it["match_method"] = "no_match"

        section_key = str(it.get("section_type") or "")
        group_key = (section_key, q_num)
        groups_for_page = handwriting_groups_by_page.get(page_idx, {}) or {}
        group = groups_for_page.get(group_key) if q_num else None

        lines = ocr_lines_by_page.get(page_idx) or []

        if not group and q_num:
            same_q_keys = [key for key in groups_for_page.keys() if key[1] == q_num]
            llm_sections = llm_section_keys_by_page.get(page_idx, set())
            if len(same_q_keys) == 1 and len(llm_sections) <= 1:
                group = groups_for_page[same_q_keys[0]]
            elif same_q_keys:
                continue
        if not group and q_num and q_num in question_numbers_by_page.get(page_idx, set()):
            continue
        if not group and not lines:
            continue
        if group:
            merged_lines = _build_ocr_lines(group, items=items)
            candidate_texts = [ln.get("text") for ln in merged_lines if ln.get("text")]
            if not candidate_texts:
                candidate_texts = [str(w.get("words") or "").strip() for w in group if str(w.get("words") or "").strip()]
            llm_text_norm = normalize_answer(str(it.get("llm_text") or ""))
            best_text = candidate_texts[0] if candidate_texts else ""
            best_ratio_group = 0.0
            if llm_text_norm and candidate_texts:
                for cand in candidate_texts:
                    cand_norm = normalize_answer(cand)
                    if not cand_norm:
                        continue
                    ratio = difflib.SequenceMatcher(None, llm_text_norm, cand_norm).ratio()
                    if ratio > best_ratio_group:
                        best_ratio_group = ratio
                        best_text = cand
            if not llm_text_norm or best_ratio_group >= ocr_match_thr:
                it["ocr_text"] = best_text
                it["ocr_text_candidates"] = candidate_texts
                it["ocr_match_ratio"] = best_ratio_group
                it["match_method"] = "question_group"

                lefts: List[float] = []
                tops: List[float] = []
                rights: List[float] = []
                bottoms: List[float] = []
                for w in group:
                    loc = w.get("location") or {}
                    left = float(loc.get("left", 0))
                    top = float(loc.get("top", 0))
                    width = float(loc.get("width", 0))
                    height = float(loc.get("height", 0))
                    lefts.append(left)
                    tops.append(top)
                    rights.append(left + width)
                    bottoms.append(top + height)
                if lefts and tops:
                    best_bbox = [min(lefts), min(tops), max(rights), max(bottoms)]
                    try:
                        img = Image.open(io.BytesIO(img_bytes_list[page_idx]))
                        img = ImageOps.exif_transpose(img)
                        w, h = img.size
                    except Exception:
                        w, h = 1, 1
                    norm_bbox = _abs_to_norm_bbox(best_bbox, w, h)
                    if norm_bbox:
                        it["handwriting_bbox"] = norm_bbox
                        it["line_bbox"] = norm_bbox
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

        if best_idx is None:
            continue

        def _line_text_bbox(line: Dict[str, Any]) -> Tuple[str, List[float]]:
            eng_words = [w for w in (line.get("words") or []) if re.search(r"[A-Za-z]", str(w.get("text") or ""))]
            if eng_words:
                text = " ".join([str(w.get("text") or "") for w in eng_words]).strip()
                left = min(float(w["left"]) for w in eng_words)
                top = min(float(w["top"]) for w in eng_words)
                right = max(float(w["left"]) + float(w["width"]) for w in eng_words)
                bottom = max(float(w["top"]) + float(w["height"]) for w in eng_words)
                return text, [left, top, right, bottom]
            return str(line.get("text") or ""), list(line.get("bbox") or [0, 0, 0, 0])

        def _is_related_bbox(base_bbox: List[float], other_bbox: List[float]) -> bool:
            base_h = base_bbox[3] - base_bbox[1]
            other_h = other_bbox[3] - other_bbox[1]
            pad = max(8, int(max(base_h, other_h) * 0.2))
            return not (
                other_bbox[2] < base_bbox[0] - pad
                or other_bbox[0] > base_bbox[2] + pad
                or other_bbox[3] < base_bbox[1] - pad
                or other_bbox[1] > base_bbox[3] + pad
            )

        base_text, base_bbox = _line_text_bbox(lines[best_idx])
        used_set = ocr_used.get(page_idx, set())
        group_indices: List[int] = []
        group_texts: List[str] = []
        group_bboxes: List[List[float]] = []
        for idx_ln, ln in enumerate(lines):
            if idx_ln in used_set:
                continue
            text, bbox = _line_text_bbox(ln)
            if idx_ln == best_idx or _is_related_bbox(base_bbox, bbox):
                group_indices.append(idx_ln)
                if text:
                    group_texts.append(text)
                group_bboxes.append(bbox)

        for idx_ln in group_indices:
            ocr_used.setdefault(page_idx, set()).add(idx_ln)

        llm_text_norm = normalize_answer(str(it.get("llm_text") or ""))
        best_text = base_text
        best_ratio_group = best_ratio
        if group_texts:
            if llm_text_norm:
                for text in group_texts:
                    cand_norm = normalize_answer(text)
                    if not cand_norm:
                        continue
                    ratio = difflib.SequenceMatcher(None, llm_text_norm, cand_norm).ratio()
                    if ratio > best_ratio_group:
                        best_ratio_group = ratio
                        best_text = text
            else:
                best_text = group_texts[0]

        it["ocr_text"] = best_text
        it["ocr_text_candidates"] = group_texts
        it["ocr_match_ratio"] = best_ratio_group
        if llm_text_norm and best_ratio_group >= ocr_match_thr:
            match_method = f"text_sim_{best_ratio_group:.2f}"
        it["match_method"] = match_method
        # Low OCR match is tracked in fields, but not appended to note.

        if group_bboxes:
            left = min(b[0] for b in group_bboxes)
            top = min(b[1] for b in group_bboxes)
            right = max(b[2] for b in group_bboxes)
            bottom = max(b[3] for b in group_bboxes)
            best_bbox = [left, top, right, bottom]
        else:
            best_bbox = base_bbox
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
    # Match against all active learning bases for this student
    for it in items:
        it["student_text"] = it.get("llm_text") or ""
    with db() as conn:
        active_base_ids = _get_active_base_ids(conn, student_id)
        if not active_base_ids:
            logger.warning(f"[AI GRADING] Student {student_id} has no active learning bases")
            active_base_ids = []  # Will result in no matches
        else:
            logger.info(f"[AI GRADING] Matching against {len(active_base_ids)} active knowledge bases: {active_base_ids}")
        items = _attach_kb_matches(conn, active_base_ids, items)

    # Compare LLM vs OCR
    sim_thr = float(os.environ.get("EL_MATCH_SIM_THRESHOLD", "0.88"))
    for it in items:
        llm_text = normalize_answer(str(it.get("llm_text") or ""))
        candidates = it.get("ocr_text_candidates") or []
        if not candidates:
            candidates = [str(it.get("ocr_text") or "")]

        cand_norms: List[Tuple[str, str]] = []
        for cand in candidates:
            norm = normalize_answer(str(cand))
            if norm:
                cand_norms.append((str(cand), norm))

        if llm_text and cand_norms:
            best_ratio = 0.0
            best_text = cand_norms[0][0]
            for raw_text, norm_text in cand_norms:
                ratio = difflib.SequenceMatcher(None, llm_text, norm_text).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_text = raw_text
            it["ocr_text"] = best_text
            it["consistency_ok"] = best_ratio >= sim_thr
            ratio = best_ratio
        elif not llm_text and not cand_norms:
            ratio = 1.0
            it["consistency_ok"] = True
        else:
            ratio = 0.0
            it["consistency_ok"] = False

        it["consistency_ratio"] = ratio

        # Lower confidence if inconsistent
        if not it["consistency_ok"] and (llm_text or cand_norms):
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
        active_base_ids = _get_active_base_ids(conn, student_id)
        items = _attach_kb_matches(conn, active_base_ids, items)

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

    def needs_review_mark(item: Dict[str, Any]) -> bool:
        """Match frontend 'warn' logic for inconsistent answers."""
        if item.get("is_correct") is not True:
            return False
        if item.get("consistency_ok") is False:
            return True
        llm_text = normalize_answer(str(item.get("llm_text") or ""))
        ref_text = normalize_answer(str(item.get("matched_en_text") or ""))
        return bool(llm_text and ref_text and llm_text != ref_text)

    def draw_question_mark(draw, bbox, color="#f59e0b"):
        """Draw a question mark to the right of the bbox."""
        x1, y1, x2, y2 = bbox
        bbox_h = y2 - y1
        font = ImageFont.load_default()
        mark = "?"
        if hasattr(draw, "textbbox"):
            left, top, right, bottom = draw.textbbox((0, 0), mark, font=font)
            text_w = right - left
            text_h = bottom - top
        elif hasattr(font, "getbbox"):
            left, top, right, bottom = font.getbbox(mark)
            text_w = right - left
            text_h = bottom - top
        else:
            text_w, text_h = font.getsize(mark)
        x = x2 + 8
        y = y1 + max(0, int((bbox_h - text_h) / 2))
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            draw.text((x + dx, y + dy), mark, font=font, fill="#000000")
        draw.text((x, y), mark, font=font, fill=color)

    def draw_warning_ellipse(draw, bbox, color="#f59e0b", width=6):
        """Draw a yellow ellipse around the answer bbox."""
        draw_red_circle(draw, bbox, color=color, width=width)

    # Use white-balanced images for graded output
    for page_idx, img_bytes in enumerate(wb_img_bytes_list):
        try:
            img = Image.open(io.BytesIO(img_bytes))
            img = ImageOps.exif_transpose(img)
            draw = ImageDraw.Draw(img)
            w, h = img.size
            for it in items:
                if int(it.get("page_index") or 1) != (page_idx + 1):
                    continue
                bbox = it.get("handwriting_bbox") or it.get("line_bbox")
                if not (isinstance(bbox, list) and len(bbox) == 4):
                    continue
                abs_bbox = _bbox_to_abs(bbox, w, h)
                if not abs_bbox:
                    continue
                is_correct = it.get("is_correct")
                is_uncertain = (is_correct is None) or needs_review_mark(it)
                if is_uncertain:
                    draw_warning_ellipse(draw, abs_bbox, color="#f59e0b", width=6)
                    draw_question_mark(draw, abs_bbox, color="#f59e0b")
                elif is_correct:
                    # Correct: draw green checkmark to the right
                    draw_checkmark(draw, abs_bbox, color="#19c37d", width=6)
                else:
                    # Incorrect: draw red ellipse around the answer
                    draw_red_circle(draw, abs_bbox, color="#ef4444", width=6)
            graded_fname = f"graded_{file_student_id}_{page_idx + 1}_{uuid.uuid4().hex}.jpg"
            graded_path = os.path.join(MEDIA_DIR, "uploads", "graded", graded_fname)
            img.save(graded_path, format="JPEG", quality=90)
            graded_image_urls.append(f"/media/uploads/graded/{graded_fname}")
        except Exception as e:
            logger.error(f"[AI GRADING] Failed to generate graded image: {e}")
            graded_image_urls.append("")

    # Save crop images (only when SAVE_CROP_IMAGES=1)
    _save_crop_images(wb_img_bytes_list, items)

    # Extract UUID from OCR results
    uuid_info = _extract_uuid_from_ocr(ocr_raw)
    if uuid_info.get("uuid"):
        logger.info(f"[AI GRADING] Extracted UUID: {uuid_info['uuid']} (conf={uuid_info['confidence']:.2f}, consistent={uuid_info['consistent']})")

    if resolved_student_id is None or resolved_base_id is None:
        if uuid_info.get("uuid"):
            with db() as conn:
                resolved = _resolve_session_by_uuid(conn, uuid_info["uuid"], account_id)
            if resolved:
                resolved_session_id = int(resolved.get("id"))
                resolved_student_id = int(resolved.get("student_id"))
                resolved_base_id = int(resolved.get("base_id"))
                resolved_student_name = resolved.get("student_name")
                resolved_base_name = resolved.get("base_name")
        if resolved_student_id is None or resolved_base_id is None:
            if uuid_info.get("uuid"):
                msg = f"试卷编号 {uuid_info['uuid']} 未匹配到学生，请在页面选择学生/资料库或确认该编号已入库。"
            else:
                msg = "未识别到试卷编号，无法匹配学生。请在页面选择学生/资料库或确保试卷编号清晰可识别。"
            logger.warning(f"[AI GRADING] {msg}")
            raise ValueError(msg)

    # Match to existing session
    matched_session = None
    if resolved_student_id is not None and resolved_base_id is not None:
        with db() as conn:
            matched_session = _match_session_by_items(conn, resolved_student_id, resolved_base_id, items)

    # Extract date from OCR results
    extracted_date = _extract_date_from_ocr(ocr_raw)
    if extracted_date:
        logger.info(f"[AI GRADING] Extracted date from OCR: {extracted_date}")

    if os.environ.get("EL_AI_DEBUG_SAVE", "1") == "1":
        _save_debug_bundle(img_bytes_list, llm_raw or {}, ocr_raw or {})

    image_urls = [f"/media/uploads/{os.path.basename(p)}" for p in saved_paths]
    bundle_id = f"ai_{uuid.uuid4().hex}"
    if os.environ.get("EL_AI_BUNDLE_SAVE", "1") == "1":
        _save_ai_bundle(bundle_id, llm_raw or {}, ocr_raw or {}, image_urls, graded_image_urls, items)
    return {
        "items": items,
        "image_urls": image_urls,
        "graded_image_urls": graded_image_urls,
        "image_count": len(saved_paths),
        "page_order": page_order,
        "matched_session": matched_session,
        "extracted_date": extracted_date,
        "worksheet_uuid": uuid_info.get("uuid"),
        "uuid_info": uuid_info,
        "bundle_id": bundle_id,
        "resolved_student_id": resolved_student_id,
        "resolved_base_id": resolved_base_id,
        "resolved_student_name": resolved_student_name,
        "resolved_base_name": resolved_base_name,
        "resolved_session_id": resolved_session_id,
    }


def confirm_ai_extracted(
    student_id: int,
    base_id: int,
    items: List[Dict],
    extracted_date: str = None,
    worksheet_uuid: str = None,
    force_duplicate: bool = False,
    bundle_id: Optional[str] = None,
) -> Dict:
    """Create session/submission from AI-extracted items and update stats.

    Args:
        student_id: Student ID
        base_id: Knowledge base ID
        items: List of extracted items
        extracted_date: Date extracted from worksheet (YYYY-MM-DD format)
        worksheet_uuid: Worksheet UUID (e.g., ES-0055-CF12D2) - primary duplicate check
        force_duplicate: If True, allow duplicate submission without checking
        bundle_id: Optional AI bundle ID for raw LLM/OCR and images

    Returns:
        Dict with session info or duplicate warning
    """
    use_items = [it for it in items if bool(it.get("include", True))]
    if not use_items:
        raise ValueError("没有可入库的题目")

    # Find canonical session for this worksheet UUID first.
    # Prefer the originally generated worksheet record (non-AI_EXTRACT) when present.
    uuid_session_row = None
    if worksheet_uuid:
        with db() as conn:
            uuid_session_row = conn.execute(
                """
                SELECT
                    ps.id,
                    ps.status,
                    ps.created_at,
                    ps.params_json,
                    (SELECT id FROM submissions s WHERE s.session_id = ps.id ORDER BY s.submitted_at DESC, s.id DESC LIMIT 1) AS latest_submission_id
                FROM practice_sessions ps
                WHERE ps.student_id = ?
                  AND ps.base_id = ?
                  AND ps.practice_uuid = ?
                ORDER BY
                  CASE WHEN COALESCE(ps.params_json, '') LIKE '%AI_EXTRACT%' THEN 1 ELSE 0 END ASC,
                  ps.id ASC
                LIMIT 1
                """,
                (student_id, base_id, worksheet_uuid),
            ).fetchone()

    # Check for duplicate submission (unless force_duplicate is True)
    # Priority: UUID > Date
    if not force_duplicate:
        with db() as conn:
            # Try UUID-based duplicate check first (more reliable)
            if worksheet_uuid:
                existing = None
                if uuid_session_row and uuid_session_row["latest_submission_id"] is not None:
                    latest_submission_id = int(uuid_session_row["latest_submission_id"])
                    existing = conn.execute(
                        """
                        SELECT
                          ps.id,
                          ps.created_at,
                          ps.practice_uuid,
                          COUNT(pr.id) as total_items,
                          SUM(CASE WHEN pr.is_correct = 1 THEN 1 ELSE 0 END) as correct_items
                        FROM practice_sessions ps
                        LEFT JOIN practice_results pr ON pr.submission_id = ?
                        WHERE ps.id = ?
                        GROUP BY ps.id
                        """,
                        (latest_submission_id, int(uuid_session_row["id"])),
                    ).fetchone()

                if existing:
                    # Found duplicate submission by UUID (only warn when a graded result already exists)
                    total_items = int(existing["total_items"] or 0)
                    correct_items = int(existing["correct_items"] or 0)
                    if total_items <= 0:
                        existing = None
                if existing:
                    accuracy = (correct_items / total_items * 100) if total_items > 0 else 0
                    return {
                        "duplicate_warning": True,
                        "existing_session_id": existing["id"],
                        "existing_uuid": worksheet_uuid,
                        "existing_created_at": existing["created_at"],
                        "existing_total": total_items,
                        "existing_correct": correct_items,
                        "existing_accuracy": accuracy,
                        "message": f"检测到重复提交：试卷编号 {worksheet_uuid} 已经提交过（共{total_items}题，正确{correct_items}题，正确率{accuracy:.1f}%）。请确认是否继续提交本次照片。"
                    }

            # Fallback: Date-based check (for worksheets without UUID or old records)
            elif extracted_date:
                existing = conn.execute(
                    """
                    SELECT ps.id, ps.created_at, COUNT(pr.id) as total_items,
                           SUM(CASE WHEN pr.is_correct = 1 THEN 1 ELSE 0 END) as correct_items
                    FROM practice_sessions ps
                    LEFT JOIN practice_results pr ON pr.session_id = ps.id
                    WHERE ps.student_id = ?
                      AND ps.created_date = ?
                      AND ps.params_json LIKE '%AI_EXTRACT%'
                    GROUP BY ps.id
                    ORDER BY ps.created_at DESC
                    LIMIT 1
                    """,
                    (student_id, extracted_date)
                ).fetchone()

                if existing:
                    # Found duplicate submission by date
                    accuracy = (existing["correct_items"] / existing["total_items"] * 100) if existing["total_items"] > 0 else 0
                    return {
                        "duplicate_warning": True,
                        "existing_session_id": existing["id"],
                        "existing_date": extracted_date,
                        "existing_created_at": existing["created_at"],
                        "existing_total": existing["total_items"],
                        "existing_correct": existing["correct_items"],
                        "existing_accuracy": accuracy,
                        "message": f"检测到重复提交：{extracted_date} 的试卷已经提交过（共{existing['total_items']}题，正确{existing['correct_items']}题，正确率{accuracy:.1f}%）。如果这是学生重做的试卷，请确认是否再次提交。"
                    }

    matched_session = None
    with db() as conn:
        matched_session = _match_session_by_items(conn, student_id, base_id, use_items)

    # Reuse the canonical worksheet session for this UUID, so repeated submissions
    # stay under the same practice session record.
    reuse_session_id: Optional[int] = None
    if uuid_session_row:
        reuse_session_id = int(uuid_session_row["id"])

    params_json = json.dumps(
        {
            "mode": "EXTERNAL_AI",
            "source": "AI_EXTRACT",
            "matched_session_id": matched_session["session_id"] if matched_session else None,
            "match_ratio": matched_session["match_ratio"] if matched_session else None,
            "extracted_date": extracted_date,
            "worksheet_uuid": worksheet_uuid,
        },
        ensure_ascii=False,
    )
    submitted_at = utcnow_iso()

    with db() as conn:
        if reuse_session_id is None:
            cur = conn.execute(
                """
                INSERT INTO practice_sessions(
                    student_id, base_id, status, params_json,
                    created_at, completed_at, corrected_at, created_date, practice_uuid
                )
                VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    student_id,
                    base_id,
                    "CORRECTED",
                    params_json,
                    submitted_at,
                    submitted_at,
                    submitted_at,
                    extracted_date,
                    worksheet_uuid,
                ),
            )
            session_id = int(cur.lastrowid)
        else:
            session_id = reuse_session_id

        submission_cur = conn.execute(
            """
            INSERT INTO submissions(session_id, item_id, position, submitted_at, image_path, text_raw, source)
            VALUES(?,?,?,?,?,?,?)
            """,
            (session_id, None, None, submitted_at, None, None, "AI_EXTRACT"),
        )
        submission_id = int(submission_cur.lastrowid)

        # store raw ai/ocr choices for audit
        try:
            raw_payload = {"items": use_items}
            if bundle_id:
                raw_payload["bundle_id"] = bundle_id
                bundle_meta = _load_ai_bundle_meta(bundle_id)
                if bundle_meta:
                    raw_payload["bundle_meta"] = {
                        "image_urls": bundle_meta.get("image_urls") or [],
                        "graded_image_urls": bundle_meta.get("graded_image_urls") or [],
                        "saved_at": bundle_meta.get("saved_at"),
                    }
            conn.execute(
                "UPDATE submissions SET text_raw=? WHERE id=?",
                (json.dumps(raw_payload, ensure_ascii=False), submission_id),
            )
        except Exception:
            pass

        existing_ex_by_pos: Dict[int, Any] = {}
        if reuse_session_id is not None:
            ex_rows = conn.execute(
                """
                SELECT id, item_id, position
                FROM exercise_items
                WHERE session_id = ?
                ORDER BY position ASC
                """,
                (session_id,),
            ).fetchall()
            existing_ex_by_pos = {int(r["position"]): r for r in ex_rows}

        results = []
        for idx, it in enumerate(use_items, start=1):
            # For reused sessions keep original positions, otherwise reindex compactly.
            raw_pos = it.get("position")
            position = int(raw_pos) if (reuse_session_id is not None and raw_pos is not None) else idx
            matched_item_id = it.get("matched_item_id")
            item_row = None
            if matched_item_id:
                item_row = conn.execute(
                    "SELECT * FROM items WHERE id=?",
                    (int(matched_item_id),),
                ).fetchone()

            en_text = ""
            zh_hint = str(it.get("zh_hint") or "")
            typ = "WORD"
            normalized = ""
            if item_row:
                en_text = item_row["en_text"]
                zh_hint = item_row["zh_text"] or zh_hint  # 使用 zh_text 而不是 zh_hint
                typ = item_row["item_type"]
                normalized = normalize_answer(en_text)  # Compute from en_text
            else:
                en_text = str(it.get("student_text") or "")
                normalized = normalize_answer(en_text)

            exercise_item_id: int
            existing_ex = existing_ex_by_pos.get(position) if reuse_session_id is not None else None
            if existing_ex is not None:
                exercise_item_id = int(existing_ex["id"])
            else:
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

            stats_item_id = None
            if existing_ex is not None and existing_ex["item_id"] is not None:
                stats_item_id = int(existing_ex["item_id"])
            elif item_row is not None:
                stats_item_id = int(item_row["id"])

            _update_stats(conn, student_id, stats_item_id, is_correct, submitted_at)

            results.append({"position": position, "is_correct": bool(is_correct)})

        if reuse_session_id is not None:
            conn.execute(
                """
                UPDATE practice_sessions
                SET status='CORRECTED',
                    completed_at = COALESCE(completed_at, ?),
                    corrected_at = ?
                WHERE id = ?
                """,
                (submitted_at, submitted_at, session_id),
            )

    correct = sum(1 for r in results if r["is_correct"])
    total = len(results)
    return {
        "session_id": session_id,
        "submission_id": submission_id,
        "total": total,
        "correct": correct,
        "accuracy": (correct / total) if total else 0.0,
    }


def bootstrap_single_child(student_name: str, grade_code: str, account_id: int) -> Dict[str, int]:
    """第一次使用初始化：仅创建学生账户，不创建默认资料库。

    返回：student_id
    """
    from . import db as db_module

    with db() as conn:
        # create student using new db.py function
        student_id = db_module.create_student(conn, student_name, grade=grade_code, account_id=account_id)

    return {"student_id": student_id}


def list_bases(account_id: int, grade_code: Optional[str] = None) -> List[Dict]:
    """List bases. Note: grade_code parameter is deprecated in new schema but kept for API compatibility."""
    from . import db as db_module

    with db() as conn:
        # New schema doesn't have grade_code on bases
        # Return all bases (can filter by is_system if needed)
        bases = db_module.get_bases(conn, account_id=account_id, is_system=None)
        return bases


def create_base(
    name: str,
    grade_code: str,
    is_system: bool = False,
    account_id: Optional[int] = None,
    education_stage: str = None,
    grade: str = None,
    term: str = None,
    version: str = None,
    publisher: str = None,
    editor: str = None,
    notes: str = None
) -> int:
    """Create base. Note: grade_code parameter is deprecated in new schema but kept for API compatibility."""
    from . import db as db_module

    with db() as conn:
        # New schema doesn't use grade_code on bases
        # Only use grade_code fallback if notes is explicitly None (not empty string)
        description = notes if notes is not None else (f"Grade: {grade_code}" if grade_code else None)
        base_id = db_module.create_base(
            conn, name,
            description=description,
            is_system=is_system,
            account_id=account_id,
            education_stage=education_stage,
            grade=grade,
            term=term,
            version=version,
            publisher=publisher,
            editor=editor
        )
        return base_id


def upsert_items(base_id: int, items: List[Dict], mode: str = "skip") -> Dict[str, int]:
    """批量导入知识点。

    mode:
      - skip: 若唯一键冲突则跳过（文档默认）
      - update: 允许更新

    注意：字段映射:
      - unit_code -> unit (使用 "__ALL__" 代替 None)
      - type -> item_type
      - zh_hint -> zh_text (中文提示)
      - difficulty_tag -> difficulty_tag (保留原值: write/read)
    """
    from . import db as db_module

    inserted = 0
    skipped = 0
    updated = 0

    with db() as conn:
        # Get existing items to check for duplicates
        existing_items = db_module.get_base_items(conn, base_id)
        existing_map = {(item['unit'], item['en_text']): item for item in existing_items}

        for it in items:
            # Map old fields to new schema
            unit_code = it.get("unit_code")
            unit = unit_code if unit_code else "__ALL__"  # Use "__ALL__" instead of NULL
            item_type = it["type"].upper() if "type" in it else "WORD"
            en_text = it["en_text"].strip()
            zh_text = it.get("zh_hint", "")  # Map zh_hint -> zh_text
            difficulty_tag = it.get("difficulty_tag")  # Keep difficulty_tag as-is

            # Check if item already exists
            key = (unit, en_text)
            if key in existing_map:
                if mode == "update":
                    # Update existing item
                    existing_id = existing_map[key]['id']
                    db_module.update_item(conn, existing_id, zh_text=zh_text, item_type=item_type, difficulty_tag=difficulty_tag)
                    updated += 1
                else:
                    skipped += 1
            else:
                # Insert new item (position will be auto-calculated)
                try:
                    db_module.create_item(
                        conn,
                        base_id=base_id,
                        zh_text=zh_text,
                        en_text=en_text,
                        unit=unit,
                        position=None,  # Auto-calculate
                        item_type=item_type,
                        difficulty_tag=difficulty_tag
                    )
                    inserted += 1
                except Exception:
                    # Unique constraint or other error
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
    def shuffle_candidate_pool(rows: List[Dict], pool_size: int) -> List[Dict]:
        if not rows:
            return rows
        effective = min(len(rows), max(pool_size, min(len(rows), 5)))
        pool = rows[:effective]
        rest = rows[effective:]
        random.shuffle(pool)
        return pool + rest

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
                where_unit = f" AND ki.unit IN ({placeholders})"
                params.extend(unit_scope)

            # only write items are eligible
            q = f"""
            SELECT
              ki.*, sis.wrong_attempts, sis.consecutive_wrong, sis.last_attempt_at
            FROM items ki
            LEFT JOIN student_item_stats sis
              ON sis.item_id = ki.id AND sis.student_id = ?
            WHERE ki.base_id=?
              AND ki.item_type=?
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
            rows = shuffle_candidate_pool(rows, need * 3)

            # remove duplicates across types/session by en_text
            for r in rows:
                if len([x for x in selected if x["en_text"] == r["en_text"]]) > 0:
                    continue
                selected.append(r)
                if len([x for x in selected if x["item_type"] == typ]) >= need:
                    break

    # if still short, backfill from any type (except grammar by default)
    if len(selected) < total_count:
        with db() as conn:
            need = total_count - len(selected)
            params = [student_id, base_id]
            where_unit = ""
            if unit_scope:
                placeholders = ",".join(["?"] * len(unit_scope))
                where_unit = f" AND ki.unit IN ({placeholders})"
                params.extend(unit_scope)
            q = f"""
            SELECT ki.*, sis.wrong_attempts, sis.consecutive_wrong, sis.last_attempt_at
            FROM items ki
            LEFT JOIN student_item_stats sis
              ON sis.item_id = ki.id AND sis.student_id = ?
            WHERE ki.base_id=?
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
            rows = shuffle_candidate_pool(rows, need * 5)
            for r in rows:
                if any(x["en_text"] == r["en_text"] for x in selected):
                    continue
                selected.append(r)
                if len(selected) >= total_count:
                    break

    return selected[:total_count]


def _select_items_for_session_multi(
    student_id: int,
    base_units: Dict[int, Optional[List[str]]],
    mix_ratio: Dict[str, int],
    total_count: int,
    difficulty_filter: Optional[str] = None,
) -> List[Dict]:
    """Select items from multiple bases with different unit scopes.

    Args:
        student_id: Student ID
        base_units: {base_id: unit_scope}, where unit_scope can be None (all units) or ["U1", "U2"]
        mix_ratio: {"WORD": 15, "PHRASE": 8, "SENTENCE": 6}
        total_count: Total number of items to select
        difficulty_filter: Filter by difficulty tag ("write", "read", or None for all)

    Returns:
        List of selected items (dicts with id, type, en_text, zh_hint, etc.)
    """
    import logging
    logger = logging.getLogger("uvicorn.error")
    logger.info(f"[SELECT_ITEMS_MULTI] student_id={student_id}, base_units={base_units}, mix_ratio={mix_ratio}, total_count={total_count}")
    def shuffle_candidate_pool(rows: List[Dict], pool_size: int) -> List[Dict]:
        if not rows:
            return rows
        effective = min(len(rows), max(pool_size, min(len(rows), 5)))
        pool = rows[:effective]
        rest = rows[effective:]
        random.shuffle(pool)
        return pool + rest

    # Calculate per-type counts
    ratio_total = sum(mix_ratio.values()) or 1
    counts = {
        t: max(0, int(round(total_count * (mix_ratio.get(t, 0) / ratio_total))))
        for t in ("WORD", "PHRASE", "SENTENCE", "GRAMMAR")
    }
    # Adjust rounding so sum == total_count
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

            # Collect candidates from all bases
            all_candidates = []
            for base_id, unit_scope in base_units.items():
                params = [student_id, base_id, typ]
                where_unit = ""
                if unit_scope:
                    placeholders = ",".join(["?"] * len(unit_scope))
                    where_unit = f" AND ki.unit IN ({placeholders})"
                    params.extend(unit_scope)

                # Add difficulty filter
                where_difficulty = ""
                if difficulty_filter == "write":
                    where_difficulty = " AND ki.difficulty_tag = 'write'"
                elif difficulty_filter == "read":
                    where_difficulty = " AND ki.difficulty_tag IN ('read', 'recognize')"
                # else: no filter (all difficulties)

                q = f"""
                SELECT
                  ki.*, sis.wrong_attempts, sis.consecutive_wrong, sis.last_attempt_at
                FROM items ki
                LEFT JOIN student_item_stats sis
                  ON sis.item_id = ki.id AND sis.student_id = ?
                WHERE ki.base_id=?
                  AND ki.item_type=?
                  {where_unit}
                  {where_difficulty}
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
                all_candidates.extend(rows)

            # Sort all candidates by priority and select
            all_candidates.sort(
                key=lambda r: (
                    -(r.get("consecutive_wrong") or 0),
                    -(r.get("wrong_attempts") or 0),
                    0 if r.get("last_attempt_at") is None else 1,
                    r.get("last_attempt_at") or "0000",
                    -r.get("id", 0),
                )
            )
            all_candidates = shuffle_candidate_pool(all_candidates, need * 3)

            # Remove duplicates across types/session by en_text
            for r in all_candidates:
                if len([x for x in selected if x["en_text"] == r["en_text"]]) > 0:
                    continue
                selected.append(r)
                if len([x for x in selected if x["item_type"] == typ]) >= need:
                    break

    # If still short, backfill from any type (except grammar by default)
    if len(selected) < total_count:
        with db() as conn:
            need = total_count - len(selected)
            all_candidates = []
            for base_id, unit_scope in base_units.items():
                params = [student_id, base_id]
                where_unit = ""
                if unit_scope:
                    placeholders = ",".join(["?"] * len(unit_scope))
                    where_unit = f" AND ki.unit IN ({placeholders})"
                    params.extend(unit_scope)

                # Add difficulty filter
                where_difficulty = ""
                if difficulty_filter == "write":
                    where_difficulty = " AND ki.difficulty_tag = 'write'"
                elif difficulty_filter == "read":
                    where_difficulty = " AND ki.difficulty_tag IN ('read', 'recognize')"
                # else: no filter (all difficulties)

                q = f"""
                SELECT ki.*, sis.wrong_attempts, sis.consecutive_wrong, sis.last_attempt_at
                FROM items ki
                LEFT JOIN student_item_stats sis
                  ON sis.item_id = ki.id AND sis.student_id = ?
                WHERE ki.base_id=?
                  {where_unit}
                  {where_difficulty}
                ORDER BY
                  COALESCE(sis.consecutive_wrong, 0) DESC,
                  COALESCE(sis.wrong_attempts, 0) DESC,
                  CASE WHEN sis.last_attempt_at IS NULL THEN 0 ELSE 1 END ASC,
                  COALESCE(sis.last_attempt_at, '0000') ASC,
                  ki.id DESC
                LIMIT ?
                """
                rows = [dict(r) for r in conn.execute(q, params + [need * 5]).fetchall()]
                all_candidates.extend(rows)

            # Sort and select
            all_candidates.sort(
                key=lambda r: (
                    -(r.get("consecutive_wrong") or 0),
                    -(r.get("wrong_attempts") or 0),
                    0 if r.get("last_attempt_at") is None else 1,
                    r.get("last_attempt_at") or "0000",
                    -r.get("id", 0),
                )
            )
            all_candidates = shuffle_candidate_pool(all_candidates, need * 5)

            for r in all_candidates:
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
                # For list elements, only split by comma/semicolon, NOT by spaces
                # This preserves "Unit 1" as a single unit name
                parts.extend(re.split(r"[，,;；]+", s))
            else:
                parts.append(str(x))
    else:
        parts = [str(unit_scope)]

    out: List[str] = []
    for p in parts:
        p = (p or "").strip()
        if not p:
            continue

        # Preserve "Unit X" format if already in this format (most common in database)
        if re.match(r"^Unit\s+\d+$", p, re.IGNORECASE):
            # Normalize to "Unit X" with single space and title case
            match = re.match(r"^Unit\s+(\d+)$", p, re.IGNORECASE)
            if match:
                out.append(f"Unit {match.group(1)}")
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
    total_count: int,
    mix_ratio: Dict[str, int],
    account_id: int,
    title: str = "四年级英语默写单",
    base_id: Optional[int] = None,
    unit_scope: Optional[List[str]] = None,
    base_units: Optional[Dict[int, List[str]]] = None,
    difficulty_filter: Optional[str] = None,
) -> Dict:
    """Generate practice session.

    Supports two modes:
    1. Legacy single-base mode: base_id + optional unit_scope
    2. Multi-base mode: base_units = {base_id: [units]}

    Args:
        difficulty_filter: Filter items by difficulty tag ("write", "read", or None for all)
    """
    ensure_media_dir()

    # Normalize inputs
    if base_units:
        # New multi-base mode
        if not base_units:
            raise ValueError("base_units cannot be empty")
        # Normalize each base's unit_scope
        normalized_base_units = {
            int(bid): normalize_unit_scope(units)
            for bid, units in base_units.items()
        }
    elif base_id:
        # Legacy single-base mode
        unit_scope = normalize_unit_scope(unit_scope)
        normalized_base_units = {base_id: unit_scope}
    else:
        raise ValueError("Must provide either base_id or base_units")

    with db() as conn:
        student = conn.execute(
            "SELECT id FROM students WHERE id=? AND account_id=?",
            (student_id, account_id),
        ).fetchone()
        if not student:
            raise ValueError(f"student_id {student_id} 不存在，请先完成初始化/创建学生。")

        # Validate all base_ids exist
        for bid in normalized_base_units.keys():
            base = conn.execute(
                "SELECT id FROM bases WHERE id=? AND (is_system=1 OR account_id=?)",
                (bid, account_id),
            ).fetchone()
            if not base:
                raise ValueError(f"base_id {bid} 不存在，请先导入或创建知识库。")

    items = _select_items_for_session_multi(
        student_id=student_id,
        base_units=normalized_base_units,
        mix_ratio=mix_ratio,
        total_count=total_count,
        difficulty_filter=difficulty_filter,
    )

    if not items:
        raise ValueError("所选出题范围内没有可用知识点（请检查 Unit 代码、或先导入知识库）。")

    # For params_json, store the normalized base_units
    params_json = json.dumps(
        {
            "base_units": {str(k): v for k, v in normalized_base_units.items()},
            "total_count": total_count,
            "mix_ratio": mix_ratio,
            "title": title,
            "difficulty_filter": difficulty_filter,
        },
        ensure_ascii=False,
    )

    # Use the first base_id for the session record (backward compatibility)
    primary_base_id = list(normalized_base_units.keys())[0]

    with db() as conn:
        cur = conn.execute(
            """
            INSERT INTO practice_sessions(student_id, base_id, status, params_json, created_at)
            VALUES(?,?,?,?,?)
            """,
            (student_id, primary_base_id, "DRAFT", params_json, utcnow_iso()),
        )
        session_id = int(cur.lastrowid)

        # store exercise items (keep global position order)
        rows_all: List[ExerciseRow] = []
        for idx, it in enumerate(items, start=1):
            en_text = it.get("en_text") or ""
            normalized = normalize_answer(en_text)  # Compute normalized answer
            conn.execute(
                """
                INSERT INTO exercise_items(session_id, item_id, position, type, en_text, zh_hint, normalized_answer)
                VALUES(?,?,?,?,?,?,?)
                """,
                (
                    session_id,
                    it.get("id"),
                    idx,
                    it.get("item_type"),
                    en_text,
                    it.get("zh_text"),  # 使用zh_text而不是zh_hint
                    normalized,
                ),
            )
            rows_all.append(
                ExerciseRow(
                    position=idx,
                    zh_hint=it.get("zh_text") or "",  # 使用zh_text而不是zh_hint
                    answer_en=it.get("en_text") or "",
                    item_type=it.get("item_type") or "",
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

        # Generate filename: Practice_日期_编号.pdf (English for cross-platform compatibility)
        from datetime import datetime
        date_str = datetime.now().strftime("%Y-%m-%d")
        practice_uuid = f"ES-{session_id:04d}-{str(uuid.uuid4())[:6].upper()}"

        pdf_filename = f"Practice_{date_str}_{practice_uuid}.pdf"
        ans_filename = f"Practice_{date_str}_{practice_uuid}_Key.pdf"

        pdf_path = os.path.join(MEDIA_DIR, pdf_filename)
        ans_path = os.path.join(MEDIA_DIR, ans_filename)

        render_dictation_pdf(
            pdf_path,
            title,
            sections,
            show_answers=False,
            session_id=session_id,
            footer=f"Session #{session_id}",
            practice_uuid=practice_uuid,
        )
        render_dictation_pdf(
            ans_path,
            title + "（答案）",
            sections,
            show_answers=True,
            session_id=session_id,
            footer=f"Session #{session_id}",
            practice_uuid=practice_uuid,
        )

        conn.execute(
            "UPDATE practice_sessions SET pdf_path=?, answer_pdf_path=?, practice_uuid=?, created_date=? WHERE id=?",
            (pdf_path, ans_path, practice_uuid, date_str, session_id),
        )

    # Return session info with items preview
    # Safely build items preview from the items list
    items_preview = []
    try:
        for idx, it in enumerate(items, start=1):
            items_preview.append({
                "position": idx,
                "type": it.get("item_type", ""),
                "zh_hint": it.get("zh_text", ""),  # Use zh_text from database
                "en_text": it.get("en_text", ""),
            })
    except Exception as e:
        # If preview generation fails, return empty list
        items_preview = []

    return {
        "session_id": session_id,
        "pdf_path": pdf_path,
        "answer_pdf_path": ans_path,
        "pdf_url": f"/media/{pdf_filename}",
        "answer_pdf_url": f"/media/{ans_filename}",
        "practice_uuid": practice_uuid,
        "items": items_preview,
    }


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
            INSERT INTO submissions(session_id, item_id, position, submitted_at, image_path, text_raw, source)
            VALUES(?,?,?,?,?,?,?)
            """,
            (session_id, None, None, submitted_at, image_path, text_raw, source),
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


def search_practice_sessions(
    account_id: int,
    student_id: Optional[int],
    base_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    practice_uuid: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Tuple[List[Dict], int]:
    base_sql = """
        FROM practice_sessions ps
        JOIN students s ON ps.student_id = s.id
        LEFT JOIN bases b ON ps.base_id = b.id
        WHERE s.account_id = ?
    """
    params: List[Any] = [account_id]
    filters: List[str] = []

    if student_id is not None:
        filters.append("ps.student_id = ?")
        params.append(student_id)

    if base_id is not None:
        filters.append("ps.base_id = ?")
        params.append(base_id)

    if start_date:
        filters.append("COALESCE(ps.created_date, substr(ps.created_at, 1, 10)) >= ?")
        params.append(start_date)
    if end_date:
        filters.append("COALESCE(ps.created_date, substr(ps.created_at, 1, 10)) <= ?")
        params.append(end_date)
    if practice_uuid:
        filters.append("ps.practice_uuid LIKE ?")
        params.append(f"%{practice_uuid}%")
    if keyword:
        filters.append(
            """
            EXISTS (
                SELECT 1 FROM exercise_items ei
                WHERE ei.session_id = ps.id
                  AND (ei.en_text LIKE ? OR ei.zh_hint LIKE ?)
            )
            """.strip()
        )
        params.append(f"%{keyword}%")
        params.append(f"%{keyword}%")

    if filters:
        base_sql += " AND " + " AND ".join(filters)

    count_sql = "SELECT COUNT(1) " + base_sql
    sql = """
        SELECT
            ps.id,
            ps.status,
            ps.created_at,
            ps.corrected_at,
            ps.practice_uuid,
            ps.created_date,
            ps.pdf_path,
            ps.answer_pdf_path,
            ps.base_id,
            ps.params_json,
            b.name AS base_name,
            (SELECT COUNT(1) FROM exercise_items ei WHERE ei.session_id = ps.id) AS item_count,
            (SELECT COUNT(1)
             FROM practice_results pr
             WHERE pr.submission_id = (
                SELECT s2.id
                FROM submissions s2
                WHERE s2.session_id = ps.id
                ORDER BY s2.submitted_at DESC, s2.id DESC
                LIMIT 1
             )) AS result_count,
            (SELECT SUM(CASE WHEN pr.is_correct = 1 THEN 1 ELSE 0 END)
             FROM practice_results pr
             WHERE pr.submission_id = (
                SELECT s2.id
                FROM submissions s2
                WHERE s2.session_id = ps.id
                ORDER BY s2.submitted_at DESC, s2.id DESC
                LIMIT 1
             )) AS correct_count,
            (SELECT GROUP_CONCAT(DISTINCT it.difficulty_tag)
             FROM exercise_items ei
             LEFT JOIN items it ON ei.item_id = it.id
             WHERE ei.session_id = ps.id) AS difficulty_tags
    """ + base_sql + """
        ORDER BY COALESCE(ps.created_date, substr(ps.created_at, 1, 10)) DESC, ps.id DESC
        LIMIT ? OFFSET ?
    """
    params_with_limit = params + [int(limit), int(offset)]

    with db() as conn:
        total_count = conn.execute(count_sql, params).fetchone()[0]
        rows = conn.execute(sql, params_with_limit).fetchall()

    base_units_map: Dict[int, Dict[str, List[str]]] = {}
    params_by_id: Dict[int, Dict[str, Any]] = {}
    base_ids: set[int] = set()
    for r in rows:
        params_raw = r["params_json"] if "params_json" in r.keys() else None
        if not params_raw:
            if r["base_id"] is not None:
                base_ids.add(int(r["base_id"]))
            continue
        try:
            params = json.loads(params_raw)
        except Exception:
            params = {}
        params_by_id[int(r["id"])] = params
        base_units = params.get("base_units")
        if isinstance(base_units, dict) and base_units:
            base_units_map[int(r["id"])] = base_units
            for bid in base_units.keys():
                try:
                    base_ids.add(int(bid))
                except Exception:
                    continue
        elif r["base_id"] is not None:
            base_ids.add(int(r["base_id"]))

    base_name_map: Dict[int, str] = {}
    if base_ids:
        placeholders = ",".join("?" for _ in base_ids)
        with db() as conn:
            base_rows = conn.execute(
                f"SELECT id, name FROM bases WHERE id IN ({placeholders})",
                list(base_ids),
            ).fetchall()
        base_name_map = {int(b["id"]): b["name"] for b in base_rows}

    sessions = []
    for r in rows:
        row = dict(r)
        row_id = int(row.get("id") or 0)
        params = params_by_id.get(row_id, {})
        source = params.get("source")
        matched_session_id = params.get("matched_session_id")
        is_ai_extract = source == "AI_EXTRACT"
        extracted_date = params.get("extracted_date") or row.get("created_date")

        difficulty_filter = None
        if params:
            difficulty_filter = params.get("difficulty_filter")
        if is_ai_extract and not matched_session_id:
            difficulty_filter = "unknown"
        if not difficulty_filter:
            tags = row.get("difficulty_tags") or ""
            tag_set = {t for t in tags.split(",") if t}
            if tag_set == {"write"}:
                difficulty_filter = "write"
            elif tag_set == {"read"}:
                difficulty_filter = "read"
            else:
                difficulty_filter = "all"
        row["difficulty_filter"] = difficulty_filter
        if is_ai_extract and not matched_session_id:
            row["base_display"] = "未知"
        else:
            base_units = base_units_map.get(row_id)
            if base_units:
                parts = []
                for bid_raw, units_raw in base_units.items():
                    try:
                        bid = int(bid_raw)
                    except Exception:
                        continue
                    base_name = base_name_map.get(bid) or "未知"
                    unit_list: List[str] = []
                    if isinstance(units_raw, list):
                        unit_list = [str(u) for u in units_raw if u]
                    elif isinstance(units_raw, str) and units_raw:
                        unit_list = [units_raw]
                    if unit_list:
                        parts.append(f"{base_name}({','.join(unit_list)})")
                    else:
                        parts.append(base_name)
                row["base_display"] = "；".join(parts) if parts else (row.get("base_name") or "未知")
            else:
                base_name = row.get("base_name") or "未知"
                row["base_display"] = base_name
        if is_ai_extract:
            row["created_date_display"] = extracted_date or "未知"
            row["created_time_display"] = extracted_date or "未知"
        else:
            created_at = row.get("created_at") or ""
            row["created_date_display"] = row.get("created_date") or (created_at[:10] if created_at else "-")
            row["created_time_display"] = row.get("created_at")
        row.pop("difficulty_tags", None)
        row.pop("params_json", None)
        pdf_path = row.get("pdf_path")
        ans_path = row.get("answer_pdf_path")
        row["pdf_url"] = f"/media/{os.path.basename(pdf_path)}" if pdf_path else None
        row["answer_pdf_url"] = f"/media/{os.path.basename(ans_path)}" if ans_path else None
        sessions.append(row)
    return sessions, int(total_count)


def get_practice_session_detail(session_id: int) -> Dict:
    with db() as conn:
        session = conn.execute(
            """
            SELECT
                ps.id,
                ps.student_id,
                ps.base_id,
                ps.status,
                ps.created_at,
                ps.corrected_at,
                ps.practice_uuid,
                ps.created_date,
                ps.pdf_path,
                ps.answer_pdf_path,
                ps.params_json,
                b.name AS base_name
            FROM practice_sessions ps
            LEFT JOIN bases b ON ps.base_id = b.id
            WHERE ps.id = ?
            """,
            (session_id,),
        ).fetchone()
        if not session:
            raise ValueError("session not found")
        session_dict = dict(session)

        params: Dict[str, Any] = {}
        params_raw = session_dict.get("params_json")
        if params_raw:
            try:
                params = json.loads(params_raw)
            except Exception:
                params = {}
        source = params.get("source")
        matched_session_id = params.get("matched_session_id")
        is_ai_extract = source == "AI_EXTRACT"
        extracted_date = params.get("extracted_date") or session_dict.get("created_date")

        items = conn.execute(
            """
            SELECT id, position, type, en_text, zh_hint
            FROM exercise_items
            WHERE session_id = ?
            ORDER BY position ASC
            """,
            (session_id,),
        ).fetchall()
        items_list = [dict(it) for it in items]

        difficulty_filter = params.get("difficulty_filter")
        if is_ai_extract and not matched_session_id:
            difficulty_filter = "unknown"
        if not difficulty_filter:
            tags = conn.execute(
                """
                SELECT GROUP_CONCAT(DISTINCT it.difficulty_tag) AS tags
                FROM exercise_items ei
                LEFT JOIN items it ON ei.item_id = it.id
                WHERE ei.session_id = ?
                """,
                (session_id,),
            ).fetchone()
            tag_str = tags["tags"] if tags else ""
            tag_set = {t for t in (tag_str or "").split(",") if t}
            if tag_set == {"write"}:
                difficulty_filter = "write"
            elif tag_set == {"read"}:
                difficulty_filter = "read"
            else:
                difficulty_filter = "all"
        session_dict["difficulty_filter"] = difficulty_filter

        base_display = session_dict.get("base_name") or "未知"
        if is_ai_extract and not matched_session_id:
            base_display = "未知"
        else:
            base_units = params.get("base_units")
            if isinstance(base_units, dict) and base_units:
                base_ids = []
                for bid_raw in base_units.keys():
                    try:
                        base_ids.append(int(bid_raw))
                    except Exception:
                        continue
                base_name_map: Dict[int, str] = {}
                if base_ids:
                    placeholders = ",".join("?" for _ in base_ids)
                    base_rows = conn.execute(
                        f"SELECT id, name FROM bases WHERE id IN ({placeholders})",
                        base_ids,
                    ).fetchall()
                    base_name_map = {int(b["id"]): b["name"] for b in base_rows}
                parts = []
                for bid_raw, units_raw in base_units.items():
                    try:
                        bid = int(bid_raw)
                    except Exception:
                        continue
                    base_name = base_name_map.get(bid) or "未知"
                    unit_list: List[str] = []
                    if isinstance(units_raw, list):
                        unit_list = [str(u) for u in units_raw if u]
                    elif isinstance(units_raw, str) and units_raw:
                        unit_list = [units_raw]
                    if unit_list:
                        parts.append(f"{base_name}({','.join(unit_list)})")
                    else:
                        parts.append(base_name)
                if parts:
                    base_display = "；".join(parts)
        session_dict["base_display"] = base_display
        if is_ai_extract:
            session_dict["created_date_display"] = extracted_date or "未知"
            session_dict["created_time_display"] = extracted_date or "未知"
        else:
            created_at = session_dict.get("created_at") or ""
            session_dict["created_date_display"] = session_dict.get("created_date") or (created_at[:10] if created_at else "-")
            session_dict["created_time_display"] = session_dict.get("created_at")

        results = conn.execute(
            """
            SELECT submission_id, exercise_item_id, answer_raw, is_correct, error_type, created_at
            FROM practice_results
            WHERE session_id = ?
            ORDER BY submission_id DESC, exercise_item_id ASC, created_at DESC
            """,
            (session_id,),
        ).fetchall()
        latest_results: Dict[int, Dict[str, Any]] = {}
        results_by_submission: Dict[int, Dict[int, Dict[str, Any]]] = {}
        for r in results:
            row = dict(r)
            sub_id = int(row["submission_id"])
            ex_id = int(row["exercise_item_id"])
            if ex_id not in latest_results:
                latest_results[ex_id] = row
            sub_map = results_by_submission.setdefault(sub_id, {})
            if ex_id not in sub_map:
                sub_map[ex_id] = row

        submissions_rows = conn.execute(
            """
            SELECT id, text_raw, image_path, submitted_at, source
            FROM submissions
            WHERE session_id = ?
            ORDER BY submitted_at DESC, id DESC
            """,
            (session_id,),
        ).fetchall()
        submissions_history = [dict(s) for s in submissions_rows]
        submission_dict = submissions_history[0] if submissions_history else None

    pdf_path = session_dict.get("pdf_path")
    ans_path = session_dict.get("answer_pdf_path")
    session_dict["pdf_url"] = f"/media/{os.path.basename(pdf_path)}" if pdf_path else None
    session_dict["answer_pdf_url"] = f"/media/{os.path.basename(ans_path)}" if ans_path else None

    raw_items: List[Dict[str, Any]] = []
    bundle_id = None
    bundle_meta = None
    submissions_payloads: List[Dict[str, Any]] = []
    for sub in submissions_history:
        sub_copy = dict(sub)
        image_path = sub_copy.get("image_path")
        sub_copy["image_url"] = f"/media/{os.path.basename(image_path)}" if image_path else None
        sub_copy["raw_items"] = []
        sub_copy["bundle_id"] = None
        sub_copy["bundle_meta"] = None
        if sub_copy.get("text_raw"):
            try:
                raw_payload = json.loads(sub_copy["text_raw"])
                sub_copy["raw_items"] = raw_payload.get("items") or []
                sub_copy["bundle_id"] = raw_payload.get("bundle_id")
                sub_copy["bundle_meta"] = raw_payload.get("bundle_meta") or None
            except Exception:
                pass
        if sub_copy.get("bundle_id") and not sub_copy.get("bundle_meta"):
            sub_copy["bundle_meta"] = _load_ai_bundle_meta(sub_copy["bundle_id"])
        sub_results = results_by_submission.get(int(sub_copy["id"]), {})
        sub_copy["results_by_item"] = sub_results
        sub_total = sum(1 for _ in sub_results.values())
        sub_correct = sum(1 for v in sub_results.values() if v.get("is_correct"))
        sub_copy["summary"] = {"total": sub_total, "correct": sub_correct}
        submissions_payloads.append(sub_copy)

    if submission_dict and submission_dict.get("text_raw"):
        try:
            raw_payload = json.loads(submission_dict["text_raw"])
            raw_items = raw_payload.get("items") or []
            bundle_id = raw_payload.get("bundle_id")
            bundle_meta = raw_payload.get("bundle_meta") or None
        except Exception:
            raw_items = []
            bundle_id = None
            bundle_meta = None
    if bundle_id and not bundle_meta:
        bundle_meta = _load_ai_bundle_meta(bundle_id)

    latest_submission_results = {}
    if submissions_payloads:
        latest_submission_results = submissions_payloads[0].get("results_by_item") or {}
    total_results = sum(1 for _ in latest_submission_results.values()) if latest_submission_results else sum(1 for _ in latest_results.values())
    correct_results = (
        sum(1 for v in latest_submission_results.values() if v.get("is_correct"))
        if latest_submission_results
        else sum(1 for v in latest_results.values() if v.get("is_correct"))
    )

    return {
        "session": session_dict,
        "items": items_list,
        "results_by_item": latest_submission_results or latest_results,
        "summary": {"total": total_results, "correct": correct_results},
        "submission": submission_dict,
        "raw_items": raw_items,
        "bundle_id": bundle_id,
        "bundle_meta": bundle_meta,
        "submissions_history": submissions_payloads,
    }


def regenerate_practice_pdfs(session_id: int) -> Dict:
    ensure_media_dir()
    with db() as conn:
        row = conn.execute(
            """
            SELECT id, practice_uuid, created_date, created_at, params_json
            FROM practice_sessions
            WHERE id = ?
            """,
            (session_id,),
        ).fetchone()
        if not row:
            raise ValueError("session not found")
        session = dict(row)
        items = conn.execute(
            """
            SELECT position, type, en_text, zh_hint
            FROM exercise_items
            WHERE session_id = ?
            ORDER BY position ASC
            """,
            (session_id,),
        ).fetchall()
        if not items:
            raise ValueError("no items for session")

        title = "英语练习单"
        params_json = session.get("params_json") or ""
        try:
            params = json.loads(params_json) if params_json else {}
            if isinstance(params, dict) and params.get("title"):
                title = str(params.get("title"))
        except Exception:
            pass

        from datetime import datetime
        practice_uuid = session.get("practice_uuid") or f"ES-{session_id:04d}-{str(uuid.uuid4())[:6].upper()}"
        date_str = session.get("created_date")
        if not date_str:
            created_at = session.get("created_at") or ""
            date_str = created_at[:10] if created_at else datetime.now().strftime("%Y-%m-%d")

        sections: Dict[str, List[ExerciseRow]] = {"WORD": [], "PHRASE": [], "SENTENCE": []}
        for it in items:
            item = dict(it)
            typ = item.get("type") or item.get("item_type") or "WORD"
            row_obj = ExerciseRow(
                position=int(item.get("position") or 0),
                zh_hint=item.get("zh_hint") or "",
                answer_en=item.get("en_text") or "",
                item_type=typ,
            )
            if typ in sections:
                sections[typ].append(row_obj)

        pdf_filename = f"Practice_{date_str}_{practice_uuid}.pdf"
        ans_filename = f"Practice_{date_str}_{practice_uuid}_Key.pdf"
        pdf_path = os.path.join(MEDIA_DIR, pdf_filename)
        ans_path = os.path.join(MEDIA_DIR, ans_filename)

        render_dictation_pdf(
            pdf_path,
            title,
            sections,
            show_answers=False,
            session_id=session_id,
            footer=f"Session #{session_id}",
            practice_uuid=practice_uuid,
        )
        render_dictation_pdf(
            ans_path,
            title + "（答案）",
            sections,
            show_answers=True,
            session_id=session_id,
            footer=f"Session #{session_id}",
            practice_uuid=practice_uuid,
        )

        conn.execute(
            "UPDATE practice_sessions SET pdf_path=?, answer_pdf_path=?, practice_uuid=?, created_date=? WHERE id=?",
            (pdf_path, ans_path, practice_uuid, date_str, session_id),
        )

    return {
        "session_id": session_id,
        "practice_uuid": practice_uuid,
        "pdf_path": pdf_path,
        "answer_pdf_path": ans_path,
        "pdf_url": f"/media/{pdf_filename}",
        "answer_pdf_url": f"/media/{ans_filename}",
    }


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
            INSERT INTO submissions(session_id, item_id, position, submitted_at, image_path, text_raw, source)
            VALUES(?,?,?,?,?,?,?)
            """,
            (session_id, None, None, utcnow_iso(), out_path, None, "PHOTO"),
        )
        submission_id = int(cur.lastrowid)

    return {"submission_id": submission_id, "image_path": out_path, "note": "MVP 未自动OCR，请在页面中手工录入答案后批改。"}

def upload_marked_submission_image(
    session_id: int,
    uploads: List[UploadFile],
    account_id: int,
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

    return analyze_ai_photos(account_id, student_id, base_id, uploads)



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


_TZ_UTC8 = timezone(timedelta(hours=8))


def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _to_utc8_date(value: Optional[str]) -> Optional[datetime.date]:
    dt = _parse_iso_datetime(value)
    if not dt:
        return None
    return dt.astimezone(_TZ_UTC8).date()


def _format_utc8_date(value: Optional[str]) -> Optional[str]:
    d = _to_utc8_date(value)
    return d.isoformat() if d else None


def _normalize_base_label(custom_name: Optional[str], base_name: Optional[str], base_id: int) -> str:
    custom = (custom_name or "").strip()
    base = (base_name or "").strip()
    return custom or base or f"资料库#{base_id}"


def _get_active_learning_bases(conn, student_id: int) -> List[Dict]:
    rows = conn.execute(
        """
        SELECT
          slb.base_id,
          slb.custom_name,
          slb.current_unit,
          slb.display_order,
          b.name AS base_name
        FROM student_learning_bases slb
        JOIN bases b ON b.id = slb.base_id
        WHERE slb.student_id = ? AND slb.is_active = 1
        ORDER BY slb.display_order, slb.id
        """,
        (student_id,),
    ).fetchall()

    bases = []
    for row in rows:
        data = dict(row)
        base_id = int(data.get("base_id") or 0)
        data["label"] = _normalize_base_label(data.get("custom_name"), data.get("base_name"), base_id)
        bases.append(data)
    return bases


def _get_week_bits(conn, student_id: int, base_ids: List[int]) -> Tuple[str, int, int]:
    """
    获取本周练习位图和统计

    Returns:
        Tuple[str, int, int]: (week_bits, week_practice_days, week_practice_count)
        - week_bits: 7位字符串，表示本周每天是否练习
        - week_practice_days: 本周练习天数
        - week_practice_count: 本周练习次数
    """
    if not base_ids:
        return "0000000", 0, 0
    placeholders = ",".join(["?"] * len(base_ids))
    cutoff = datetime.now(timezone.utc) - timedelta(days=14)
    rows = conn.execute(
        f"""
        SELECT created_at
        FROM practice_sessions
        WHERE student_id = ?
          AND base_id IN ({placeholders})
          AND created_at >= ?
        """,
        [student_id, *base_ids, cutoff.isoformat()],
    ).fetchall()

    practice_dates = set()
    today = datetime.now(_TZ_UTC8).date()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    week_practice_count = 0

    for row in rows:
        d = _to_utc8_date(row["created_at"])
        if d:
            practice_dates.add(d)
            # 统计本周练习次数
            if week_start <= d <= week_end:
                week_practice_count += 1

    week_days = [week_start + timedelta(days=i) for i in range(7)]
    bits = "".join("1" if d in practice_dates else "0" for d in week_days)
    week_practice_days = sum(1 for d in week_days if d in practice_dates)

    return bits, week_practice_days, week_practice_count


def _get_library_stats(
    conn,
    student_id: int,
    base_ids: List[int],
    days: int,
    mastery_threshold: int,
) -> Dict[str, Any]:
    stats = {
        "total_items": 0,
        "learned_items": 0,
        "mastered_items": 0,
        "coverage_rate": 0,
        "mastery_rate_in_learned": None,
        "practice_days_30d": 0,
        "wrong_items_30d": 0,
        "week_bits": "0000000",
        "week_practice_days": 0,
        "week_practice_count": 0,
        "last_practice_at": None,
    }
    if not base_ids:
        return stats

    placeholders = ",".join(["?"] * len(base_ids))
    total_row = conn.execute(
        f"SELECT COUNT(1) AS c FROM items WHERE base_id IN ({placeholders})",
        base_ids,
    ).fetchone()
    learned_row = conn.execute(
        f"""
        SELECT COUNT(1) AS c
        FROM student_item_stats sis
        JOIN items i ON i.id = sis.item_id
        WHERE sis.student_id = ?
          AND i.base_id IN ({placeholders})
          AND sis.total_attempts > 0
        """,
        [student_id, *base_ids],
    ).fetchone()
    mastered_row = conn.execute(
        f"""
        SELECT COUNT(1) AS c
        FROM student_item_stats sis
        JOIN items i ON i.id = sis.item_id
        WHERE sis.student_id = ?
          AND i.base_id IN ({placeholders})
          AND sis.consecutive_correct >= ?
        """,
        [student_id, *base_ids, mastery_threshold],
    ).fetchone()

    total = int(total_row["c"]) if total_row else 0
    learned = int(learned_row["c"]) if learned_row else 0
    mastered = int(mastered_row["c"]) if mastered_row else 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_iso = cutoff.isoformat()

    wrong_row = conn.execute(
        f"""
        SELECT COUNT(DISTINCT ei.item_id) AS c
        FROM practice_results pr
        JOIN practice_sessions ps ON ps.id = pr.session_id
        JOIN exercise_items ei ON ei.id = pr.exercise_item_id
        WHERE ps.student_id = ?
          AND ps.base_id IN ({placeholders})
          AND pr.is_correct = 0
          AND pr.created_at >= ?
          AND ei.item_id IS NOT NULL
        """,
        [student_id, *base_ids, cutoff_iso],
    ).fetchone()

    session_rows = conn.execute(
        f"""
        SELECT created_at
        FROM practice_sessions
        WHERE student_id = ?
          AND base_id IN ({placeholders})
          AND created_at >= ?
        """,
        [student_id, *base_ids, cutoff_iso],
    ).fetchall()

    practice_dates = set()
    for row in session_rows:
        d = _to_utc8_date(row["created_at"])
        if d:
            practice_dates.add(d)

    last_row = conn.execute(
        f"""
        SELECT MAX(created_at) AS t
        FROM practice_sessions
        WHERE student_id = ? AND base_id IN ({placeholders})
        """,
        [student_id, *base_ids],
    ).fetchone()

    week_bits, week_days, week_count = _get_week_bits(conn, student_id, base_ids)

    stats.update(
        {
            "total_items": total,
            "learned_items": learned,
            "mastered_items": mastered,
            "coverage_rate": (learned / total) if total else 0,
            "mastery_rate_in_learned": (mastered / learned) if learned else None,
            "practice_days_30d": len(practice_dates),
            "wrong_items_30d": int(wrong_row["c"]) if wrong_row else 0,
            "week_bits": week_bits,
            "week_practice_days": week_days,
            "week_practice_count": week_count,
            "last_practice_at": _format_utc8_date(last_row["t"] if last_row else None),
        }
    )
    return stats


def get_dashboard(student_id: int, base_id: int, days: int = 30) -> Dict:
    """家长看板（基础版）：已学/已掌握/易错/最近练习/日历"""
    with db() as conn:
        learned = conn.execute(
            """
            SELECT COUNT(1) AS c
            FROM student_item_stats sis
            JOIN items ki ON ki.id = sis.item_id
            WHERE sis.student_id=? AND ki.base_id=?
            """,
            (student_id, base_id),
        ).fetchone()

        mastered = conn.execute(
            """
            SELECT COUNT(1) AS c
            FROM student_item_stats sis
            JOIN items ki ON ki.id = sis.item_id
            WHERE sis.student_id=? AND ki.base_id=? AND sis.consecutive_correct >= ?
            """,
            (student_id, base_id, get_mastery_threshold()),
        ).fetchone()

        wrong_top = conn.execute(
            """
            SELECT ki.item_type, ki.en_text, ki.zh_text, sis.wrong_attempts, sis.last_attempt_at
            FROM student_item_stats sis
            JOIN items ki ON ki.id = sis.item_id
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


def _media_url(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    return f"/media/{os.path.basename(path)}"


def get_dashboard_overview(account_id: int, days: int = 30) -> Dict[str, Any]:
    mastery_threshold = get_mastery_threshold()
    global_weekly_target = get_weekly_target_days()
    with db() as conn:
        students = conn.execute(
            "SELECT id, name, grade, avatar, weekly_target_days FROM students WHERE account_id = ? ORDER BY id LIMIT 10",
            (account_id,),
        ).fetchall()

        students_out = []
        for row in students:
            student = dict(row)
            student_id = int(student["id"])
            active_bases = _get_active_learning_bases(conn, student_id)
            base_ids = [int(b["base_id"]) for b in active_bases]
            stats = _get_library_stats(conn, student_id, base_ids, days, mastery_threshold)

            # 获取学生的个性化目标，如果未设置则使用全局默认值
            student_weekly_target = get_weekly_target_days(student_id)

            students_out.append(
                {
                    "student_id": student_id,
                    "student_name": student.get("name") or "",
                    "grade": student.get("grade") or "",
                    "avatar": student.get("avatar") or "",
                    "active_bases_count": len(base_ids),
                    "total_items": stats["total_items"],
                    "learned_items": stats["learned_items"],
                    "mastered_items": stats["mastered_items"],
                    "coverage_rate": stats["coverage_rate"],
                    "mastery_rate_in_learned": stats["mastery_rate_in_learned"],
                    "week_bits": stats["week_bits"],
                    "week_practice_days": stats["week_practice_days"],
                    "week_practice_count": stats["week_practice_count"],
                    "weekly_target_days": student_weekly_target,
                    "wrong_items_30d": stats["wrong_items_30d"],
                    "last_practice_at": stats["last_practice_at"],
                }
            )

    return {
        "days": days,
        "weekly_target_days": global_weekly_target,
        "mastery_threshold": mastery_threshold,
        "students": students_out,
    }


def get_dashboard_student(student_id: int, account_id: int, days: int = 30, max_bases: int = 6) -> Dict[str, Any]:
    mastery_threshold = get_mastery_threshold()
    weekly_target_days = get_weekly_target_days(student_id)
    with db() as conn:
        student_row = conn.execute(
            "SELECT id, name, grade, avatar FROM students WHERE id = ? AND account_id = ?",
            (student_id, account_id),
        ).fetchone()
        if not student_row:
            raise ValueError("student not found")

        student = dict(student_row)
        active_bases = _get_active_learning_bases(conn, student_id)
        base_ids = [int(b["base_id"]) for b in active_bases]
        base_label_map = {int(b["base_id"]): b["label"] for b in active_bases}

        library_stats = _get_library_stats(conn, student_id, base_ids, days, mastery_threshold)
        library_stats["active_bases_count"] = len(base_ids)

        bases_stats = {}
        if base_ids:
            placeholders = ",".join(["?"] * len(base_ids))
            rows = conn.execute(
                f"""
                SELECT
                  i.base_id AS base_id,
                  COUNT(i.id) AS total,
                  COUNT(CASE WHEN sis.total_attempts > 0 THEN 1 END) AS learned,
                  COUNT(CASE WHEN sis.consecutive_correct >= ? THEN 1 END) AS mastered
                FROM items i
                LEFT JOIN student_item_stats sis
                  ON sis.item_id = i.id AND sis.student_id = ?
                WHERE i.base_id IN ({placeholders})
                GROUP BY i.base_id
                """,
                [mastery_threshold, student_id, *base_ids],
            ).fetchall()
            bases_stats = {int(r["base_id"]): dict(r) for r in rows}

        bases_rows = []
        for base in active_bases:
            if len(bases_rows) >= max_bases:
                break
            base_id = int(base["base_id"])
            stat = bases_stats.get(base_id, {})
            total = int(stat.get("total") or 0)
            learned = int(stat.get("learned") or 0)
            mastered = int(stat.get("mastered") or 0)
            bases_rows.append(
                {
                    "base_id": base_id,
                    "label": base.get("label") or f"资料库#{base_id}",
                    "current_unit": base.get("current_unit"),
                    "total": total,
                    "learned": learned,
                    "mastered": mastered,
                    "coverage_rate": (learned / total) if total else 0,
                    "mastery_rate_in_learned": (mastered / learned) if learned else None,
                }
            )

        recent_sessions = []
        if base_ids:
            placeholders = ",".join(["?"] * len(base_ids))
            rows = conn.execute(
                f"""
                SELECT
                  ps.id,
                  ps.status,
                  ps.created_at,
                  ps.corrected_at,
                  ps.base_id,
                  ps.pdf_path,
                  ps.answer_pdf_path,
                  (SELECT COUNT(1) FROM exercise_items ei WHERE ei.session_id = ps.id) AS item_count,
                  (SELECT COUNT(1) FROM submissions s WHERE s.session_id = ps.id) AS submission_count
                FROM practice_sessions ps
                WHERE ps.student_id = ? AND ps.base_id IN ({placeholders})
                ORDER BY ps.id DESC
                LIMIT 10
                """,
                [student_id, *base_ids],
            ).fetchall()

            for row in rows:
                data = dict(row)
                base_id = int(data.get("base_id") or 0)
                data["base_label"] = base_label_map.get(base_id, f"资料库#{base_id}")
                data["pdf_url"] = _media_url(data.get("pdf_path"))
                data["answer_pdf_url"] = _media_url(data.get("answer_pdf_path"))
                recent_sessions.append(data)

        top_wrong = []
        if base_ids:
            placeholders = ",".join(["?"] * len(base_ids))
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            rows = conn.execute(
                f"""
                SELECT
                  i.en_text,
                  i.item_type,
                  i.base_id,
                  COUNT(1) AS wrong_count,
                  MAX(pr.created_at) AS last_wrong_at
                FROM practice_results pr
                JOIN practice_sessions ps ON ps.id = pr.session_id
                JOIN exercise_items ei ON ei.id = pr.exercise_item_id
                JOIN items i ON i.id = ei.item_id
                WHERE ps.student_id = ?
                  AND ps.base_id IN ({placeholders})
                  AND pr.is_correct = 0
                  AND pr.created_at >= ?
                GROUP BY i.id
                ORDER BY wrong_count DESC, last_wrong_at DESC
                LIMIT 10
                """,
                [student_id, *base_ids, cutoff.isoformat()],
            ).fetchall()
            for row in rows:
                data = dict(row)
                base_id = int(data.get("base_id") or 0)
                data["base_label"] = base_label_map.get(base_id, f"资料库#{base_id}")
                top_wrong.append(data)

    return {
        "student": {
            "id": int(student.get("id")),
            "name": student.get("name") or "",
            "grade": student.get("grade") or "",
            "avatar": student.get("avatar") or "",
        },
        "days": days,
        "weekly_target_days": weekly_target_days,
        "mastery_threshold": mastery_threshold,
        "library": library_stats,
        "bases": {
            "truncated": len(base_ids) > max_bases,
            "max_bases": max_bases,
            "rows": bases_rows,
        },
        "recent_sessions": recent_sessions,
        "top_wrong_30d": top_wrong,
    }


def cleanup_old_sessions(
    undownloaded_days: int = 14
) -> Dict[str, int]:
    """清理旧的练习单和PDF文件

    清理策略：
    1. 删除未下载且创建超过undownloaded_days天的会话（包括关联数据）
    2. 删除已下载且创建超过undownloaded_days天的PDF文件（保留数据库记录）

    Args:
        undownloaded_days: 会话与PDF保留天数（默认14天）

    Returns:
        清理统计：{"deleted_sessions": N, "deleted_pdfs": M}
    """
    import logging
    from datetime import datetime, timedelta

    logger = logging.getLogger("uvicorn.error")
    deleted_sessions = 0
    deleted_pdfs = 0

    with db() as conn:
        # 1. 删除未下载且过期的会话
        cutoff_date = (datetime.now() - timedelta(days=undownloaded_days)).strftime("%Y-%m-%d")

        # 先获取要删除的会话列表（用于删除PDF文件）
        sessions_to_delete = conn.execute(
            """
            SELECT id, pdf_path, answer_pdf_path
            FROM practice_sessions
            WHERE downloaded_at IS NULL
              AND created_date < ?
            """,
            (cutoff_date,)
        ).fetchall()

        if sessions_to_delete:
            session_ids = [s["id"] for s in sessions_to_delete]
            logger.info(f"[CLEANUP] Deleting {len(session_ids)} undownloaded sessions older than {cutoff_date}")

            # 删除关联的PDF文件
            for session in sessions_to_delete:
                for path_key in ["pdf_path", "answer_pdf_path"]:
                    pdf_path = session.get(path_key)
                    if pdf_path and os.path.exists(pdf_path):
                        try:
                            os.remove(pdf_path)
                            deleted_pdfs += 1
                            logger.info(f"[CLEANUP] Deleted PDF: {pdf_path}")
                        except Exception as e:
                            logger.warning(f"[CLEANUP] Failed to delete PDF {pdf_path}: {e}")

            # 删除关联的 exercise_items（外键级联删除可能不存在）
            placeholders = ",".join(["?"] * len(session_ids))
            conn.execute(
                f"DELETE FROM exercise_items WHERE session_id IN ({placeholders})",
                session_ids
            )

            # 删除会话记录
            conn.execute(
                f"DELETE FROM practice_sessions WHERE id IN ({placeholders})",
                session_ids
            )

            deleted_sessions = len(session_ids)

        # 2. 删除已下载但超过保留期的PDF文件（保留数据库记录）
        old_downloaded_sessions = conn.execute(
            """
            SELECT id, pdf_path, answer_pdf_path
            FROM practice_sessions
            WHERE downloaded_at IS NOT NULL
              AND created_date < ?
              AND (pdf_path IS NOT NULL OR answer_pdf_path IS NOT NULL)
            """,
            (cutoff_date,)
        ).fetchall()

        if old_downloaded_sessions:
            logger.info(f"[CLEANUP] Deleting PDFs for {len(old_downloaded_sessions)} sessions older than {cutoff_date}")

            for session in old_downloaded_sessions:
                session_id = session["id"]
                pdf_deleted = False

                # 删除PDF文件
                for path_key in ["pdf_path", "answer_pdf_path"]:
                    pdf_path = session.get(path_key)
                    if pdf_path and os.path.exists(pdf_path):
                        try:
                            os.remove(pdf_path)
                            deleted_pdfs += 1
                            pdf_deleted = True
                            logger.info(f"[CLEANUP] Deleted old PDF: {pdf_path}")
                        except Exception as e:
                            logger.warning(f"[CLEANUP] Failed to delete old PDF {pdf_path}: {e}")

                # 清除数据库中的PDF路径（数据仍保留，可重新生成）
                if pdf_deleted:
                    conn.execute(
                        "UPDATE practice_sessions SET pdf_path = NULL, answer_pdf_path = NULL WHERE id = ?",
                        (session_id,)
                    )

    logger.info(f"[CLEANUP] Cleanup complete: deleted {deleted_sessions} sessions, {deleted_pdfs} PDFs")

    return {
        "deleted_sessions": deleted_sessions,
        "deleted_pdfs": deleted_pdfs,
        "undownloaded_cutoff_date": cutoff_date,
        "pdf_cutoff_date": cutoff_date,
    }


def _safe_remove_file(path: Optional[str]) -> bool:
    if not path:
        return False
    try:
        abs_path = os.path.abspath(path)
        media_root = os.path.abspath(MEDIA_DIR)
        if os.path.commonpath([abs_path, media_root]) != media_root:
            return False
        if os.path.exists(abs_path):
            os.remove(abs_path)
            return True
    except Exception:
        return False
    return False


def _path_from_media_url(url: Optional[str]) -> Optional[str]:
    if not url or not isinstance(url, str):
        return None
    if url.startswith("/media/"):
        rel = url[len("/media/"):]
        return os.path.join(MEDIA_DIR, rel)
    return None


def delete_practice_session(session_id: int) -> Dict[str, Any]:
    """Delete a practice session and related files."""
    import shutil

    with db() as conn:
        session_row = conn.execute(
            "SELECT id, pdf_path, answer_pdf_path FROM practice_sessions WHERE id=?",
            (session_id,),
        ).fetchone()
        if not session_row:
            raise ValueError("session not found")
        session = dict(session_row)

        submissions_rows = conn.execute(
            "SELECT id, image_path, text_raw FROM submissions WHERE session_id=?",
            (session_id,),
        ).fetchall()
        submissions = [dict(r) for r in submissions_rows]

        conn.execute("DELETE FROM practice_sessions WHERE id=?", (session_id,))

    removed_files: List[str] = []
    removed_bundles: List[str] = []

    for key in ("pdf_path", "answer_pdf_path"):
        if _safe_remove_file(session.get(key)):
            removed_files.append(session.get(key))

    for sub in submissions:
        if _safe_remove_file(sub.get("image_path")):
            removed_files.append(sub.get("image_path"))
        raw = sub.get("text_raw")
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            continue
        bundle_id = payload.get("bundle_id")
        if bundle_id:
            bundle_dir = os.path.join(MEDIA_DIR, "uploads", "ai_bundles", str(bundle_id))
            try:
                abs_dir = os.path.abspath(bundle_dir)
                media_root = os.path.abspath(MEDIA_DIR)
                if os.path.commonpath([abs_dir, media_root]) == media_root and os.path.exists(abs_dir):
                    shutil.rmtree(abs_dir, ignore_errors=True)
                    removed_bundles.append(str(bundle_id))
            except Exception:
                pass
        bundle_meta = payload.get("bundle_meta") if isinstance(payload.get("bundle_meta"), dict) else {}
        for url in (bundle_meta.get("image_urls") or []) + (bundle_meta.get("graded_image_urls") or []):
            path = _path_from_media_url(url)
            if path and _safe_remove_file(path):
                removed_files.append(path)
        items = payload.get("items")
        if isinstance(items, list):
            for it in items:
                if not isinstance(it, dict):
                    continue
                crop_url = it.get("crop_url")
                path = _path_from_media_url(crop_url)
                if path and _safe_remove_file(path):
                    removed_files.append(path)

    return {
        "deleted": True,
        "session_id": session_id,
        "removed_files": removed_files,
        "removed_bundles": removed_bundles,
    }
