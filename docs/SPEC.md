# EnglishLearn – Current Spec (Updated)

This document reflects the current state of the project (post‑OCR changes). It replaces earlier drafts and focuses on the AI‑first grading flow.

## Scope & Goals
- Provide English dictation practice sheets and AI-assisted grading.
- Allow grading from arbitrary worksheets (not only system‑generated sheets).
- Use a vision LLM to extract student answers and bounding boxes; show them to parents for confirmation.

## Architecture Overview
- Backend: FastAPI (Python)
- Frontend: Static HTML served by backend
- DB: SQLite
- Media: PDFs and uploads stored under `backend/media/`

## Accounts & Data Isolation
- 账号体系：`accounts` + `auth_sessions`，cookie 为 `el_session`。
- 学生与自定义资料库归属到 `account_id`：
  - `students.account_id` 必填；每个账号独立学生集合。
  - `bases.account_id` 仅用于自定义资料库；`is_system=1` 时为 `NULL`，全局共享。
- 所有涉及 `student_id` / `base_id` / `session_id` / `submission_id` 的 API 必须校验归属关系，跨账号访问返回 404。
- 迁移脚本：`backend/migrate_add_account_scope.py` 为既有数据回填最早账户。

## Key Flows

### 1) Generate Practice Sheet
- Input: student_id, base_id, unit scope, mix ratio
- Output: practice PDF + answer PDF
- Route: `POST /api/practice-sessions/generate`

### 2) AI Grade From Photos (AI‑Only)
- Upload 1+ photos of any worksheet.
- LLM returns extracted items (question order, student answer, confidence, and bbox).
- Server matches extracted answers against knowledge base.
- Parent confirms which items should be recorded and correctness, then submit to DB.

Routes:
- `POST /api/ai/grade-photos?student_id=...&base_id=...`
- `POST /api/ai/confirm-extracted`

### 3) Session Matching (Best Effort)
- After AI extraction, server tries to match extracted items to an existing practice session.
- If matched, UI shows the most likely session; otherwise shows “no match”.

## AI / Vision

### Provider & Env
- API key:
  - `ARK_API_KEY` (Doubao Ark) or `OPENAI_API_KEY`
- Base URL:
  - `EL_OPENAI_BASE_URL` or `ARK_BASE_URL`
- Model:
  - `EL_OPENAI_VISION_MODEL`
- Max tokens:
  - `EL_AI_MAX_TOKENS` (default 6000)
  - `EL_AI_MAX_TOKENS_RETRY` (default 12000)

### Output Expectations
- The model must return JSON only.
- Each item includes:
  - `q`: question order
  - `zh_hint`: Chinese prompt if present
  - `student_text`: recognized student answer
  - `confidence`: 0–1
  - `page_index`: 0‑based page index
  - `handwriting_bbox`: bbox of handwritten answer (preferred)
  - `line_bbox`: bbox of answer line (fallback)

### Debug Mode
- `EL_AI_DEBUG_BBOX=1` produces overlay images with bounding boxes.
- `EL_AI_DEBUG_BBOX_MODE`:
  - `active` (default) – show only bbox actually used
  - `all` – show handwriting/line/fallback together

## Knowledge Base Matching
- Match by normalized answer, english text, and/or zh_hint.
- Fuzzy match allowed for longer strings.
- Display per item whether it hit the KB and the matched term.

## UI – Submit & Grade
- AI‑only flow; no manual fallback.
- User selects photos → previews thumbnails.
- User can add/remove photos before analysis.
- After AI extraction, UI shows:
  - question number, prompt (zh_hint), LLM recognized text
  - LLM text displays in red when inconsistent with OCR
  - correctness toggle (green check / red cross)
  - include toggle (whether to store)
  - confidence level
  - notes
  - crop thumbnail of recognized handwriting (click to zoom)
- Clicking any thumbnail or graded image opens a zoomed image modal (ESC or click to close).
- Removed columns: OCR recognition, source selection, manual input (simplified to LLM-only).

## UI Improvements (2025-12-31)

**OCR Merge Logic**:
- Single-word questions: very strict threshold (0.1) to prevent merging
- Multi-word questions (phrases/sentences): moderate threshold (0.5) for limited merging
- Configurable via `EL_OCR_WORD_MERGE_THRESHOLD` and `EL_OCR_PHRASE_MERGE_THRESHOLD`

**Table Columns**:
- Removed: "OCR识别", "采信", "手动输入"
- Added: "识别图片" with crop thumbnails
- LLM text shown in red (#e5484d) when inconsistent with OCR

**Crop Thumbnails**:
- Generated client-side using Canvas from uploaded images
- Click to zoom (modal view)
- ESC key or click to close modal

## Files & Storage
- Media root: `backend/media/`
- Uploads: `backend/media/uploads/`
- Crops: `backend/media/uploads/crops/`
- Debug overlays: `backend/media/uploads/debug/`

## Non‑Goals / Removed
- Local OCR / OpenCV grading fallback is disabled.
- Manual entry grading removed from UI (AI‑only flow).

## Notes
- `.env` is loaded at app startup.
- Use `.env.example` as template for env keys.

## OCR-LLM Matching Improvements (2025-12-31)

### Problems Identified

**Problem 1: OCR lines incorrectly merged**
- `_build_ocr_lines()` merges separate handwritten answers into a single line when vertically close
- Example: Questions 13 (猪/pig) and 14 (马/horse) merged into `'13.猪: Pig horse'`
- Root cause: Merging threshold (`line_h * 0.6`) too loose, combines print+handwriting
- Impact: Wrong answers assigned to questions, incorrect display

**Problem 2: Sequential matching fails with unanswered questions**
- LLM detects all questions (24 items, including empty answers)
- OCR only detects handwritten answers (14 items)
- Sequential fallback causes misalignment after skipped questions

### Solutions Implemented

**Solution 1: Separate handwriting from print in line building**
- Build separate line lists for handwriting vs print text
- Only merge within same type
- Use stricter threshold (0.4) for handwriting to prevent merging separate answers

**Solution 2: Position-based matching using question numbers**
- Extract question numbers from OCR print text (e.g., "13.猪:" → Q13)
- Match using 3-strategy priority:
  1. Text similarity (ratio ≥ 0.6) - highest priority
  2. Position-based (OCR answer closest to question position) - medium priority
  3. Sequential fallback - lowest priority
- Correctly handles unanswered questions (empty LLM text → no OCR match)

**Solution 3: Question position extraction**
- Parse question numbers from print text using regex `r'^(\d+)[\s.．。]'`
- Build question number → position map for position-based matching

### Configuration

```bash
EL_OCR_HANDWRITING_MERGE_THRESHOLD=0.4  # Merge threshold for handwriting (default 0.4)
```

### Expected Behavior After Fix

- Pig and horse are separate OCR lines (not merged)
- Q13 correctly matches "Pig" via position (near "13.猪:")
- Q14 correctly matches "horse" via position (near "14.马:")
- Unanswered questions (Q6, Q16-Q24) have no OCR match, remain empty
