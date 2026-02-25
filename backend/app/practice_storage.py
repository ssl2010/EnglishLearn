import hashlib
import io
import json
import mimetypes
import sqlite3
import uuid
from typing import Any, Dict, List, Optional

from PIL import Image, ImageOps

from .db import db, utcnow_iso


def _json_text(value: Optional[Dict[str, Any]]) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _sha256_hex(content: Optional[str] = None, raw_bytes: Optional[bytes] = None) -> Optional[str]:
    if raw_bytes is None and content is None:
        return None
    h = hashlib.sha256()
    if raw_bytes is not None:
        h.update(raw_bytes)
    else:
        h.update((content or "").encode("utf-8"))
    return h.hexdigest()


def save_ai_artifact(
    practice_uuid: str,
    engine: str,
    stage: str,
    content_type: str,
    raw_text: Optional[str] = None,
    raw_json: Optional[Dict[str, Any]] = None,
    meta: Optional[Dict[str, Any]] = None,
    source_path: Optional[str] = None,
) -> int:
    if not practice_uuid:
        raise ValueError("practice_uuid is required")
    if not engine or not stage or not content_type:
        raise ValueError("engine/stage/content_type are required")

    now = utcnow_iso()
    json_text = _json_text(raw_json) if raw_json is not None else None
    meta_text = _json_text(meta) if meta is not None else None
    sha = _sha256_hex(content=raw_text if raw_text is not None else json_text)
    with db() as conn:
        cur = conn.execute(
            """
            INSERT INTO practice_ai_artifacts (
                practice_uuid, engine, stage, content_type,
                content_text, content_json, meta_json, source_path, sha256,
                created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                practice_uuid,
                engine,
                stage,
                content_type,
                raw_text,
                json_text,
                meta_text,
                source_path,
                sha,
                now,
                now,
            ),
        )
        return int(cur.lastrowid)


def save_practice_file(
    practice_uuid: str,
    file_bytes: bytes,
    mime_type: Optional[str],
    original_filename: Optional[str],
    kind: str = "upload_image",
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if not practice_uuid:
        raise ValueError("practice_uuid is required")
    if not isinstance(file_bytes, (bytes, bytearray)) or not file_bytes:
        raise ValueError("file_bytes is required")
    mime = (mime_type or "").strip() or (
        mimetypes.guess_type(original_filename or "")[0] if original_filename else None
    ) or "application/octet-stream"

    width = None
    height = None
    try:
        with Image.open(io.BytesIO(file_bytes)) as img:
            img = ImageOps.exif_transpose(img)
            width, height = img.size
    except Exception:
        width = None
        height = None

    now = utcnow_iso()
    file_uuid = str(uuid.uuid4())
    sha = _sha256_hex(raw_bytes=bytes(file_bytes))
    meta_text = _json_text(meta) if meta is not None else None
    with db() as conn:
        conn.execute(
            """
            INSERT INTO practice_files (
                practice_uuid, file_uuid, kind, mime_type, original_filename,
                byte_size, sha256, width, height, meta_json, content_blob,
                created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                practice_uuid,
                file_uuid,
                kind,
                mime,
                original_filename,
                len(file_bytes),
                sha,
                width,
                height,
                meta_text,
                sqlite3.Binary(bytes(file_bytes)),  # type: ignore[name-defined]
                now,
                now,
            ),
        )
    return {
        "practice_uuid": practice_uuid,
        "file_uuid": file_uuid,
        "kind": kind,
        "mime_type": mime,
        "byte_size": len(file_bytes),
        "sha256": sha,
        "width": width,
        "height": height,
    }


def list_practice_files(practice_uuid: str, kind: Optional[str] = None) -> List[Dict[str, Any]]:
    sql = """
        SELECT file_uuid, kind, mime_type, original_filename, byte_size, sha256,
               width, height, meta_json, created_at, updated_at
        FROM practice_files
        WHERE practice_uuid = ?
    """
    args: List[Any] = [practice_uuid]
    if kind:
        sql += " AND kind = ?"
        args.append(kind)
    sql += " ORDER BY created_at DESC, id DESC"
    with db() as conn:
        rows = conn.execute(sql, tuple(args)).fetchall()
    out: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        try:
            item["meta_json"] = json.loads(item["meta_json"]) if item.get("meta_json") else None
        except Exception:
            pass
        item["download_url"] = f"/api/files/{item['file_uuid']}"
        out.append(item)
    return out


def get_practice_file_by_uuid(file_uuid: str) -> Optional[Dict[str, Any]]:
    with db() as conn:
        row = conn.execute(
            """
            SELECT practice_uuid, file_uuid, kind, mime_type, original_filename, byte_size,
                   sha256, width, height, meta_json, content_blob, created_at, updated_at
            FROM practice_files
            WHERE file_uuid = ?
            """,
            (file_uuid,),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    try:
        item["meta_json"] = json.loads(item["meta_json"]) if item.get("meta_json") else None
    except Exception:
        pass
    return item


def list_ai_artifacts(
    practice_uuid: str,
    engine: Optional[str] = None,
    stage: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    sql = """
        SELECT id, practice_uuid, engine, stage, content_type,
               content_text, content_json, meta_json, source_path, sha256,
               created_at, updated_at
        FROM practice_ai_artifacts
        WHERE practice_uuid = ?
    """
    args: List[Any] = [practice_uuid]
    if engine:
        sql += " AND engine = ?"
        args.append(engine)
    if stage:
        sql += " AND stage = ?"
        args.append(stage)
    sql += " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?"
    args.extend([max(1, int(limit)), max(0, int(offset))])
    with db() as conn:
        rows = conn.execute(sql, tuple(args)).fetchall()
    out: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        for key in ("content_json", "meta_json"):
            try:
                item[key] = json.loads(item[key]) if item.get(key) else None
            except Exception:
                pass
        txt = item.get("content_text")
        cj = item.get("content_json")
        item["has_content"] = bool(txt or cj)
        item["content_length"] = len(txt) if isinstance(txt, str) else (len(json.dumps(cj, ensure_ascii=False)) if cj is not None else 0)
        out.append(item)
    return out


def get_latest_ai_artifact(
    practice_uuid: str,
    engine: Optional[str] = None,
    stage: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    rows = list_ai_artifacts(practice_uuid, engine=engine, stage=stage, limit=1, offset=0)
    return rows[0] if rows else None


def save_ai_bundle_raw_to_db(
    practice_uuid: str,
    llm_raw: Optional[Dict[str, Any]],
    ocr_raw: Optional[Dict[str, Any]],
    meta: Optional[Dict[str, Any]] = None,
    source_tag: Optional[str] = None,
) -> Dict[str, int]:
    """Best-effort helper to store LLM/OCR raw in DB while preserving existing pipeline."""
    inserted = 0
    if llm_raw is not None:
        save_ai_artifact(
            practice_uuid=practice_uuid,
            engine="llm_vision",
            stage="response",
            content_type="application/json",
            raw_json=llm_raw,
            meta={"source_tag": source_tag, **(meta or {})},
        )
        inserted += 1
    if ocr_raw is not None:
        save_ai_artifact(
            practice_uuid=practice_uuid,
            engine="ocr",
            stage="response",
            content_type="application/json",
            raw_json=ocr_raw,
            meta={"source_tag": source_tag, **(meta or {})},
        )
        inserted += 1
    return {"inserted": inserted}

