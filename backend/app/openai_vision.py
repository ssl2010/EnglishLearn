import os
import base64
import json
import re
import logging
from typing import Any, Dict, List, Optional

# OpenAI official Python SDK (pip install openai)
from openai import OpenAI

logger = logging.getLogger("uvicorn.error")


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, str(default)))
    except Exception:
        return default


def is_configured() -> bool:
    """Return True if OpenAI/ARK credentials are available."""
    return bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("ARK_API_KEY"))


def _log_env() -> None:
    """Log non-sensitive env info for debugging."""
    logger.info(
        "openai_vision env: key_present=%s base_url=%s model=%s",
        bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("ARK_API_KEY")),
        os.environ.get("EL_OPENAI_BASE_URL")
        or os.environ.get("ARK_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or "",
        os.environ.get("EL_OPENAI_VISION_MODEL") or "gpt-4o-mini",
    )


def _client() -> OpenAI:
    """
    Create OpenAI client.
    - Reads OPENAI_API_KEY or ARK_API_KEY from env.
    - Optional: EL_OPENAI_BASE_URL / ARK_BASE_URL override.
    """
    timeout_seconds = float(os.environ.get("EL_AI_HTTP_TIMEOUT_SECONDS") or os.environ.get("EL_AI_TIMEOUT_SECONDS") or 0)
    client_kwargs: Dict[str, Any] = {}
    if timeout_seconds:
        client_kwargs["timeout"] = timeout_seconds
    base_url = (
        os.environ.get("EL_OPENAI_BASE_URL")
        or os.environ.get("ARK_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
    )
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("ARK_API_KEY")
    if not base_url and os.environ.get("ARK_API_KEY"):
        base_url = "https://ark.cn-beijing.volces.com/api/v3"
    if base_url:
        return OpenAI(api_key=api_key, base_url=base_url, **client_kwargs)
    return OpenAI(api_key=api_key, **client_kwargs)


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
        logger.exception("openai_vision failed to load ai_config.json from %s", path)
    return {}


def _safe_json_loads(s: str) -> Any:
    s = (s or "").strip()
    # Remove common non-JSON control chars that some proxies/models may emit.
    s = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", s)
    if s.startswith("```"):
        s = s.strip("`").strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    try:
        dec = json.JSONDecoder()
        obj, _ = dec.raw_decode(s)
        return obj
    except Exception:
        pass
    # Last-chance: trim to the outermost JSON object/array.
    start = min([i for i in [s.find("{"), s.find("[")] if i != -1] or [-1])
    end = max([s.rfind("}"), s.rfind("]")])
    if start >= 0 and end > start:
        try:
            return json.loads(s[start : end + 1])
        except Exception:
            pass
    m = re.search(r"(\{.*\}|\[.*\])", s, flags=re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    raise ValueError("Model output is not valid JSON")


def analyze_marked_sheet(image_bytes_list: List[bytes], expected_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    '''
    Use OpenAI vision to read a parent's MARKED photo and infer per-question correctness.

    Inputs:
      - image_bytes_list: the marked photo bytes (one or more pages)
      - expected_items: list of {position:int, zh_hint:str, expected_en:str}

    Output (dict):
      {
        "items": [
          {
            "q": 1,
            "parent_mark": "correct"|"incorrect"|"unknown",
            "confidence": 0.0~1.0,
            "student_text": "...",   # if readable, else ""
            "note": "..."
          }, ...
        ],
        "notes": "optional"
      }
    '''
    _log_env()
    model = os.environ.get("EL_OPENAI_VISION_MODEL") or "gpt-4o-mini"

    data_urls: List[str] = []
    for image_bytes in image_bytes_list:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        data_urls.append(f"data:image/jpeg;base64,{b64}")

    expected_brief = [
        {
            "q": int(it.get("position")),
            "zh": (it.get("zh_hint") or "")[:50],
            "expected": (it.get("expected_en") or "")[:80],
        }
        for it in expected_items
    ]

    prompt = (
        "You are helping grade an English dictation worksheet photo that has been marked by a parent. "
        "Your job is NOT to fully OCR every character. Instead, focus on reading the parent's marks next to each question:\n"
        "- check mark / tick / circle meaning correct\n"
        "- cross / X meaning incorrect\n"
        "- no clear mark: unknown\n\n"
        "The sheet contains multiple questions numbered. You are given an expected list of questions (q) with short hints.\n"
        "Return STRICT JSON with keys: items (array) and optional notes.\n"
        "For each expected q, output:\n"
        "{q:int, parent_mark:'correct'|'incorrect'|'unknown', confidence:0..1, student_text:'', note:''}\n"
        "If you can read the student's written answer for that q, put it in student_text; otherwise empty.\n"
        "If you are unsure, set parent_mark=unknown and lower confidence.\n\n"
        f"Expected questions list:\n{json.dumps(expected_brief, ensure_ascii=False)}"
    )

    base_url = (
        os.environ.get("EL_OPENAI_BASE_URL")
        or os.environ.get("ARK_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or ""
    )
    ark_mode = "ark.cn-beijing.volces.com" in base_url or bool(os.environ.get("ARK_API_KEY"))

    client = _client()

    def _do_request(max_tokens: int, strict_json: bool, use_response_format: bool = True) -> Any:
        text_prompt = prompt
        if strict_json:
            text_prompt = prompt + "\n\n仅允许输出 JSON，对象形式如 {\"items\":[...] }，不要输出 Markdown 或其他文字。"
        logger.info("openai_vision prompt(marked) chars=%d preview=%s", len(text_prompt), text_prompt[:400])
        content = [{"type": "text", "text": text_prompt}]
        for url in data_urls:
            content.append({"type": "image_url", "image_url": {"url": url}})
        req_kwargs: Dict[str, Any] = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": content,
                }
            ],
            "max_tokens": max_tokens,
            "temperature": 0,
        }
        if use_response_format:
            req_kwargs["response_format"] = {"type": "json_object"}
        if ark_mode:
            req_kwargs["reasoning_effort"] = os.environ.get("EL_ARK_REASONING_EFFORT") or "medium"
        logger.info("openai_vision calling API with max_tokens=%s...", max_tokens)
        result = client.chat.completions.create(**req_kwargs)
        logger.info("openai_vision API call completed")
        return result

    max_tokens = _env_int("EL_AI_MAX_TOKENS", 2000)
    max_tokens_retry = _env_int("EL_AI_MAX_TOKENS_RETRY", 4000)
    try:
        resp = _do_request(max_tokens, strict_json=False, use_response_format=True)
    except Exception as e:
        # Some proxies don't support response_format; retry without it.
        msg = str(e).lower()
        if "response_format" in msg or "unsupported" in msg:
            logger.warning("openai_vision response_format unsupported; retrying without it")
            resp = _do_request(max_tokens, strict_json=False, use_response_format=False)
        else:
            logger.exception("openai_vision request failed")
            raise

    out_text = ""
    try:
        choice0 = resp.choices[0]
        msg = getattr(choice0, "message", None)
        if isinstance(msg, dict):
            out_text = str(msg.get("content") or "").strip()
        else:
            out_text = str(getattr(msg, "content", "") or "").strip()
        if not out_text:
            out_text = str(getattr(choice0, "text", "") or "").strip()
    except Exception:
        out_text = ""

    finish_reason = ""
    try:
        finish_reason = str(resp.choices[0].finish_reason or "")
    except Exception:
        finish_reason = ""

    try:
        usage = getattr(resp, "usage", None)
        if usage:
            prompt_tokens = getattr(usage, "prompt_tokens", None)
            completion_tokens = getattr(usage, "completion_tokens", None)
            total_tokens = getattr(usage, "total_tokens", None)
            logger.info(
                "openai_vision tokens: prompt=%s completion=%s total=%s",
                prompt_tokens,
                completion_tokens,
                total_tokens,
            )
    except Exception:
        pass

    if finish_reason == "length":
        logger.warning("openai_vision completion truncated; retrying with higher max_tokens")
        try:
            resp = _do_request(max_tokens_retry, strict_json=True, use_response_format=True)
        except Exception:
            logger.exception("openai_vision retry failed after truncation")
        else:
            try:
                choice0 = resp.choices[0]
                msg = getattr(choice0, "message", None)
                if isinstance(msg, dict):
                    out_text = str(msg.get("content") or "").strip()
                else:
                    out_text = str(getattr(msg, "content", "") or "").strip()
                if not out_text:
                    out_text = str(getattr(choice0, "text", "") or "").strip()
            except Exception:
                out_text = out_text or ""

    if not out_text:
        try:
            dump = resp.model_dump()
            logger.error("openai_vision empty content; response=%s", json.dumps(dump, ensure_ascii=False)[:1000])
        except Exception:
            logger.error("openai_vision empty content; response=%r", resp)
    try:
        data = _safe_json_loads(out_text)
    except Exception:
        logger.exception("openai_vision JSON parse failed; raw=%s", out_text[:500])
        raise

    items = None
    if isinstance(data, dict):
        items = data.get("items")
        if items is None:
            for key in ("questions", "results", "answers", "data"):
                val = data.get(key)
                if isinstance(val, list):
                    items = val
                    break
                if isinstance(val, dict) and isinstance(val.get("items"), list):
                    items = val.get("items")
                    break
        if items is None and isinstance(data.get("result"), dict):
            items = data["result"].get("items")
    elif isinstance(data, list):
        items = data
    if not isinstance(items, list):
        try:
            logger.error(
                "openai_vision JSON missing items; keys=%s raw=%s",
                list(data.keys()) if isinstance(data, dict) else type(data),
                out_text[:800],
            )
        except Exception:
            logger.error("openai_vision JSON missing items; keys=%s", list(data.keys()) if isinstance(data, dict) else type(data))
        raise ValueError("OpenAI output JSON missing 'items' array")

    norm_items: List[Dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        q = int(it.get("q"))
        pm = str(it.get("parent_mark") or "unknown").lower()
        if pm not in ("correct", "incorrect", "unknown"):
            pm = "unknown"
        conf = float(it.get("confidence") or 0.0)
        conf = max(0.0, min(1.0, conf))
        norm_items.append(
            {
                "q": q,
                "parent_mark": pm,
                "confidence": conf,
                "student_text": (it.get("student_text") or "")[:200],
                "note": (it.get("note") or "")[:200],
            }
        )

    return {"items": norm_items, "notes": (data.get("notes") if isinstance(data, dict) else "")}


def analyze_freeform_sheet(image_bytes_list: List[bytes], return_raw: bool = False) -> Dict[str, Any]:
    """
    Use vision model to extract questions and student answers with bboxes.
    Output JSON:
      {
        "items": [
          {
            "q": 1,
            "zh_hint": "...",
            "student_text": "...",
            "confidence": 0.0~1.0,
            "page_index": 1,
            "handwriting_bbox": [x1,y1,x2,y2],
            "line_bbox": [x1,y1,x2,y2],
            "note": "..."
          }
        ]
      }
    """
    _log_env()
    model = os.environ.get("EL_OPENAI_VISION_MODEL") or "gpt-4o-mini"

    data_urls: List[str] = []
    for image_bytes in image_bytes_list:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        data_urls.append(f"data:image/jpeg;base64,{b64}")

    cfg = _load_ai_config()
    prompt_data = (cfg.get("llm", {}) or {}).get("freeform_prompt") or cfg.get("freeform_sheet") or ""
    if isinstance(prompt_data, list):
        prompt = "\n".join(prompt_data)
    else:
        prompt = str(prompt_data)
    if not prompt.strip():
        raise ValueError("AI 提示词为空，请检查 ai_config.json 的 llm.freeform_prompt")

    base_url = (
        os.environ.get("EL_OPENAI_BASE_URL")
        or os.environ.get("ARK_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or ""
    )
    ark_mode = "ark.cn-beijing.volces.com" in base_url or bool(os.environ.get("ARK_API_KEY"))

    client = _client()

    def _do_request(max_tokens: int, strict_json: bool, use_response_format: bool = True, extra_note: str = "", retry_count: int = 0) -> Any:
        text_prompt = prompt
        if strict_json:
            text_prompt = prompt + "\n\n仅允许输出 JSON，不要输出 Markdown、说明文字或任何多余内容。"
        if extra_note:
            text_prompt = text_prompt + "\n\n" + extra_note
        logger.info("openai_vision prompt(freeform) chars=%d preview=%s", len(text_prompt), text_prompt[:400])
        content = [{"type": "text", "text": text_prompt}]
        for url in data_urls:
            content.append({"type": "image_url", "image_url": {"url": url}})
        req_kwargs: Dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": max_tokens,
            "temperature": 0,
        }
        if use_response_format:
            req_kwargs["response_format"] = {"type": "json_object"}
        if ark_mode:
            req_kwargs["reasoning_effort"] = os.environ.get("EL_ARK_REASONING_EFFORT") or "medium"

        logger.info("openai_vision calling API with max_tokens=%s, images=%d, retry=%d...",
                   max_tokens, len(data_urls), retry_count)

        # Retry logic for connection errors
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                result = client.chat.completions.create(**req_kwargs)
                logger.info("openai_vision API call completed successfully")
                return result
            except Exception as e:
                error_msg = str(e)
                is_connection_error = "Connection error" in error_msg or "ConnectionError" in str(type(e).__name__)
                is_timeout_error = "timeout" in error_msg.lower() or "Timeout" in str(type(e).__name__)

                if (is_connection_error or is_timeout_error) and attempt < max_retries:
                    wait_time = (attempt + 1) * 2  # 2s, 4s
                    logger.warning(f"openai_vision API call failed (attempt {attempt+1}/{max_retries+1}): {error_msg}. Retrying in {wait_time}s...")
                    import time
                    time.sleep(wait_time)
                    continue
                else:
                    # Last attempt or non-retryable error
                    logger.error(f"openai_vision API call failed after {attempt+1} attempts: {type(e).__name__}: {error_msg}")
                    raise

    max_tokens = _env_int("EL_AI_MAX_TOKENS", 2000)
    max_tokens_retry = _env_int("EL_AI_MAX_TOKENS_RETRY", 4000)
    try:
        # Always request strict JSON on the first attempt.
        resp = _do_request(max_tokens, strict_json=True, use_response_format=True)
    except Exception as e:
        msg = str(e).lower()
        if "response_format" in msg or "unsupported" in msg:
            logger.warning("openai_vision response_format unsupported; retrying without it")
            resp = _do_request(max_tokens, strict_json=True, use_response_format=False)
        else:
            logger.exception("openai_vision request failed")
            raise

    out_text = ""
    try:
        choice0 = resp.choices[0]
        msg = getattr(choice0, "message", None)
        if isinstance(msg, dict):
            out_text = str(msg.get("content") or "").strip()
        else:
            out_text = str(getattr(msg, "content", "") or "").strip()
        if not out_text:
            out_text = str(getattr(choice0, "text", "") or "").strip()
    except Exception:
        out_text = ""

    finish_reason = ""
    try:
        finish_reason = str(resp.choices[0].finish_reason or "")
    except Exception:
        finish_reason = ""

    if finish_reason == "length":
        logger.warning("openai_vision completion truncated; retrying with higher max_tokens")
        try:
            resp = _do_request(max_tokens_retry, strict_json=True, use_response_format=True)
        except Exception:
            logger.exception("openai_vision retry failed after truncation")
        else:
            try:
                choice0 = resp.choices[0]
                msg = getattr(choice0, "message", None)
                if isinstance(msg, dict):
                    out_text = str(msg.get("content") or "").strip()
                else:
                    out_text = str(getattr(msg, "content", "") or "").strip()
                if not out_text:
                    out_text = str(getattr(choice0, "text", "") or "").strip()
            except Exception:
                out_text = out_text or ""

    if not out_text:
        try:
            dump = resp.model_dump()
            logger.error("openai_vision empty content; response=%s", json.dumps(dump, ensure_ascii=False)[:1000])
        except Exception:
            logger.error("openai_vision empty content; response=%r", resp)

    try:
        data = _safe_json_loads(out_text)
    except Exception:
        logger.exception("openai_vision JSON parse failed; raw=%s", out_text[:500])
        # Retry once with a stricter prompt and higher token budget.
        try:
            resp = _do_request(max_tokens_retry, strict_json=True, use_response_format=False)
            choice0 = resp.choices[0]
            msg = getattr(choice0, "message", None)
            if isinstance(msg, dict):
                out_text = str(msg.get("content") or "").strip()
            else:
                out_text = str(getattr(msg, "content", "") or "").strip()
            if not out_text:
                out_text = str(getattr(choice0, "text", "") or "").strip()
            data = _safe_json_loads(out_text)
        except Exception:
            raise

    items = None
    if isinstance(data, dict):
        # Try new sections format first
        sections = data.get("sections")
        if isinstance(sections, list):
            # Flatten sections into items (preserve section order)
            items = []
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
                    # Note: bbox comes from OCR matching, not from LLM
                    items.append({
                        "q": it.get("q"),
                        "section_title": sec_title if idx == 0 else "",  # Only first item has title
                        "section_type": sec_type,
                        "zh_hint": it.get("hint") or "",
                        "student_text": it.get("ans") or "",
                        "is_correct": it.get("ok"),
                        "confidence": it.get("conf"),
                        "page_index": it.get("pg") or 1,
                        "note": it.get("note") or "",
                    })
        # Fallback to old items format
        if items is None:
            items = data.get("items")
        if items is None:
            for key in ("questions", "results", "answers", "data"):
                val = data.get(key)
                if isinstance(val, list):
                    items = val
                    break
                if isinstance(val, dict) and isinstance(val.get("items"), list):
                    items = val.get("items")
                    break
        if items is None and isinstance(data.get("result"), dict):
            items = data["result"].get("items")
    elif isinstance(data, list):
        items = data
    if not isinstance(items, list):
        try:
            logger.error(
                "openai_vision JSON missing items; keys=%s raw=%s",
                list(data.keys()) if isinstance(data, dict) else type(data),
                out_text[:800],
            )
        except Exception:
            logger.error("openai_vision JSON missing items; raw=%s", out_text[:800])
        # Retry once with a stronger schema reminder if model returned alt keys.
        if isinstance(data, dict) and any(k in data for k in ("words", "phrases", "sentences")):
            try:
                extra_note = (
                    "必须返回 items 数组，每个元素包含 q、zh_hint、student_text、confidence、page_index、"
                    "handwriting_bbox、line_bbox。不要返回 words/phrases/sentences 等替代结构。"
                )
                resp = _do_request(max_tokens_retry, strict_json=True, use_response_format=False, extra_note=extra_note)
                choice0 = resp.choices[0]
                msg = getattr(choice0, "message", None)
                if isinstance(msg, dict):
                    out_text = str(msg.get("content") or "").strip()
                else:
                    out_text = str(getattr(msg, "content", "") or "").strip()
                if not out_text:
                    out_text = str(getattr(choice0, "text", "") or "").strip()
                data = _safe_json_loads(out_text)
                items = data.get("items") if isinstance(data, dict) else None
            except Exception:
                pass
        # Last resort: adapt known alternative structures into items.
        if not isinstance(items, list) and isinstance(data, dict):
            alt: List[Dict[str, Any]] = []
            for key in ("words", "phrases", "sentences"):
                val = data.get(key)
                if isinstance(val, list):
                    alt.extend(val)
            if alt:
                logger.warning("openai_vision adapting words/phrases/sentences to items without bboxes")
                items = []
                for idx, entry in enumerate(alt, start=1):
                    if not isinstance(entry, dict):
                        continue
                    items.append(
                        {
                            "q": idx,
                            "zh_hint": entry.get("chinese") or entry.get("中文") or "",
                            "student_text": entry.get("english") or entry.get("英文") or "",
                            "is_correct": entry.get("is_correct") if "is_correct" in entry else None,
                            "confidence": entry.get("confidence") if "confidence" in entry else None,
                            "page_index": int(entry.get("page_index") or 1),
                            "handwriting_bbox": entry.get("handwriting_bbox"),
                            "line_bbox": entry.get("line_bbox"),
                            "note": "fallback_from_alt_keys",
                        }
                    )
            # Handle sectioned Chinese keys like "单词默写"/"短语默写"/"句子默写"
            if not items:
                for section, val in data.items():
                    if not isinstance(val, list):
                        continue
                    for entry in val:
                        if not isinstance(entry, dict):
                            continue
                        items = items or []
                        items.append(
                            {
                                "q": int(entry.get("序号") or len(items) + 1),
                                "zh_hint": entry.get("中文") or entry.get("chinese") or "",
                                "student_text": entry.get("英文") or entry.get("english") or "",
                                "is_correct": entry.get("is_correct") if "is_correct" in entry else None,
                                "confidence": entry.get("confidence") if "confidence" in entry else None,
                                "page_index": int(entry.get("page_index") or 1),
                                "handwriting_bbox": entry.get("handwriting_bbox"),
                                "line_bbox": entry.get("line_bbox"),
                                "note": f"fallback_from_section:{section}",
                            }
                        )
        if not isinstance(items, list):
            raise ValueError("OpenAI output JSON missing 'items' array")

    norm_items: List[Dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        try:
            qv = int(it.get("q"))
        except Exception:
            qv = len(norm_items) + 1

        hb = it.get("handwriting_bbox")
        if not (isinstance(hb, list) and len(hb) == 4):
            hb = None
        lb = it.get("line_bbox")
        if not (isinstance(lb, list) and len(lb) == 4):
            lb = None
        conf_val = it.get("confidence")
        norm_items.append(
            {
                "q": qv,
                "zh_hint": (it.get("zh_hint") or "")[:120],
                "student_text": (it.get("student_text") or "")[:200],
                "is_correct": bool(it.get("is_correct")) if "is_correct" in it else None,
                "confidence": float(conf_val) if conf_val is not None else None,
                "page_index": int(it.get("page_index") or 1),
                "handwriting_bbox": hb,
                "line_bbox": lb,
                "note": (it.get("note") or "")[:200],
            }
        )

    if return_raw:
        # Parse raw_text to get the original LLM JSON object
        raw_json = None
        try:
            raw_json = _safe_json_loads(out_text)
        except Exception:
            raw_json = {}
        return {"items": norm_items, "raw_llm": raw_json}
    return {"items": norm_items}


def annotate_graded_sheet(
    image_bytes: bytes,
    grading_items: List[Dict[str, Any]],
    output_path: str
) -> str:
    """
    Draw grading marks on the original image.

    Args:
        image_bytes: Original image bytes
        grading_items: List of graded items with {q, is_correct, note, ...}
        output_path: Path to save the annotated image

    Returns:
        Path to the annotated image
    """
    from PIL import Image, ImageDraw, ImageFont
    import io

    # Load image
    img = Image.open(io.BytesIO(image_bytes))
    draw = ImageDraw.Draw(img)

    # Try to load a font, fallback to default if not available
    try:
        # Use larger fonts for better visibility
        font_huge = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 60)
        font_medium = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 30)
    except Exception:
        try:
            font_huge = ImageFont.load_default()
            font_medium = ImageFont.load_default()
        except Exception:
            font_huge = None
            font_medium = None

    img_height = img.height
    img_width = img.width
    num_items = len(grading_items)

    # Calculate spacing
    if num_items > 0:
        vertical_spacing = img_height / (num_items + 2)
    else:
        vertical_spacing = 50

    # Draw marks for each question
    for idx, item in enumerate(grading_items):
        is_correct = item.get("is_correct", False)
        note = item.get("note", "")
        q_num = item.get("q", idx + 1)

        # Position on the right side
        mark_x = img_width - 100
        mark_y = int((idx + 1.5) * vertical_spacing)

        # Draw circle background
        circle_radius = 35
        circle_color = (7, 168, 108) if is_correct else (229, 72, 77)  # Green or Red

        # Draw filled circle
        draw.ellipse(
            [mark_x - circle_radius, mark_y - circle_radius,
             mark_x + circle_radius, mark_y + circle_radius],
            fill=circle_color,
            outline=circle_color
        )

        # Draw mark symbol
        if is_correct:
            # Draw white checkmark ✓
            if font_huge:
                # Calculate text bbox to center it
                bbox = draw.textbbox((0, 0), "✓", font=font_huge)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
                text_x = mark_x - text_width // 2
                text_y = mark_y - text_height // 2 - 5
                draw.text((text_x, text_y), "✓", fill="white", font=font_huge)
        else:
            # Draw white X
            if font_huge:
                bbox = draw.textbbox((0, 0), "✗", font=font_huge)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
                text_x = mark_x - text_width // 2
                text_y = mark_y - text_height // 2 - 5
                draw.text((text_x, text_y), "✗", fill="white", font=font_huge)

        # Draw question number next to the mark
        if font_medium:
            num_x = mark_x - circle_radius - 10
            bbox = draw.textbbox((0, 0), str(q_num), font=font_medium)
            text_width = bbox[2] - bbox[0]
            num_x = num_x - text_width
            draw.text((num_x, mark_y - 15), str(q_num), fill=(100, 100, 100), font=font_medium)

        # Draw note if error (but not "未作答")
        if not is_correct and note and note != "未作答" and font_medium:
            # Draw note on a semi-transparent background
            note_text = note[:15]  # Limit length
            note_x = mark_x - circle_radius - 200
            note_y = mark_y + circle_radius + 5

            # Draw red text
            draw.text((note_x, note_y), note_text, fill=(229, 72, 77), font=font_medium)

    # Save annotated image
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    img.save(output_path, quality=95)

    return output_path
