import base64
import json
import os
import time
from typing import Any, Dict, List

import requests


def _get_access_token(api_key: str, secret_key: str, timeout: int) -> str:
    url = "https://aip.baidubce.com/oauth/2.0/token"
    params = {
        "grant_type": "client_credentials",
        "client_id": api_key,
        "client_secret": secret_key,
    }
    resp = requests.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    return data.get("access_token") or ""


def _ocr_edu_test(image_bytes: bytes, access_token: str, timeout: int, endpoint: str, extra_params: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{endpoint}?access_token={access_token}"
    img_b64 = base64.b64encode(image_bytes).decode("ascii")
    payload = {"image": img_b64}
    if extra_params:
        payload.update(extra_params)
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    resp = requests.post(url, data=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and data.get("error_code"):
        raise ValueError(f"Baidu OCR error {data.get('error_code')}: {data.get('error_msg')}")
    return data


def recognize_edu_test(images: List[bytes], timeout: int, endpoint: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    api_key = os.environ.get("BAIDU_OCR_API_KEY") or ""
    secret_key = os.environ.get("BAIDU_OCR_SECRET_KEY") or ""
    if not api_key or not secret_key:
        raise ValueError("BAIDU_OCR_API_KEY/BAIDU_OCR_SECRET_KEY missing")

    token = _get_access_token(api_key, secret_key, timeout)
    if not token:
        raise ValueError("Failed to get Baidu OCR access_token")

    pages = []
    for idx, img in enumerate(images):
        data = _ocr_edu_test(img, token, timeout, endpoint, params or {})
        # Normalize doc_analysis results to words_result for downstream parsing
        if isinstance(data, dict) and "results" in data and "words_result" not in data:
            words_result = []
            for item in data.get("results") or []:
                words = item.get("words") or {}
                text = words.get("word")
                loc = words.get("words_location") or {}
                if text and loc:
                    words_result.append(
                        {
                            "words": text,
                            "location": {
                                "left": loc.get("left", 0),
                                "top": loc.get("top", 0),
                                "width": loc.get("width", 0),
                                "height": loc.get("height", 0),
                            },
                            "words_type": item.get("words_type"),
                        }
                    )
            data = {**data, "words_result": words_result}
        pages.append({"page_index": idx, "raw": data})

    return {"pages": pages}
