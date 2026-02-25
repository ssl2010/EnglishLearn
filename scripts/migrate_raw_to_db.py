#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


UUID_RE = re.compile(r"ES-\d{4}-[A-Z0-9]{6}")


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def infer_engine_stage(path: Path) -> Tuple[str, str, str]:
    name = path.name.lower()
    if name == "llm_raw.json":
        return "llm_vision", "response", "application/json"
    if name == "ocr_raw.json":
        return "ocr", "response", "application/json"
    if name == "meta.json":
        return "fusion", "postprocess", "application/json"
    if name.endswith(".json"):
        return "fusion", "response", "application/json"
    return "fusion", "response", "text/plain"


def find_practice_uuid_in_json(data: Any) -> Optional[str]:
    if isinstance(data, dict):
        for key, value in data.items():
            if key in {"practice_uuid", "worksheet_uuid", "uuid"} and isinstance(value, str):
                m = UUID_RE.search(value)
                if m:
                    return m.group(0)
            got = find_practice_uuid_in_json(value)
            if got:
                return got
    elif isinstance(data, list):
        for item in data:
            got = find_practice_uuid_in_json(item)
            if got:
                return got
    elif isinstance(data, str):
        m = UUID_RE.search(data)
        if m:
            return m.group(0)
    return None


def resolve_practice_uuid(conn: sqlite3.Connection, source_path: Path, payload: Optional[Any]) -> Tuple[Optional[str], str]:
    m = UUID_RE.search(str(source_path))
    if m:
        return m.group(0), "path_regex"
    if payload is not None:
        got = find_practice_uuid_in_json(payload)
        if got:
            return got, "json_payload"

    # bundle_id -> submissions.text_raw -> practice_sessions.practice_uuid
    bundle_id = None
    for part in source_path.parts:
        if part.startswith("ai_") or part.startswith("debug_"):
            bundle_id = part
            break
    if bundle_id:
        rows = conn.execute(
            """
            SELECT ps.practice_uuid, sub.text_raw
            FROM submissions sub
            JOIN practice_sessions ps ON ps.id = sub.session_id
            WHERE sub.text_raw LIKE ?
            ORDER BY sub.id DESC
            """,
            (f'%\"bundle_id\"%{bundle_id}%',),
        ).fetchall()
        for row in rows:
            pu = row[0]
            if pu:
                return str(pu), "bundle_lookup"
            try:
                raw = json.loads(row[1] or "{}")
                p2 = raw.get("worksheet_uuid")
                if isinstance(p2, str) and UUID_RE.fullmatch(p2):
                    return p2, "bundle_payload_worksheet_uuid"
            except Exception:
                pass

    # session id fallback from path
    m_sid = re.search(r"(?:session|submission)_(\d+)", str(source_path))
    if m_sid:
        row = conn.execute("SELECT practice_uuid FROM practice_sessions WHERE id = ?", (int(m_sid.group(1)),)).fetchone()
        if row and row[0]:
            return str(row[0]), "session_id_lookup"

    return None, "unresolved"


def insert_artifact(
    conn: sqlite3.Connection,
    practice_uuid: str,
    engine: str,
    stage: str,
    content_type: str,
    content_text: Optional[str],
    content_json: Optional[str],
    meta_json: Optional[str],
    source_path: str,
    sha: str,
    dry_run: bool,
) -> str:
    dup = conn.execute(
        "SELECT id FROM practice_ai_artifacts WHERE source_path = ? OR (sha256 = ? AND practice_uuid = ?) LIMIT 1",
        (source_path, sha, practice_uuid),
    ).fetchone()
    if dup:
        return "skipped_duplicate"
    if dry_run:
        return "would_insert"
    now = utcnow_iso()
    conn.execute(
        """
        INSERT INTO practice_ai_artifacts(
            practice_uuid, engine, stage, content_type, content_text, content_json,
            meta_json, source_path, sha256, created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            practice_uuid, engine, stage, content_type, content_text, content_json,
            meta_json, source_path, sha, now, now
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
    ap.add_argument("--report", default=f"/tmp/migrate_raw_to_db_{int(datetime.now().timestamp())}.jsonl")
    args = ap.parse_args()

    base_dir = Path(args.base_dir).resolve()
    report_path = Path(args.report).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    processed = 0
    with report_path.open("a", encoding="utf-8") as report:
        for p in sorted(base_dir.rglob("*")):
            if not p.is_file():
                continue
            if args.limit and processed >= args.limit:
                break
            processed += 1
            rel = str(p)
            rec: Dict[str, Any] = {"source_path": rel, "ts": utcnow_iso()}
            try:
                raw = p.read_text(encoding="utf-8", errors="replace")
                engine, stage, content_type = infer_engine_stage(p)
                parsed = None
                content_text = raw
                content_json_text = None
                if content_type == "application/json":
                    try:
                        parsed = json.loads(raw)
                        content_json_text = json.dumps(parsed, ensure_ascii=False)
                        content_text = None
                    except Exception:
                        content_type = "text/plain"
                        content_text = raw
                practice_uuid, method = resolve_practice_uuid(conn, p, parsed)
                rec.update({"engine": engine, "stage": stage, "resolve_method": method, "practice_uuid": practice_uuid})
                if not practice_uuid:
                    rec["status"] = "skipped_unresolved_practice_uuid"
                else:
                    sha = sha256_text(content_json_text if content_json_text is not None else (content_text or ""))
                    rec["status"] = insert_artifact(
                        conn,
                        practice_uuid=practice_uuid,
                        engine=engine,
                        stage=stage,
                        content_type=content_type,
                        content_text=content_text,
                        content_json=content_json_text,
                        meta_json=json.dumps({"migrated_from": rel}, ensure_ascii=False),
                        source_path=rel,
                        sha=sha,
                        dry_run=args.dry_run,
                    )
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
