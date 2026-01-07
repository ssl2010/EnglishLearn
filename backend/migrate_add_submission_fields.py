#!/usr/bin/env python3
"""
数据库迁移：为 submissions 表添加缺失字段

添加字段：
- image_path: 上传图片路径
- text_raw: 原始文本数据
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
        cursor.execute("PRAGMA table_info(submissions)")
        columns = [col[1] for col in cursor.fetchall()]

        # Add image_path column
        if 'image_path' not in columns:
            print("Adding image_path column...")
            cursor.execute("""
                ALTER TABLE submissions
                ADD COLUMN image_path TEXT
            """)
            print("✓ Added image_path column")
        else:
            print("✓ image_path column already exists")

        # Add text_raw column
        if 'text_raw' not in columns:
            print("Adding text_raw column...")
            cursor.execute("""
                ALTER TABLE submissions
                ADD COLUMN text_raw TEXT
            """)
            print("✓ Added text_raw column")
        else:
            print("✓ text_raw column already exists")

        conn.commit()
        print("\n✅ Migration completed successfully!")

        # Show statistics
        cursor.execute("SELECT COUNT(*) FROM submissions")
        total = cursor.fetchone()[0]

        print(f"\n📊 Statistics:")
        print(f"  Total submissions: {total}")

    except Exception as e:
        conn.rollback()
        print(f"\n❌ Migration failed: {e}")
        raise
    finally:
        conn.close()

if __name__ == '__main__':
    migrate()
