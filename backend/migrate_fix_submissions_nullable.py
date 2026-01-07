#!/usr/bin/env python3
"""
数据库迁移：修复 submissions 表字段约束

问题：item_id 和 position 字段被设置为 NOT NULL，
但实际使用中一个 submission 可能对应整个 session（多个items），
而不是单个 item。

解决方案：允许这些字段为 NULL
"""

import sqlite3
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

from app.db import DB_PATH

def migrate():
    db_path = DB_PATH
    print(f"Migrating database: {db_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        print("Recreating submissions table with nullable item_id and position...")

        # Step 1: Create new table with correct schema
        cursor.execute("""
            CREATE TABLE submissions_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                item_id INTEGER,  -- Now nullable
                position INTEGER,  -- Now nullable
                student_text TEXT,
                is_correct BOOLEAN,
                llm_text TEXT,
                ocr_text TEXT,
                source TEXT DEFAULT 'manual',
                submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                image_path TEXT,
                text_raw TEXT,
                FOREIGN KEY (session_id) REFERENCES practice_sessions(id)
            )
        """)

        # Step 2: Copy data from old table
        cursor.execute("""
            INSERT INTO submissions_new
            SELECT * FROM submissions
        """)

        # Step 3: Drop old table
        cursor.execute("DROP TABLE submissions")

        # Step 4: Rename new table
        cursor.execute("ALTER TABLE submissions_new RENAME TO submissions")

        # Step 5: Recreate indexes if any
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_submissions_session
            ON submissions(session_id)
        """)

        conn.commit()
        print("✓ Recreated submissions table with nullable constraints")

        # Show statistics
        cursor.execute("SELECT COUNT(*) FROM submissions")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM submissions WHERE item_id IS NULL")
        null_items = cursor.fetchone()[0]

        print(f"\n✅ Migration completed successfully!")
        print(f"\n📊 Statistics:")
        print(f"  Total submissions: {total}")
        print(f"  With NULL item_id: {null_items}")

    except Exception as e:
        conn.rollback()
        print(f"\n❌ Migration failed: {e}")
        raise
    finally:
        conn.close()

if __name__ == '__main__':
    migrate()
