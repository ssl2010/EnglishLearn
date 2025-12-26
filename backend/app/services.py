import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from .db import db, utcnow_iso
from .normalize import normalize_answer
from .pdf_gen import ExerciseRow, render_dictation_pdf
from .mark_detect import detect_marks_on_practice_sheet

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




from fastapi import UploadFile


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

def upload_marked_submission_image(session_id: int, upload: UploadFile) -> Dict:
    """上传家长已批改的照片，并推断逐题对错（降低OCR压力）。

    - 默认（auto）：若配置了 OPENAI_API_KEY，则优先用 OpenAI 视觉大模型做整页解析；
      否则回退到 OpenCV 红笔痕迹检测。
    - 返回 proposed_grading；前端必须允许家长确认/修正后再入库（家长与模型都可能误判）。

    环境变量：
      - OPENAI_API_KEY: 开启 OpenAI 视觉
      - EL_OPENAI_VISION_MODEL: 可选，默认 gpt-4o-mini
      - EL_MARK_GRADING_PROVIDER: openai / opencv / auto（默认 auto）
    """
    ensure_media_dir()
    import uuid

    ext = os.path.splitext(upload.filename or "")[1].lower() or ".jpg"
    fname = f"marked_{session_id}_{uuid.uuid4().hex}{ext}"
    out_path = os.path.join(MEDIA_DIR, "uploads", fname)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    img_bytes = upload.file.read()
    with open(out_path, "wb") as f:
        f.write(img_bytes)

    # create submission
    submitted_at = utcnow_iso()
    with db() as conn:
        cur = conn.execute(
            """
            INSERT INTO submissions(session_id, submitted_at, image_path, text_raw, source)
            VALUES(?,?,?,?,?)
            """,
            (session_id, submitted_at, out_path, None, "PHOTO_MARKED"),
        )
        submission_id = int(cur.lastrowid)

        # mark as completed (submitted)
        conn.execute("UPDATE practice_sessions SET status='COMPLETED' WHERE id=?", (session_id,))

        ex_rows = conn.execute(
            "SELECT id, position, zh_hint, en_text FROM exercise_items WHERE session_id=? ORDER BY position ASC",
            (session_id,),
        ).fetchall()

    positions = [int(r["position"]) for r in ex_rows]

    # -------- Provider selection --------
    provider = (os.environ.get("EL_MARK_GRADING_PROVIDER") or "auto").lower()
    grading_provider = "opencv"
    openai_map: Dict[int, Dict] = {}

    if provider in ("openai", "auto"):
        try:
            from .openai_vision import analyze_marked_sheet, is_configured  # type: ignore

            if is_configured():
                expected_items = [
                    {"position": int(r["position"]), "zh_hint": r["zh_hint"], "expected_en": r["en_text"]}
                    for r in ex_rows
                ]
                analysis = analyze_marked_sheet(img_bytes, expected_items=expected_items)
                grading_provider = "openai"

                for it in (analysis.get("items") or []):
                    q = int(it.get("q"))
                    openai_map[q] = {
                        "parent_mark": it.get("parent_mark", "unknown"),
                        "confidence": float(it.get("confidence", 0.0)),
                        "student_text": it.get("student_text", "") or "",
                        "note": it.get("note", "") or "",
                    }

                # persist raw analysis for audit/debug
                with db() as conn:
                    conn.execute(
                        "UPDATE submissions SET text_raw=? WHERE id=?",
                        (json.dumps(analysis, ensure_ascii=False), submission_id),
                    )
        except Exception:
            grading_provider = "opencv"

    pred_map = {}
    if grading_provider == "opencv":
        preds = detect_marks_on_practice_sheet(img_bytes, positions=positions)
        pred_map = {p.position: p for p in preds}

    # -------- Build proposed grading --------
    proposed = []
    for r in ex_rows:
        pos = int(r["position"])

        proposed_mark = "unknown"
        student_text = ""
        note = ""
        red_ratio = None

        if grading_provider == "openai":
            it = openai_map.get(pos)
            if it:
                proposed_mark = str(it.get("parent_mark") or "unknown")
                confidence = float(it.get("confidence") or 0.0)
                student_text = str(it.get("student_text") or "")
                note = str(it.get("note") or "")
            else:
                confidence = 0.2
        else:
            p = pred_map.get(pos)
            if not p:
                confidence = 0.3
                red_ratio = 0.0
            else:
                confidence = float(p.confidence)
                red_ratio = float(p.red_ratio)
                proposed_mark = "correct" if p.is_correct else "incorrect"

        # For the current UI (checkbox): unknown -> default correct but low confidence.
        proposed_is_correct = True if proposed_mark in ("correct", "unknown") else False

        proposed.append(
            {
                "exercise_item_id": int(r["id"]),
                "position": pos,
                "zh_hint": r["zh_hint"],
                "expected_en": r["en_text"],
                "proposed_mark": proposed_mark,
                "proposed_is_correct": proposed_is_correct,
                "confidence": confidence,
                "student_text": student_text,
                "note": note,
                "red_ratio": red_ratio,
            }
        )

    return {
        "submission_id": submission_id,
        "image_path": out_path,
        "grading_provider": grading_provider,
        "proposed_grading": proposed,
        "hint": "建议：对的尽量不做标记；错的用红叉/圈错/划线。请在页面确认后提交入库。",
    }



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
