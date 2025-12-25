import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

DB_PATH = os.environ.get(
    "EL_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "data.db"),
)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db() -> Iterable[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS students (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL,
              grade_code TEXT NOT NULL,
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS knowledge_bases (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL,
              grade_code TEXT NOT NULL,
              is_system INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS student_base_progress (
              student_id INTEGER NOT NULL,
              base_id INTEGER NOT NULL,
              current_unit_code TEXT,
              PRIMARY KEY (student_id, base_id),
              FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE,
              FOREIGN KEY(base_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS knowledge_items (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              base_id INTEGER NOT NULL,
              unit_code TEXT,
              type TEXT NOT NULL CHECK(type IN ('WORD','PHRASE','SENTENCE','GRAMMAR')),
              en_text TEXT NOT NULL,
              zh_hint TEXT,
              difficulty_tag TEXT NOT NULL CHECK(difficulty_tag IN ('write','recognize')),
              normalized_answer TEXT NOT NULL,
              is_enabled INTEGER NOT NULL DEFAULT 1,
              source TEXT NOT NULL DEFAULT 'IMPORT',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE(base_id, unit_code, type, en_text),
              FOREIGN KEY(base_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS practice_sessions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              student_id INTEGER NOT NULL,
              base_id INTEGER NOT NULL,
              status TEXT NOT NULL CHECK(status IN ('DRAFT','PUBLISHED','COMPLETED','CORRECTED','ARCHIVED')),
              params_json TEXT NOT NULL,
              pdf_path TEXT,
              answer_pdf_path TEXT,
              created_at TEXT NOT NULL,
              published_at TEXT,
              completed_at TEXT,
              corrected_at TEXT,
              archived_at TEXT,
              FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE,
              FOREIGN KEY(base_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS exercise_items (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              session_id INTEGER NOT NULL,
              item_id INTEGER,
              position INTEGER NOT NULL,
              type TEXT NOT NULL,
              en_text TEXT NOT NULL,
              zh_hint TEXT,
              normalized_answer TEXT NOT NULL,
              FOREIGN KEY(session_id) REFERENCES practice_sessions(id) ON DELETE CASCADE,
              FOREIGN KEY(item_id) REFERENCES knowledge_items(id) ON DELETE SET NULL,
              UNIQUE(session_id, position)
            );

            CREATE TABLE IF NOT EXISTS submissions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              session_id INTEGER NOT NULL,
              submitted_at TEXT NOT NULL,
              image_path TEXT,
              text_raw TEXT,
              source TEXT NOT NULL DEFAULT 'PHOTO',
              FOREIGN KEY(session_id) REFERENCES practice_sessions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS practice_results (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              submission_id INTEGER NOT NULL,
              session_id INTEGER NOT NULL,
              exercise_item_id INTEGER NOT NULL,
              answer_raw TEXT,
              answer_norm TEXT,
              is_correct INTEGER NOT NULL,
              error_type TEXT NOT NULL,
              created_at TEXT NOT NULL,
              FOREIGN KEY(submission_id) REFERENCES submissions(id) ON DELETE CASCADE,
              FOREIGN KEY(session_id) REFERENCES practice_sessions(id) ON DELETE CASCADE,
              FOREIGN KEY(exercise_item_id) REFERENCES exercise_items(id) ON DELETE CASCADE
            );


            CREATE TABLE IF NOT EXISTS system_settings (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS student_item_stats (
              student_id INTEGER NOT NULL,
              item_id INTEGER NOT NULL,
              total_attempts INTEGER NOT NULL DEFAULT 0,
              correct_attempts INTEGER NOT NULL DEFAULT 0,
              wrong_attempts INTEGER NOT NULL DEFAULT 0,
              consecutive_correct INTEGER NOT NULL DEFAULT 0,
              consecutive_wrong INTEGER NOT NULL DEFAULT 0,
              last_attempt_at TEXT,
              PRIMARY KEY(student_id, item_id),
              FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE,
              FOREIGN KEY(item_id) REFERENCES knowledge_items(id) ON DELETE CASCADE
            );
            """
        )

        # default settings (can be changed later)
        conn.execute(
            "INSERT OR IGNORE INTO system_settings(key, value, updated_at) VALUES(?,?,?)",
            ("mastery_threshold", "2", utcnow_iso()),
        )
        conn.execute(
            "INSERT OR IGNORE INTO system_settings(key, value, updated_at) VALUES(?,?,?)",
            ("weekly_target_days", "4", utcnow_iso()),
        )


def qone(conn: sqlite3.Connection, sql: str, args: Tuple[Any, ...] = ()) -> Optional[sqlite3.Row]:
    cur = conn.execute(sql, args)
    return cur.fetchone()


def qall(conn: sqlite3.Connection, sql: str, args: Tuple[Any, ...] = ()) -> List[sqlite3.Row]:
    cur = conn.execute(sql, args)
    return cur.fetchall()


def exec1(conn: sqlite3.Connection, sql: str, args: Tuple[Any, ...] = ()) -> int:
    cur = conn.execute(sql, args)
    return cur.lastrowid


def to_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def from_json(s: str) -> Any:
    return json.loads(s)
