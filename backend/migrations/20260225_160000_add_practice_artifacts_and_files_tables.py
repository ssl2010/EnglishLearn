#!/usr/bin/env python3
import sqlite3


def migrate(conn: sqlite3.Connection):
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS practice_ai_artifacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            practice_uuid TEXT NOT NULL,
            engine TEXT NOT NULL,
            stage TEXT NOT NULL,
            content_type TEXT NOT NULL,
            content_text TEXT,
            content_json TEXT,
            meta_json TEXT,
            source_path TEXT,
            sha256 TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS practice_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            practice_uuid TEXT NOT NULL,
            file_uuid TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL,
            mime_type TEXT NOT NULL,
            original_filename TEXT,
            byte_size INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            width INTEGER,
            height INTEGER,
            meta_json TEXT,
            content_blob BLOB NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_artifacts_practice ON practice_ai_artifacts(practice_uuid)")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_artifacts_lookup ON practice_ai_artifacts(practice_uuid, engine, stage, created_at)"
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_files_practice ON practice_files(practice_uuid)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_files_sha ON practice_files(sha256)")

    conn.commit()


if __name__ == "__main__":
    import os
    db_path = os.path.join(os.path.dirname(__file__), "..", "el.db")
    conn = sqlite3.connect(db_path)
    try:
        migrate(conn)
        print("ok")
    finally:
        conn.close()
