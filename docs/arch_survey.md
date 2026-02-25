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

## 5. ID flow hotspots and necessity analysis

- `practice_uuid` (business-global ID)
  - Should be the primary ID for frontend routes, APIs, logs, and migration scripts
  - Stable across repeated submissions of the same worksheet
  - Already present in `practice_sessions.practice_uuid`, but not yet unique-constrained in DB
- `session_id` (internal relational PK)
  - Still necessary internally because core tables (`exercise_items`, `submissions`, `practice_results`) are joined by `session_id`
  - Removing it would require large schema rewrites and data backfill across multiple tables
  - Refactor direction: keep as internal PK, expose `practice_uuid` in public APIs and use wrappers for legacy routes
- `bundle_id` (AI analysis transaction ID)
  - Necessary before confirm/in库阶段 to identify one specific AI analysis run (raw/meta/source images)
  - One `practice_uuid` can have multiple AI analyses/submissions; `bundle_id` distinguishes each analysis snapshot
  - Refactor direction: keep `bundle_id` as per-analysis ID, but persist artifacts/files under `practice_uuid` and map by `bundle_id`

## 6. Refactor actions completed in this branch (current)

- Added DB tables (schema + migration) for:
  - `practice_ai_artifacts`
  - `practice_files`
- Added DAO/service module `backend/app/practice_storage.py`
- Added practice_uuid-driven APIs for files/artifacts in `backend/app/main.py`
- Added best-effort dual-write of AI raw (`llm_raw`/`ocr_raw`) into DB in `analyze_ai_photos*()`
- Added DB-first bundle meta lookup (`bundle_id -> practice_ai_artifacts`) with filesystem fallback
- Switched AI source image persistence in `analyze_ai_photos()` to DB-first (`practice_files`) by default
- Switched manual submit image upload (`upload_submission_image`) to DB blob storage (`practice_files`)
- Added `practice_uuid` wrappers for detail / regenerate-pdf / submit-image / submit-marked-photo / manual-correct / delete
- Updated frontend `practice-view`/`practice`/`dashboard` to prefer `practice_uuid`

## 7. Remaining major work (not yet complete)

- Convert AI debug raw bundle persistence (`debug_last`) from persistent project directory to temp/retention-safe workflow (if strict debug-mode policy is required)
- Decide whether to add a UNIQUE constraint for `practice_sessions.practice_uuid` after auditing historical duplicates
- Extend DB-backed storage to more media types (e.g., graded images) if desired
- Execute historical migration scripts and validate on production-like data
