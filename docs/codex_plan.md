# Codex Refactor Plan (DB raw/file storage + practice_uuid-centric APIs)

Branch: `feat/ai-raw-db-migration`

## Phase / PR breakdown

1. **PR-1 (foundation)**
   - DB migration: `practice_ai_artifacts`, `practice_files`
   - schema.sql update
   - `docs/arch_survey.md`

2. **PR-2 (DAO/service)**
   - `save_ai_artifact`, `save_practice_file`
   - list/get helpers for files/artifacts
   - best-effort AI raw dual-write to DB

3. **PR-3 (API)**
   - `POST/GET /api/practice/{practice_uuid}/files`
   - `GET /api/files/{file_uuid}`
   - `GET /api/practice/{practice_uuid}/artifacts`
   - `GET /api/practice/{practice_uuid}/artifacts/latest`

4. **PR-4 (replace upload/raw filesystem writes)**
   - AI source upload path -> DB (`practice_files`)
   - raw bundle writes -> DB-first artifacts
   - keep controlled compatibility mode during transition
   - Status: **implemented in branch (DB-first default; filesystem compatibility flags retained)**

5. **PR-5 (OCR/LLM DB->tempfile adaptation)**
   - engine adapters accept temp files from `practice_files`
   - cleanup temp files

6. **PR-6 (ID convergence)**
   - practice_uuid-first APIs for detail/submit/correct/view
   - legacy `session_id` routes remain compatibility wrappers
   - Status: **partially implemented** (key practice detail/submit/correct/delete/regenerate routes added)

7. **PR-7 (historical migration + reports)**
   - `scripts/migrate_raw_to_db.py`
   - `scripts/migrate_upload_images_to_db.py`
   - dry-run and audit jsonl verification

## Validation checklist per phase

- Run Python syntax checks (`ast.parse`) on touched backend files
- Run migration manager on a backup DB first
- Verify new APIs with authenticated session
- Confirm no blob leakage in list endpoints (download endpoint only)

## Rollback notes

- DB migration rollback is additive (new tables only); old paths remain available
- Runtime rollout should initially be dual-write before disabling filesystem writes
- Current branch defaults:
  - `EL_AI_BUNDLE_SAVE=0` (filesystem AI raw bundle persistence disabled unless explicitly enabled)
  - `EL_SAVE_AI_UPLOAD_FILES=0` (filesystem AI source uploads disabled unless explicitly enabled)
- Merge back to `main` only after:
  - migration scripts dry-run + sample live migration
  - new API smoke tests
  - legacy flows regression tests
