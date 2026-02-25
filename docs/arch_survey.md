# Architecture Survey (Codex)

Generated on branch `feat/ai-raw-db-migration` for the DB raw/file storage refactor.

## 1. Backend framework & DB

- Backend framework: `FastAPI` (`backend/app/main.py`)
- DB access: built-in `sqlite3` via `backend/app/db.py` (`EL_DB_PATH`, default `backend/el.db`)
- Migration mechanism:
  - ad-hoc scripts under `backend/migrate_*.py`
  - managed migrations under `backend/migrations/*.py` via `backend/migration_manager.py`

## 2. Practice entity & IDs

- Core table: `practice_sessions` in `backend/schema.sql`
- Business UUID field: `practice_sessions.practice_uuid` (`TEXT`, indexed, currently not UNIQUE)
- Internal relational PK: `practice_sessions.id` (widely used as `session_id`)
- Current auxiliary AI ID: `bundle_id` stored in `submissions.text_raw` JSON (`$.bundle_id`) and used to locate `data/media/uploads/ai_bundles/<bundle_id>/`

## 3. Upload image persistence (current)

- API entry points:
  - `POST /api/practice-sessions/{session_id}/submit-image` -> `upload_submission_image()` in `backend/app/services.py`
  - `POST /api/ai/grade-photos` -> `analyze_ai_photos()` in `backend/app/services.py`
- Current persistence paths:
  - user uploads / AI source images: `MEDIA_DIR/uploads/`
  - graded images: `MEDIA_DIR/uploads/graded/`
  - optional crops: `MEDIA_DIR/uploads/crops/`

## 4. LLM/OCR raw persistence (current)

- Current raw bundle save path:
  - `MEDIA_DIR/uploads/ai_bundles/<bundle_id>/llm_raw.json`
  - `MEDIA_DIR/uploads/ai_bundles/<bundle_id>/ocr_raw.json`
  - `MEDIA_DIR/uploads/ai_bundles/<bundle_id>/meta.json`
- Save call sites:
  - `analyze_ai_photos()` -> `_save_ai_bundle(...)`
  - `analyze_ai_photos_from_debug()` -> `_save_ai_bundle(...)`
- Debug overwrite path:
  - `MEDIA_DIR/uploads/debug_last/` via `_save_debug_bundle(...)`

## 5. ID flow hotspots (to refactor)

- `session_id` still dominates route handlers and relational joins
- `practice_uuid` already exists and is queryable (`/api/practice-sessions/by-uuid/{practice_uuid}`)
- `bundle_id` is still required for:
  - linking a specific AI analysis result (raw/meta/images) to a submission
  - pre-confirm flows where `practice_uuid` may be missing or unresolved

## 6. Initial refactor actions completed in this branch

- Added DB tables (schema + migration) for:
  - `practice_ai_artifacts`
  - `practice_files`
- Added DAO/service module `backend/app/practice_storage.py`
- Added practice_uuid-driven APIs for files/artifacts in `backend/app/main.py`
- Added best-effort dual-write of AI raw (`llm_raw`/`ocr_raw`) into DB in `analyze_ai_photos*()`

## 7. Remaining major work (not yet complete)

- Replace existing upload image filesystem writes with DB-first storage (`practice_files`)
- Replace filesystem raw bundle dependency in all readers with DB-first artifacts retrieval
- Full `practice_uuid` route convergence across legacy `session_id` flows
- Historical migration execution and validation
