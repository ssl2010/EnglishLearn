# Claude Code Guide

## How to run
- Backend:
  - Create venv (optional) and install deps: `pip install -r backend/requirements.txt`
  - Run dev server: `uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000`
- Frontend:
  - Static HTML served by backend at `/` (no separate build step)

## How to test
- No automated tests configured. Use manual flows:
  - Generate practice session at `/generate.html`
  - Submit grading at `/submit.html`

## How to format/lint
- No formatter/linter configured.
- Keep code style consistent with existing files.

## Do not modify
- `generated/`
- `third_party/`

## PR / commit conventions
- Keep commits small and focused.
- Use present tense in commit messages.
- Include a short summary and a concise body when changes are non-trivial.

## Notes
- Env config is loaded from `.env` (see `.env.example` for template).
- Media files are written to `backend/media/`.
