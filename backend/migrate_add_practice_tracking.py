#!/usr/bin/env python3
"""
数据库迁移：添加练习单持久化追踪字段

添加字段：
- practice_uuid: 练习单唯一编号（格式：ES-0001-ABC123）
- downloaded_at: PDF下载时间戳（NULL表示未下载，只保存已下载的练习单）
- created_date: 创建日期（YYYY-MM-DD格式，便于按日期查询）

索引：
- practice_uuid: 用于通过编号快速查询
- student_id + created_date: 用于按学生和日期查询
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
        # Check if columns already exist
        cursor.execute("PRAGMA table_info(practice_sessions)")
        columns = [col[1] for col in cursor.fetchall()]

        # Add practice_uuid column
        if 'practice_uuid' not in columns:
            print("Adding practice_uuid column...")
            cursor.execute("""
                ALTER TABLE practice_sessions
                ADD COLUMN practice_uuid TEXT
            """)
            print("✓ Added practice_uuid column")
        else:
            print("✓ practice_uuid column already exists")

        # Add downloaded_at column
        if 'downloaded_at' not in columns:
            print("Adding downloaded_at column...")
            cursor.execute("""
                ALTER TABLE practice_sessions
                ADD COLUMN downloaded_at TIMESTAMP
            """)
            print("✓ Added downloaded_at column")
        else:
            print("✓ downloaded_at column already exists")

        # Add created_date column (for easier date-based queries)
        if 'created_date' not in columns:
            print("Adding created_date column...")
            cursor.execute("""
                ALTER TABLE practice_sessions
                ADD COLUMN created_date TEXT
            """)

            # Populate created_date from created_at for existing records
            print("Populating created_date from existing created_at values...")
            cursor.execute("""
                UPDATE practice_sessions
                SET created_date = substr(created_at, 1, 10)
                WHERE created_date IS NULL AND created_at IS NOT NULL
            """)
            print("✓ Added and populated created_date column")
        else:
            print("✓ created_date column already exists")

        # Create index on practice_uuid for fast UUID lookup
        print("Creating index on practice_uuid...")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_practice_uuid
            ON practice_sessions(practice_uuid)
        """)
        print("✓ Created index on practice_uuid")

        # Create composite index on student_id + created_date
        print("Creating index on student_id + created_date...")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_student_date
            ON practice_sessions(student_id, created_date)
        """)
        print("✓ Created index on student_id + created_date")

        conn.commit()
        print("\n✅ Migration completed successfully!")

        # Show statistics
        cursor.execute("SELECT COUNT(*) FROM practice_sessions")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM practice_sessions WHERE practice_uuid IS NOT NULL")
        with_uuid = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM practice_sessions WHERE downloaded_at IS NOT NULL")
        downloaded = cursor.fetchone()[0]

        print(f"\n📊 Statistics:")
        print(f"  Total sessions: {total}")
        print(f"  With UUID: {with_uuid}")
        print(f"  Downloaded: {downloaded}")

    except Exception as e:
        conn.rollback()
        print(f"\n❌ Migration failed: {e}")
        raise
    finally:
        conn.close()

if __name__ == '__main__':
    migrate()
