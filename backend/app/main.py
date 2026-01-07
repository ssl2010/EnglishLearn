import os
import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

_DOTENV_PATH = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
load_dotenv(_DOTENV_PATH, override=False)

from .db import init_db
from .services import (
    bootstrap_single_child,
    create_base,
    generate_practice_session,
    get_dashboard,
    get_system_status,
    list_bases,
    list_sessions,
    manual_correct_session,
    search_practice_sessions,
    get_practice_session_detail,
    regenerate_practice_pdfs,
    delete_practice_session,
    upsert_items,
    upload_submission_image,
    upload_marked_submission_image,
    confirm_mark_grading,
    get_setting,
    set_setting,
    analyze_ai_photos,
    analyze_ai_photos_from_debug,
    confirm_ai_extracted,
    MEDIA_DIR,
    ensure_media_dir,
)


app = FastAPI(title="English Learning MVP", version="0.1.0")
_cleanup_thread_started = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class BootstrapReq(BaseModel):
    student_name: str
    grade_code: str


class CreateBaseReq(BaseModel):
    name: str
    grade_code: str = ""  # Deprecated but kept for compatibility
    is_system: bool = False
    description: Optional[str] = None
    education_stage: Optional[str] = None
    grade: Optional[str] = None
    term: Optional[str] = None
    version: Optional[str] = None
    publisher: Optional[str] = None
    editor: Optional[str] = None


class ImportItemsReq(BaseModel):
    base_id: int
    mode: str = Field("skip", pattern="^(skip|update)$")
    items: List[Dict]


class GenerateReq(BaseModel):
    student_id: int
    base_id: Optional[int] = None  # For backward compatibility
    unit_scope: Optional[List[str]] = None  # For backward compatibility
    base_units: Optional[Dict[int, List[str]]] = None  # New: {base_id: [units]}
    total_count: int = 20
    mix_ratio: Dict[str, int] = Field(default_factory=lambda: {"WORD": 15, "PHRASE": 8, "SENTENCE": 6})
    title: str = "Dictation Practice (C → E)"
    difficulty_filter: Optional[str] = None  # Filter by difficulty: "write", "read", or None (all)


class ManualCorrectReq(BaseModel):
    # mapping position -> raw answer
    answers: Dict[str, str]


def _cleanup_loop() -> None:
    logger = logging.getLogger("uvicorn.error")
    from .services import cleanup_old_sessions
    while True:
        hour, minute, interval_days, undownloaded_days = _get_cleanup_config()
        next_run = _next_cleanup_time(hour, minute, interval_days)
        sleep_seconds = max(1, int((next_run - _now_bj()).total_seconds()))
        logger.info(f"[CLEANUP] Next auto cleanup at {next_run.isoformat()} (sleep {sleep_seconds}s)")
        time.sleep(sleep_seconds)
        try:
            result = cleanup_old_sessions(undownloaded_days=undownloaded_days)
            logger.info(
                "[CLEANUP] Auto cleanup: deleted_sessions=%s deleted_pdfs=%s",
                result.get("deleted_sessions"),
                result.get("deleted_pdfs"),
            )
        except Exception as e:
            logger.warning(f"[CLEANUP] Auto cleanup failed: {e}")


def _start_cleanup_task() -> None:
    global _cleanup_thread_started
    if _cleanup_thread_started:
        return
    _cleanup_thread_started = True
    t = threading.Thread(target=_cleanup_loop, daemon=True, name="cleanup-worker")
    t.start()


def _now_bj() -> datetime:
    return datetime.now(timezone(timedelta(hours=8)))


def _get_cleanup_config() -> tuple[int, int, int, int]:
    raw_time = os.environ.get("EL_CLEANUP_TIME", "03:00")
    hour = 3
    minute = 0
    if raw_time:
        parts = raw_time.split(":")
        if len(parts) >= 1:
            try:
                hour = int(parts[0])
            except ValueError:
                hour = 3
        if len(parts) >= 2:
            try:
                minute = int(parts[1])
            except ValueError:
                minute = 0
    interval_days = int(os.environ.get("EL_CLEANUP_INTERVAL_DAYS", "1") or 1)
    undownloaded_days = int(os.environ.get("EL_CLEANUP_UNDOWNLOADED_DAYS", "14") or 14)
    if interval_days < 1:
        interval_days = 1
    return hour, minute, interval_days, undownloaded_days


def _next_cleanup_time(hour: int, minute: int, interval_days: int) -> datetime:
    now = _now_bj()
    next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if next_run <= now:
        next_run += timedelta(days=interval_days)
    return next_run


@app.on_event("startup")
def _startup() -> None:
    init_db()
    _start_cleanup_task()


class SettingsResp(BaseModel):
    mastery_threshold: int = 2
    weekly_target_days: int = 4


class UpdateSettingsReq(BaseModel):
    mastery_threshold: Optional[int] = Field(default=None, ge=1, le=10)
    weekly_target_days: Optional[int] = Field(default=None, ge=1, le=7)


class AISuggestReq(BaseModel):
    preference_text: str = Field(default="")
    word_count: int = 15
    phrase_count: int = 8
    sentence_count: int = 6


class AIExtractItem(BaseModel):
    model_config = {"extra": "allow"}  # Allow extra fields not defined in model

    position: int
    zh_hint: Optional[str] = None
    student_text: str = ""
    matched_item_id: Optional[int] = None
    matched_en_text: Optional[str] = None
    matched_type: Optional[str] = None
    kb_hit: Optional[bool] = None
    is_correct: bool = True
    include: bool = True
    llm_text: Optional[str] = None
    ocr_text: Optional[str] = None
    source: Optional[str] = None
    section_title: Optional[str] = None
    section_type: Optional[str] = None
    note: Optional[str] = None
    confidence: Optional[float] = None
    consistency_ok: Optional[bool] = None
    consistency_ratio: Optional[float] = None
    page_index: Optional[int] = None
    handwriting_bbox: Optional[List[float]] = None
    line_bbox: Optional[List[float]] = None
    crop_url: Optional[str] = None
    ocr_match_ratio: Optional[float] = None
    match_method: Optional[str] = None


class AIConfirmReq(BaseModel):
    student_id: int
    base_id: int
    items: List[AIExtractItem]
    extracted_date: Optional[str] = None
    worksheet_uuid: Optional[str] = None
    force_duplicate: bool = False
    bundle_id: Optional[str] = None

@app.post("/api/bootstrap")
def api_bootstrap(req: BootstrapReq):
    return bootstrap_single_child(req.student_name, req.grade_code)


# ============================================================
# Student API Endpoints
# ============================================================

@app.get("/api/students")
def api_get_students():
    """Get all students"""
    from .db import db, get_students
    with db() as conn:
        students = get_students(conn)
    return {"students": students}


@app.get("/api/students/{student_id}")
def api_get_student(student_id: int):
    """Get single student"""
    from .db import db, get_student
    with db() as conn:
        student = get_student(conn, student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    return student


class CreateStudentReq(BaseModel):
    name: str
    grade: Optional[str] = None


@app.post("/api/students")
def api_create_student(req: CreateStudentReq):
    """Create new student"""
    from .db import db, create_student
    with db() as conn:
        student_id = create_student(conn, req.name, req.grade)
    return {"student_id": student_id}


class UpdateStudentReq(BaseModel):
    name: Optional[str] = None
    grade: Optional[str] = None
    avatar: Optional[str] = None


@app.put("/api/students/{student_id}")
def api_update_student(student_id: int, req: UpdateStudentReq):
    """Update student info"""
    from .db import db, update_student, get_student
    with db() as conn:
        update_student(conn, student_id, req.name, req.grade, req.avatar)
        student = get_student(conn, student_id)
    return student


@app.get("/api/system/status")
def api_status(student_id: int, base_id: int):
    return get_system_status(student_id, base_id)


@app.get("/api/knowledge-bases")
def api_list_bases(grade_code: Optional[str] = None, is_system: Optional[bool] = None):
    """List bases with optional filters"""
    from .db import db, get_bases
    with db() as conn:
        bases = get_bases(conn, is_system=is_system)
    return {"bases": bases}


@app.post("/api/knowledge-bases")
def api_create_base(req: CreateBaseReq):
    base_id = create_base(
        name=req.name,
        grade_code=req.grade_code,
        is_system=req.is_system,
        education_stage=req.education_stage,
        grade=req.grade,
        term=req.term,
        version=req.version,
        publisher=req.publisher,
        editor=req.editor,
        notes=req.description  # Map description to notes parameter
    )
    return {"base_id": base_id}


class UpdateBaseReq(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_system: Optional[bool] = None
    education_stage: Optional[str] = None
    grade: Optional[str] = None
    term: Optional[str] = None
    version: Optional[str] = None
    publisher: Optional[str] = None
    editor: Optional[str] = None


@app.put("/api/knowledge-bases/{base_id}")
def api_update_base(base_id: int, req: UpdateBaseReq):
    """Update base"""
    from .db import db, update_base, get_base
    with db() as conn:
        update_base(
            conn, base_id,
            name=req.name,
            description=req.description,
            is_system=req.is_system,
            education_stage=req.education_stage,
            grade=req.grade,
            term=req.term,
            version=req.version,
            publisher=req.publisher,
            editor=req.editor
        )
        base = get_base(conn, base_id)
    return base


@app.post("/api/knowledge-bases/{base_id}/cover")
async def api_upload_base_cover(base_id: int, file: UploadFile = File(...)):
    """Upload cover image for knowledge base"""
    import os
    from .db import db, update_base, get_base
    from .services import MEDIA_DIR, ensure_media_dir

    # Validate file type
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=422, detail="File must be an image")

    # Ensure media directory exists
    ensure_media_dir()

    # Generate unique filename
    import uuid
    ext = file.filename.split(".")[-1] if "." in file.filename else "jpg"
    filename = f"cover_{base_id}_{uuid.uuid4().hex[:8]}.{ext}"
    filepath = os.path.join(MEDIA_DIR, filename)

    # Save file
    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)

    # Update database
    cover_url = f"/media/{filename}"
    with db() as conn:
        update_base(conn, base_id, cover_image=cover_url)
        base = get_base(conn, base_id)

    return {"cover_url": cover_url, "base": base}


@app.delete("/api/knowledge-bases/{base_id}")
def api_delete_base(base_id: int, force: bool = False):
    """Delete base

    Checks if base is used in any student's learning library.
    If used, returns 422 with list of students (unless force=True for admin).

    Args:
        base_id: Knowledge base ID to delete
        force: Admin override flag (future feature, currently disabled)
    """
    from .db import db, delete_base, get_base

    with db() as conn:
        # Check if base exists
        base = get_base(conn, base_id)
        if not base:
            raise HTTPException(status_code=404, detail="知识库不存在")

        # Check if base is used in any learning library
        check_sql = """
            SELECT slb.id, slb.student_id, s.name as student_name
            FROM student_learning_bases slb
            JOIN students s ON slb.student_id = s.id
            WHERE slb.base_id = ?
        """
        usage_rows = conn.execute(check_sql, (base_id,)).fetchall()

        if usage_rows and not force:
            # Base is in use, cannot delete (unless force=True)
            students = [{"student_id": row["student_id"], "student_name": row["student_name"]}
                       for row in usage_rows]
            student_names = ", ".join([s["student_name"] for s in students])

            raise HTTPException(
                status_code=422,
                detail=f"无法删除知识库\"{base['name']}\"，因为以下学生的学习库中正在使用：{student_names}。\n\n请先在\"学习库管理\"中将该知识库从学生学习库中移除，然后再删除。"
            )

        # TODO: When force=True (admin feature), log warning about students affected
        # For now, force parameter is ignored (no admin system yet)
        if force and usage_rows:
            # Future: Log admin action
            # Example: logger.warning(f"Admin force-deleted base {base_id} affecting {len(usage_rows)} students")
            pass

        # No usage (or admin override), safe to delete
        delete_base(conn, base_id)

    return {"success": True}


@app.get("/api/knowledge-bases/{base_id}/units")
def api_get_base_units(base_id: int):
    """Get unit metadata for a base"""
    from .db import db, get_units
    with db() as conn:
        units = get_units(conn, base_id)
    return {"units": units}


class ImportUnitsReq(BaseModel):
    units: List[Dict]


@app.post("/api/knowledge-bases/{base_id}/units/import")
def api_import_units(base_id: int, req: ImportUnitsReq):
    """Import unit metadata for a base"""
    from .db import db, upsert_units
    with db() as conn:
        result = upsert_units(conn, base_id, req.units)
    return result


@app.get("/api/knowledge-bases/{base_id}/items")
def api_get_base_items(base_id: int, unit: Optional[str] = None):
    """Get items for a base"""
    from .db import db, get_base_items
    with db() as conn:
        items = get_base_items(conn, base_id, unit=unit)
    return {"items": items}


class CreateItemReq(BaseModel):
    base_id: int
    zh_text: str
    en_text: str
    unit: Optional[str] = "__ALL__"
    item_type: str = "WORD"
    difficulty_tag: Optional[str] = None


@app.post("/api/knowledge-items")
def api_create_item(req: CreateItemReq):
    """Create a new knowledge item"""
    from .db import db, create_item
    with db() as conn:
        item_id = create_item(
            conn,
            base_id=req.base_id,
            zh_text=req.zh_text,
            en_text=req.en_text,
            unit=req.unit or "__ALL__",
            position=None,  # Auto-calculate
            item_type=req.item_type,
            difficulty_tag=req.difficulty_tag
        )
    return {"item_id": item_id}


class UpdateItemReq(BaseModel):
    zh_text: Optional[str] = None
    en_text: Optional[str] = None
    unit: Optional[str] = None
    item_type: Optional[str] = None
    difficulty_tag: Optional[str] = None


@app.put("/api/knowledge-items/{item_id}")
def api_update_item(item_id: int, req: UpdateItemReq):
    """Update knowledge item"""
    from .db import db, update_item, get_item
    with db() as conn:
        update_item(conn, item_id, req.zh_text, req.en_text, req.unit, None, req.item_type, req.difficulty_tag)
        item = get_item(conn, item_id)
    return item


@app.delete("/api/knowledge-items/{item_id}")
def api_delete_item(item_id: int):
    """Delete knowledge item"""
    from .db import db, delete_item
    with db() as conn:
        delete_item(conn, item_id)
    return {"success": True}


# ============================================================
# Learning Library API Endpoints
# ============================================================

@app.get("/api/students/{student_id}/learning-bases")
def api_get_learning_bases(student_id: int, is_active: Optional[bool] = None):
    """Get student's learning library"""
    from .db import db, get_student_learning_bases
    with db() as conn:
        learning_bases = get_student_learning_bases(conn, student_id, is_active=is_active)
    return {"learning_bases": learning_bases}


class AddLearningBaseReq(BaseModel):
    base_id: int
    custom_name: Optional[str] = None
    current_unit: Optional[str] = None


@app.post("/api/students/{student_id}/learning-bases")
def api_add_learning_base(student_id: int, req: AddLearningBaseReq):
    """Add base to student's learning library"""
    from .db import db, add_learning_base, get_student, get_base
    try:
        with db() as conn:
            student = get_student(conn, student_id)
            if not student:
                raise HTTPException(status_code=400, detail=f"学生不存在: {student_id}")
            base = get_base(conn, req.base_id)
            if not base:
                raise HTTPException(status_code=400, detail=f"资料库不存在: {req.base_id}")
            lb_id = add_learning_base(conn, student_id, req.base_id, req.custom_name, req.current_unit)
        return {"id": lb_id}
    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        if "UNIQUE constraint failed" in error_msg:
            raise HTTPException(status_code=400, detail="该资料库已在学习库中")
        raise HTTPException(status_code=500, detail=f"添加失败: {error_msg}")


class UpdateLearningBaseReq(BaseModel):
    custom_name: Optional[str] = None
    current_unit: Optional[str] = None
    is_active: Optional[bool] = None


@app.put("/api/students/{student_id}/learning-bases/{lb_id}")
def api_update_learning_base(student_id: int, lb_id: int, req: UpdateLearningBaseReq):
    """Update learning base configuration"""
    from .db import db, update_learning_base, get_student_learning_bases
    with db() as conn:
        update_learning_base(conn, lb_id, req.custom_name, req.current_unit, req.is_active)
        # Return updated learning bases list
        learning_bases = get_student_learning_bases(conn, student_id)
    return {"learning_bases": learning_bases}


@app.delete("/api/students/{student_id}/learning-bases/{lb_id}")
def api_remove_learning_base(student_id: int, lb_id: int):
    """Remove base from student's learning library"""
    from .db import db, remove_learning_base
    with db() as conn:
        remove_learning_base(conn, lb_id)
    return {"success": True}


@app.get("/api/students/{student_id}/bases/{base_id}/mastery-stats")
def api_get_mastery_stats(student_id: int, base_id: int):
    """Get detailed mastery statistics for a base, grouped by item type and difficulty tag

    Returns statistics showing:
    - Total items by type (WORD/PHRASE/SENTENCE) and difficulty (write/recognize/NULL)
    - Mastered items (consecutive_correct >= mastery_threshold)
    - Learning items (attempted but not mastered)
    - Not started items (never attempted)
    """
    from .db import db
    from .services import get_setting

    mastery_threshold = int(get_setting("mastery_threshold", "2"))

    with db() as conn:
        # Get all items for this base with their stats
        query = """
            SELECT
                i.item_type,
                i.difficulty_tag,
                COUNT(i.id) as total,
                COUNT(CASE WHEN sis.consecutive_correct >= ? THEN 1 END) as mastered,
                COUNT(CASE WHEN sis.total_attempts > 0 AND sis.consecutive_correct < ? THEN 1 END) as learning,
                COUNT(CASE WHEN sis.total_attempts IS NULL OR sis.total_attempts = 0 THEN 1 END) as not_started
            FROM items i
            LEFT JOIN student_item_stats sis ON sis.item_id = i.id AND sis.student_id = ?
            WHERE i.base_id = ?
            GROUP BY i.item_type, i.difficulty_tag
            ORDER BY
                CASE i.item_type
                    WHEN 'WORD' THEN 1
                    WHEN 'PHRASE' THEN 2
                    WHEN 'SENTENCE' THEN 3
                    ELSE 4
                END,
                CASE i.difficulty_tag
                    WHEN 'write' THEN 1
                    WHEN 'recognize' THEN 2
                    ELSE 3
                END
        """

        rows = conn.execute(query, (mastery_threshold, mastery_threshold, student_id, base_id)).fetchall()

        stats = []
        for row in rows:
            stats.append({
                "item_type": row["item_type"],
                "difficulty_tag": row["difficulty_tag"],
                "total": row["total"],
                "mastered": row["mastered"],
                "learning": row["learning"],
                "not_started": row["not_started"]
            })

        unit_query = """
            SELECT
                i.unit,
                i.item_type,
                i.difficulty_tag,
                COUNT(i.id) as total,
                COUNT(CASE WHEN sis.consecutive_correct >= ? THEN 1 END) as mastered,
                COUNT(CASE WHEN sis.total_attempts > 0 AND sis.consecutive_correct < ? THEN 1 END) as learning,
                COUNT(CASE WHEN sis.total_attempts IS NULL OR sis.total_attempts = 0 THEN 1 END) as not_started
            FROM items i
            LEFT JOIN student_item_stats sis ON sis.item_id = i.id AND sis.student_id = ?
            WHERE i.base_id = ?
            GROUP BY i.unit, i.item_type, i.difficulty_tag
        """
        unit_rows = conn.execute(unit_query, (mastery_threshold, mastery_threshold, student_id, base_id)).fetchall()
        unit_stats = []
        for row in unit_rows:
            unit_stats.append({
                "unit": row["unit"],
                "item_type": row["item_type"],
                "difficulty_tag": row["difficulty_tag"],
                "total": row["total"],
                "mastered": row["mastered"],
                "learning": row["learning"],
                "not_started": row["not_started"],
            })

    return {"stats": stats, "unit_stats": unit_stats, "mastery_threshold": mastery_threshold}


@app.get("/api/students/{student_id}/bases/{base_id}/items")
def api_get_base_items_with_stats(
    student_id: int,
    base_id: int,
    unit: Optional[str] = None,
):
    """Get items for a base with per-student mastery/practice stats."""
    from .db import db
    from .services import get_setting

    mastery_threshold = int(get_setting("mastery_threshold", "2"))
    sql = """
        SELECT
            i.id,
            i.unit,
            i.item_type,
            i.zh_text,
            i.en_text,
            i.difficulty_tag,
            sis.total_attempts,
            sis.correct_attempts,
            sis.consecutive_correct
        FROM items i
        LEFT JOIN student_item_stats sis
            ON sis.item_id = i.id AND sis.student_id = ?
        WHERE i.base_id = ?
    """
    params: List = [student_id, base_id]
    if unit and unit not in ("__ALL__", "all"):
        sql += " AND i.unit = ?"
        params.append(unit)
    sql += """
        ORDER BY
            CASE i.item_type
                WHEN 'WORD' THEN 1
                WHEN 'PHRASE' THEN 2
                WHEN 'SENTENCE' THEN 3
                ELSE 4
            END,
            CASE i.difficulty_tag
                WHEN 'write' THEN 1
                WHEN 'recognize' THEN 2
                WHEN 'read' THEN 2
                ELSE 3
            END,
            i.id
    """
    with db() as conn:
        rows = conn.execute(sql, params).fetchall()

    items = []
    for row in rows:
        total_attempts = row["total_attempts"] or 0
        correct_attempts = row["correct_attempts"] or 0
        consecutive_correct = row["consecutive_correct"] or 0
        if total_attempts <= 0:
            mastery_status = "not_started"
        elif consecutive_correct >= mastery_threshold:
            mastery_status = "mastered"
        else:
            mastery_status = "learning"
        items.append({
            "id": row["id"],
            "unit": row["unit"],
            "item_type": row["item_type"],
            "zh_text": row["zh_text"],
            "en_text": row["en_text"],
            "difficulty_tag": row["difficulty_tag"],
            "total_attempts": total_attempts,
            "correct_attempts": correct_attempts,
            "consecutive_correct": consecutive_correct,
            "mastery_status": mastery_status,
        })

    return {"items": items, "mastery_threshold": mastery_threshold}


@app.post("/api/knowledge-items/import")
def api_import_items(req: ImportItemsReq):
    return upsert_items(req.base_id, req.items, mode=req.mode)



@app.post("/api/knowledge-bases/import-file")
async def api_import_base_file(
    file: UploadFile = File(...),
    mode: str = "skip",
):
    """Import a knowledge base from an uploaded JSON file.

    Supported formats:
    - EL_KB_V1: Basic format with base + items
    - EL_KB_V1_UNITMETA: Enhanced format with unit_meta (ignored)

    Expected payload (both formats):
    {
      "format": "EL_KB_V1" or "EL_KB_V1_UNITMETA",
      "base": {"name": "...", "grade_code": "G4", ...},
      "items": [
        {
          "type": "WORD",
          "unit_code": "U1",
          "en_text": "...",
          "zh_hint": "...",
          "difficulty_tag": "write"  // Optional, ignored
        }
      ],
      "unit_meta": [...]  // Optional, ignored
    }

    Field mapping:
    - zh_hint -> zh_text
    - type -> item_type
    - unit_code -> unit

    Behavior:
    - Always creates a new knowledge base using payload.base (or filename fallback)
    - Then bulk-imports items into that base (mode=skip|update)
    - Ignores extra fields: unit_meta, difficulty_tag, etc.
    - Returns {"base_id":..., "inserted":..., "updated":..., "skipped":...}
    """
    raw = await file.read()
    # accept UTF-8 with optional BOM
    try:
        text = raw.decode("utf-8-sig")
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"File encoding must be UTF-8: {e}")

    try:
        payload = json.loads(text)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid JSON: {e}")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Payload must be a JSON object")

    base_meta = payload.get("base") or {}
    if not isinstance(base_meta, dict):
        raise HTTPException(status_code=422, detail="payload.base must be an object")

    name = base_meta.get("name") or payload.get("name")
    grade_code = base_meta.get("grade_code") or payload.get("grade_code")

    # Derive grade_code from grade_number if not present (for EL_KB_V1_UNITMETA format)
    if not grade_code and "grade_number" in base_meta:
        grade_number = base_meta["grade_number"]
        grade_code = f"G{grade_number}"

    # Extract metadata fields (try base object first, then top level)
    education_stage = base_meta.get("education_stage") or payload.get("education_stage")
    grade = base_meta.get("grade") or payload.get("grade")
    term = base_meta.get("term") or payload.get("term")
    version = base_meta.get("version") or payload.get("version")
    publisher = base_meta.get("publisher") or payload.get("publisher")
    editor = base_meta.get("editor") or base_meta.get("chief_editor") or payload.get("editor") or payload.get("chief_editor")
    notes = base_meta.get("notes") or base_meta.get("description") or payload.get("notes") or payload.get("description")

    if not name:
        # fallback to filename without extension
        fn = (file.filename or "ImportedBase").rsplit(".", 1)[0]
        name = fn

    if not grade_code:
        # fallback; user can still use it, but recommend passing grade_code
        grade_code = "G4"

    items = payload.get("items")
    if items is None and isinstance(payload.get("data"), dict):
        # allow {"data":{"items":[...]}}
        items = payload["data"].get("items")
    if items is None:
        raise HTTPException(status_code=422, detail="Missing payload.items")
    if not isinstance(items, list):
        raise HTTPException(status_code=422, detail="payload.items must be an array")

    # normalize mode
    if mode not in ("skip", "update"):
        raise HTTPException(status_code=422, detail="mode must be skip or update")

    base_id = create_base(
        name=str(name),
        grade_code=str(grade_code),
        is_system=False,
        education_stage=education_stage,
        grade=grade,
        term=term,
        version=version,
        publisher=publisher,
        editor=editor,
        notes=notes
    )

    assets = payload.get("assets")
    if assets is None and isinstance(payload.get("data"), dict):
        assets = payload["data"].get("assets")
    if isinstance(assets, list):
        cover_asset = next(
            (a for a in assets if isinstance(a, dict) and a.get("id") == "cover"),
            None,
        )
        if cover_asset:
            cover_data = (
                cover_asset.get("data")
                or cover_asset.get("content")
                or cover_asset.get("base64")
            )
            if cover_data:
                import base64
                import logging
                import uuid
                from .services import MEDIA_DIR, ensure_media_dir
                from .db import db, update_base

                logger = logging.getLogger("uvicorn.error")
                ext = "jpg"
                b64_data = str(cover_data)
                if b64_data.startswith("data:"):
                    header, b64_data = b64_data.split(",", 1)
                    if "image/png" in header:
                        ext = "png"
                    elif "image/webp" in header:
                        ext = "webp"
                try:
                    try:
                        decoded = base64.b64decode(b64_data, validate=True)
                    except Exception:
                        decoded = base64.b64decode(b64_data)
                except Exception as e:
                    decoded = None
                    logger.warning(f"[IMPORT] Failed to decode cover asset: {e}")

                if decoded:
                    ensure_media_dir()
                    filename = f"cover_{base_id}_{uuid.uuid4().hex[:8]}.{ext}"
                    filepath = os.path.join(MEDIA_DIR, filename)
                    try:
                        with open(filepath, "wb") as f:
                            f.write(decoded)
                        cover_url = f"/media/{filename}"
                        with db() as conn:
                            update_base(conn, base_id, cover_image=cover_url)
                    except Exception as e:
                        logger.warning(f"[IMPORT] Failed to save cover asset: {e}")

    # Import unit metadata if present (EL_KB_V1_UNITMETA format)
    unit_meta = payload.get("unit_meta")
    if unit_meta and isinstance(unit_meta, list):
        from .db import db, upsert_units
        with db() as conn:
            unit_result = upsert_units(conn, base_id, unit_meta)
        res_units = unit_result
    else:
        res_units = {"inserted": 0, "updated": 0}

    res = upsert_items(base_id, items, mode=mode)
    res["base_id"] = base_id
    res["units"] = res_units
    return res

@app.post("/api/practice-sessions/generate")
def api_generate(req: GenerateReq):
    try:
        # Validate: must provide either base_units OR (base_id + optional unit_scope)
        if req.base_units:
            # New multi-base mode
            data = generate_practice_session(
                student_id=req.student_id,
                base_units=req.base_units,
                total_count=req.total_count,
                mix_ratio={k.upper(): int(v) for k, v in req.mix_ratio.items()},
                title=req.title,
                difficulty_filter=req.difficulty_filter,
            )
        else:
            # Legacy single-base mode
            if not req.base_id:
                raise ValueError("Either base_units or base_id must be provided")
            data = generate_practice_session(
                student_id=req.student_id,
                base_id=req.base_id,
                unit_scope=req.unit_scope,
                total_count=req.total_count,
                mix_ratio={k.upper(): int(v) for k, v in req.mix_ratio.items()},
                title=req.title,
                difficulty_filter=req.difficulty_filter,
            )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        # Catch all other exceptions and return detailed error
        import traceback
        error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
        raise HTTPException(status_code=500, detail=error_detail)

    # Backward-compatible fields: pdf_path / answer_pdf_path already included.
    # Add browser-friendly download URLs under /media.
    import os as _os
    pdf_path = data.get("pdf_path")
    ans_path = data.get("answer_pdf_path")
    data["pdf_url"] = f"/media/{_os.path.basename(pdf_path)}" if pdf_path else None
    data["answer_pdf_url"] = f"/media/{_os.path.basename(ans_path)}" if ans_path else None
    return data


@app.get("/api/practice-sessions")
def api_list_sessions(student_id: int, base_id: int, limit: int = 30):
    return {"sessions": list_sessions(student_id, base_id, limit=limit)}


@app.get("/api/practice-sessions/search")
def api_search_sessions(
    student_id: int,
    base_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    practice_uuid: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = 50,
    page: Optional[int] = None,
    page_size: Optional[int] = None,
    offset: Optional[int] = None,
):
    if page is not None or page_size is not None:
        size = page_size or 20
        page_num = page or 1
        if page_num < 1:
            page_num = 1
        offset_val = (page_num - 1) * size
        limit_val = size
    elif offset is not None:
        offset_val = max(0, offset)
        limit_val = limit
        size = limit_val
        page_num = (offset_val // limit_val) + 1 if limit_val else 1
    else:
        offset_val = 0
        limit_val = limit
        size = limit_val
        page_num = 1

    sessions, total_count = search_practice_sessions(
        student_id=student_id,
        base_id=base_id,
        start_date=start_date,
        end_date=end_date,
        practice_uuid=practice_uuid,
        keyword=keyword,
        limit=limit_val,
        offset=offset_val,
    )
    return {
        "sessions": sessions,
        "count": total_count,
        "total": total_count,
        "page": page_num,
        "page_size": size,
    }


@app.delete("/api/practice-sessions/{session_id}")
def api_delete_practice_session(session_id: int):
    try:
        return delete_practice_session(session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/practice-sessions/by-uuid/{practice_uuid}")
def api_get_session_by_uuid(practice_uuid: str):
    """Query practice session by UUID"""
    from .db import db
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
                ps.downloaded_at,
                ps.pdf_path,
                ps.answer_pdf_path
            FROM practice_sessions ps
            WHERE ps.practice_uuid = ?
            """,
            (practice_uuid,)
        ).fetchone()

        if not session:
            raise HTTPException(status_code=404, detail="Practice session not found")

        session_dict = dict(session)

        # Add PDF URLs
        if session_dict.get("pdf_path"):
            import os
            session_dict["pdf_url"] = f"/media/{os.path.basename(session_dict['pdf_path'])}"
        if session_dict.get("answer_pdf_path"):
            import os
            session_dict["answer_pdf_url"] = f"/media/{os.path.basename(session_dict['answer_pdf_path'])}"

        # Get items
        items = conn.execute(
            """
            SELECT
                ei.position,
                ei.type,
                ei.en_text,
                ei.zh_hint
            FROM exercise_items ei
            WHERE ei.session_id = ?
            ORDER BY ei.position
            """,
            (session_dict["id"],)
        ).fetchall()

        session_dict["items"] = [dict(item) for item in items]

    return session_dict


@app.get("/api/practice-sessions/{session_id}/detail")
def api_get_session_detail(session_id: int):
    try:
        return get_practice_session_detail(session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/practice-sessions/{session_id}/regenerate-pdf")
def api_regenerate_pdf(session_id: int):
    try:
        return regenerate_practice_pdfs(session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/students/{student_id}/practice-sessions/by-date")
def api_get_sessions_by_date(
    student_id: int,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    downloaded_only: bool = False
):
    """Query practice sessions by student and date range

    Args:
        student_id: Student ID
        start_date: Start date (YYYY-MM-DD format), inclusive
        end_date: End date (YYYY-MM-DD format), inclusive
        downloaded_only: If true, only return downloaded sessions
    """
    from .db import db

    sql = """
        SELECT
            ps.id,
            ps.student_id,
            ps.base_id,
            ps.status,
            ps.created_at,
            ps.corrected_at,
            ps.practice_uuid,
            ps.created_date,
            ps.downloaded_at,
            ps.pdf_path,
            ps.answer_pdf_path,
            b.name as base_name
        FROM practice_sessions ps
        LEFT JOIN bases b ON ps.base_id = b.id
        WHERE ps.student_id = ?
    """
    params = [student_id]

    if start_date:
        sql += " AND ps.created_date >= ?"
        params.append(start_date)

    if end_date:
        sql += " AND ps.created_date <= ?"
        params.append(end_date)

    if downloaded_only:
        sql += " AND ps.downloaded_at IS NOT NULL"

    sql += " ORDER BY ps.created_date DESC, ps.id DESC"

    with db() as conn:
        sessions = conn.execute(sql, params).fetchall()
        sessions_list = []

        for session in sessions:
            session_dict = dict(session)

            # Add PDF URLs
            if session_dict.get("pdf_path"):
                import os
                session_dict["pdf_url"] = f"/media/{os.path.basename(session_dict['pdf_path'])}"
            if session_dict.get("answer_pdf_path"):
                import os
                session_dict["answer_pdf_url"] = f"/media/{os.path.basename(session_dict['answer_pdf_path'])}"

            sessions_list.append(session_dict)

    return {"sessions": sessions_list, "count": len(sessions_list)}


@app.post("/api/practice-sessions/{session_id}/submit-image")
def api_submit_image(session_id: int, file: UploadFile = File(...)):
    return upload_submission_image(session_id, file)



@app.post("/api/practice-sessions/{session_id}/submit-marked-photo")
def api_submit_marked_photo(
    session_id: int,
    files: List[UploadFile] = File(...),
    confirm_mismatch: bool = False,
    allow_external: bool = False,
):
    return upload_marked_submission_image(
        session_id,
        files,
        confirm_mismatch=confirm_mismatch,
        allow_external=allow_external,
    )


@app.post("/api/ai/grade-photos")
def api_ai_grade_photos(
    student_id: int,
    base_id: int,
    files: List[UploadFile] = File(...),
):
    return analyze_ai_photos(student_id, base_id, files)


@app.post("/api/ai/grade-photos-debug")
def api_ai_grade_photos_debug(
    student_id: int,
    base_id: int,
):
    """Debug mode: load from debug_last directory instead of calling LLM/OCR."""
    return analyze_ai_photos_from_debug(student_id, base_id)


@app.post("/api/ai/confirm-extracted")
def api_ai_confirm_extracted(req: AIConfirmReq):
    items = [it.model_dump() for it in req.items]
    return confirm_ai_extracted(
        req.student_id,
        req.base_id,
        items,
        req.extracted_date,
        req.worksheet_uuid,
        req.force_duplicate,
        req.bundle_id,
    )


class ConfirmMarksReq(BaseModel):
    # position -> is_correct
    marks: Dict[str, bool]


@app.post("/api/submissions/{submission_id}/confirm-marks")
def api_confirm_marks(submission_id: int, req: ConfirmMarksReq):
    final = {int(k): bool(v) for k, v in req.marks.items()}
    return confirm_mark_grading(submission_id, final)


@app.post("/api/practice-sessions/{session_id}/manual-correct")
def api_manual_correct(session_id: int, req: ManualCorrectReq):
    return manual_correct_session(session_id, req.answers)


@app.get("/api/dashboard")
def api_dashboard(student_id: int, base_id: int, days: int = 30):
    return get_dashboard(student_id, base_id, days=days)



@app.get("/api/settings")
def api_get_settings():
    return {
        "mastery_threshold": int(get_setting("mastery_threshold", "2")),
        "weekly_target_days": int(get_setting("weekly_target_days", "4")),
    }


@app.put("/api/settings")
def api_update_settings(req: UpdateSettingsReq):
    if req.mastery_threshold is not None:
        set_setting("mastery_threshold", str(int(req.mastery_threshold)))
    if req.weekly_target_days is not None:
        set_setting("weekly_target_days", str(int(req.weekly_target_days)))
    return api_get_settings()


@app.post("/api/admin/cleanup")
def api_cleanup_old_sessions(
    undownloaded_days: Optional[int] = None
):
    """清理旧的练习单和PDF文件

    Args:
        undownloaded_days: 会话与PDF保留天数（默认从.env读取）
    """
    from .services import cleanup_old_sessions
    if undownloaded_days is None:
        _, _, _, undownloaded_days = _get_cleanup_config()
    return cleanup_old_sessions(undownloaded_days)


@app.post("/api/ai/suggest-generation-params")
def api_ai_suggest(req: AISuggestReq):
    """阶段1：AI只做“参数建议”，不直接决定抽题逻辑。"""
    # Very light heuristic parser: extract numbers and keywords.
    text = (req.preference_text or "").lower()
    wc, pc, sc = req.word_count, req.phrase_count, req.sentence_count

    import re as _re
    nums = [int(x) for x in _re.findall(r"(\d+)", text)]
    # if user gives 3 numbers, treat as w/p/s
    if len(nums) >= 3:
        wc, pc, sc = nums[0], nums[1], nums[2]
    elif len(nums) == 1:
        # single number: apply to words
        wc = nums[0]

    if "单词" in text or "word" in text:
        if "多" in text or "more" in text:
            wc = max(wc, 18)
    if "短语" in text or "phrase" in text:
        if "多" in text or "more" in text:
            pc = max(pc, 10)
    if "句子" in text or "sentence" in text:
        if "多" in text or "more" in text:
            sc = max(sc, 8)

    return {"word_count": wc, "phrase_count": pc, "sentence_count": sc, "note": "AI仅做题量/偏好建议，实际出题仍严格从知识库抽取。"}



# Serve generated media (PDFs, uploads)
ensure_media_dir()

# Custom PDF endpoint with proper filename headers
@app.get("/media/{filepath:path}")
async def serve_media_file(filepath: str):
    """Serve media files with proper Content-Disposition headers for PDFs."""
    from fastapi.responses import FileResponse
    from urllib.parse import quote
    import os
    import re
    from .db import db, utcnow_iso

    file_path = os.path.join(MEDIA_DIR, filepath)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    # For PDF files, set Content-Disposition to show the actual filename
    if filepath.endswith('.pdf'):
        # Extract just the filename without path
        display_name = os.path.basename(filepath)

        # Track download for practice session PDFs
        # Filename format: Practice_YYYY-MM-DD_ES-XXXX-XXXXXX.pdf or Practice_YYYY-MM-DD_ES-XXXX-XXXXXX_Key.pdf
        uuid_match = re.search(r'(ES-\d{4}-[A-Z0-9]{6})', display_name)
        if uuid_match:
            practice_uuid = uuid_match.group(1)
            # Record download timestamp (only once - if downloaded_at is NULL)
            try:
                with db() as conn:
                    conn.execute(
                        "UPDATE practice_sessions SET downloaded_at = ? WHERE practice_uuid = ? AND downloaded_at IS NULL",
                        (utcnow_iso(), practice_uuid)
                    )
            except Exception as e:
                # Log error but don't fail the download
                import logging
                logging.getLogger("uvicorn.error").warning(f"Failed to track download for {practice_uuid}: {e}")

        # Use RFC 5987 encoding for UTF-8 filenames (supports Chinese)
        # Format: filename*=UTF-8''encoded_filename
        encoded_filename = quote(display_name)

        return FileResponse(
            file_path,
            media_type="application/pdf",
            headers={
                # Provide both ASCII fallback and UTF-8 encoded filename
                "Content-Disposition": f"inline; filename=\"practice.pdf\"; filename*=UTF-8''{encoded_filename}"
            }
        )

    # For other files, serve normally
    return FileResponse(file_path)

# IMPORTANT: Don't mount StaticFiles for /media anymore since we have a custom endpoint above
# app.mount('/media', StaticFiles(directory=MEDIA_DIR), name='media')

# Serve static frontend
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
