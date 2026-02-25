#!/usr/bin/env python3
import argparse
import hashlib
import json
import mimetypes
import os
import re
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

try:
    from PIL import Image, ImageOps
except Exception:  # pragma: no cover
    Image = None
    ImageOps = None

UUID_RE = re.compile(r"ES-\d{4}-[A-Z0-9]{6}")
IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def infer_practice_uuid(conn: sqlite3.Connection, path: Path) -> Tuple[Optional[str], str]:
    m = UUID_RE.search(str(path))
    if m:
        return m.group(0), "path_regex"

    name = path.name
    m_sub = re.search(r"submission_(\d+)_", name)
    if m_sub:
        row = conn.execute("SELECT practice_uuid FROM practice_sessions WHERE id = ?", (int(m_sub.group(1)),)).fetchone()
        if row and row[0]:
            return str(row[0]), "submission_filename_session_id"

    m_ai = re.search(r"ai_sheet_(\d+)_", name)
    if m_ai:
        # ai_sheet filename contains student_id, not session_id; cannot uniquely resolve
        return None, "ai_sheet_student_only"

    return None, "unresolved"


def image_meta(data: bytes) -> Tuple[Optional[int], Optional[int]]:
    if Image is None:
        return None, None
    try:
        from io import BytesIO
        with Image.open(BytesIO(data)) as img:
            if ImageOps is not None:
                img = ImageOps.exif_transpose(img)
            return img.size
    except Exception:
        return None, None


def insert_file(
    conn: sqlite3.Connection,
    practice_uuid: str,
    path: str,
    data: bytes,
    mime_type: str,
    dry_run: bool,
) -> str:
    sha = sha256_bytes(data)
    dup = conn.execute(
        "SELECT id FROM practice_files WHERE practice_uuid = ? AND sha256 = ? LIMIT 1",
        (practice_uuid, sha),
    ).fetchone()
    if dup:
        return "skipped_duplicate"
    if dry_run:
        return "would_insert"
    w, h = image_meta(data)
    now = utcnow_iso()
    conn.execute(
        """
        INSERT INTO practice_files(
            practice_uuid, file_uuid, kind, mime_type, original_filename, byte_size,
            sha256, width, height, meta_json, content_blob, created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            practice_uuid,
            str(uuid.uuid4()),
            "upload_image",
            mime_type,
            os.path.basename(path),
            len(data),
            sha,
            w,
            h,
            json.dumps({"migrated_from": path}, ensure_ascii=False),
            sqlite3.Binary(data),
            now,
            now,
        ),
    )
    return "inserted"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="backend/el.db")
    ap.add_argument("--base-dir", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--move-to", default="")
    ap.add_argument("--delete-after", action="store_true")
    ap.add_argument("--report", default=f"/tmp/migrate_uploads_to_db_{int(datetime.now().timestamp())}.jsonl")
    args = ap.parse_args()

    base_dir = Path(args.base_dir).resolve()
    report_path = Path(args.report).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    processed = 0
    with report_path.open("a", encoding="utf-8") as report:
        for p in sorted(base_dir.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in IMG_EXTS:
                continue
            if args.limit and processed >= args.limit:
                break
            processed += 1
            rec: Dict[str, Any] = {"source_path": str(p), "ts": utcnow_iso()}
            try:
                practice_uuid, method = infer_practice_uuid(conn, p)
                rec["resolve_method"] = method
                rec["practice_uuid"] = practice_uuid
                if not practice_uuid:
                    rec["status"] = "skipped_unresolved_practice_uuid"
                else:
                    data = p.read_bytes()
                    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
                    rec["status"] = insert_file(conn, practice_uuid, str(p), data, mime, args.dry_run)
                    if rec["status"] == "inserted":
                        conn.commit()
                    if rec["status"] in {"inserted", "skipped_duplicate"} and not args.dry_run:
                        if args.move_to:
                            target = Path(args.move_to).resolve() / p.relative_to(base_dir)
                            target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(p), str(target))
                            rec["moved_to"] = str(target)
                        elif args.delete_after:
                            p.unlink(missing_ok=True)
                            rec["deleted"] = True
            except Exception as e:
                conn.rollback()
                rec["status"] = "error"
                rec["error"] = str(e)
            report.write(json.dumps(rec, ensure_ascii=False) + "\n")

    conn.close()
    print(f"done. processed={processed} report={report_path}")


if __name__ == "__main__":
    main()
