import os
import json
from typing import Dict, List, Optional

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

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
    upsert_items,
    upload_submission_image,
    upload_marked_submission_image,
    confirm_mark_grading,
    get_setting,
    set_setting,

)


app = FastAPI(title="English Learning MVP", version="0.1.0")

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
    grade_code: str
    is_system: bool = False


class ImportItemsReq(BaseModel):
    base_id: int
    mode: str = Field("skip", pattern="^(skip|update)$")
    items: List[Dict]


class GenerateReq(BaseModel):
    student_id: int
    base_id: int
    unit_scope: Optional[List[str]] = None
    total_count: int = 20
    mix_ratio: Dict[str, int] = Field(default_factory=lambda: {"WORD": 15, "PHRASE": 8, "SENTENCE": 6})
    title: str = "Dictation Practice (C → E)"


class ManualCorrectReq(BaseModel):
    # mapping position -> raw answer
    answers: Dict[str, str]


@app.on_event("startup")
def _startup() -> None:
    init_db()


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

@app.post("/api/bootstrap")
def api_bootstrap(req: BootstrapReq):
    return bootstrap_single_child(req.student_name, req.grade_code)


@app.get("/api/system/status")
def api_status(student_id: int, base_id: int):
    return get_system_status(student_id, base_id)


@app.get("/api/knowledge-bases")
def api_list_bases(grade_code: Optional[str] = None):
    return {"bases": list_bases(grade_code)}


@app.post("/api/knowledge-bases")
def api_create_base(req: CreateBaseReq):
    base_id = create_base(req.name, req.grade_code, req.is_system)
    return {"base_id": base_id}


@app.post("/api/knowledge-items/import")
def api_import_items(req: ImportItemsReq):
    return upsert_items(req.base_id, req.items, mode=req.mode)



@app.post("/api/knowledge-bases/import-file")
async def api_import_base_file(
    file: UploadFile = File(...),
    mode: str = "skip",
):
    """Import a knowledge base from an uploaded JSON file (EL_KB_V1).

    Expected payload:
    {
      "schema_version": "EL_KB_V1",
      "base": {"name": "...", "grade_code": "G4"},
      "items": [ ... ]
    }

    Behavior:
    - Always creates a new knowledge base using payload.base (or filename fallback)
    - Then bulk-imports items into that base (mode=skip|update)
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

    base_id = create_base(str(name), str(grade_code), is_system=False)
    res = upsert_items(base_id, items, mode=mode)
    res["base_id"] = base_id
    return res

@app.post("/api/practice-sessions/generate")
def api_generate(req: GenerateReq):
    data = generate_practice_session(
        student_id=req.student_id,
        base_id=req.base_id,
        unit_scope=req.unit_scope,
        total_count=req.total_count,
        mix_ratio={k.upper(): int(v) for k, v in req.mix_ratio.items()},
        title=req.title,
    )
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


@app.post("/api/practice-sessions/{session_id}/submit-image")
def api_submit_image(session_id: int, file: UploadFile = File(...)):
    return upload_submission_image(session_id, file)



@app.post("/api/practice-sessions/{session_id}/submit-marked-photo")
def api_submit_marked_photo(session_id: int, file: UploadFile = File(...)):
    return upload_marked_submission_image(session_id, file)


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
from .services import MEDIA_DIR, ensure_media_dir

ensure_media_dir()
# IMPORTANT: mount /media before '/' frontend mount
app.mount('/media', StaticFiles(directory=MEDIA_DIR), name='media')

# Serve static frontend
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
