import os
import base64
import json
import re
from typing import Any, Dict, List, Optional

# OpenAI official Python SDK (pip install openai)
from openai import OpenAI


def is_configured() -> bool:
    '''Return True if OpenAI credentials are available.'''
    return bool(os.environ.get("OPENAI_API_KEY"))


def _client() -> OpenAI:
    '''
    Create OpenAI client.
    - Reads OPENAI_API_KEY from env (recommended).
    - Optional: EL_OPENAI_BASE_URL to override; otherwise you can also use OPENAI_BASE_URL env var.
    '''
    base_url = os.environ.get("EL_OPENAI_BASE_URL")
    if base_url:
        return OpenAI(api_key=os.environ.get("OPENAI_API_KEY"), base_url=base_url)
    return OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


def _safe_json_loads(s: str) -> Any:
    s = (s or "").strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    m = re.search(r"(\{.*\}|\[.*\])", s, flags=re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    raise ValueError("Model output is not valid JSON")


def analyze_marked_sheet(image_bytes: bytes, expected_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    '''
    Use OpenAI vision to read a parent's MARKED photo and infer per-question correctness.

    Inputs:
      - image_bytes: the marked photo bytes
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
    model = os.environ.get("EL_OPENAI_VISION_MODEL") or "gpt-4o-mini"

    b64 = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:image/jpeg;base64,{b64}"

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

    client = _client()
    resp = client.responses.create(
        model=model,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": data_url},
                ],
            }
        ],
        max_output_tokens=900,
        temperature=0,
    )

    out_text = getattr(resp, "output_text", "") or ""
    data = _safe_json_loads(out_text)

    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
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
