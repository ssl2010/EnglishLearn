#!/usr/bin/env python3
"""
数据库迁移：为students表添加avatar字段
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "el.db"


def migrate():
    """添加avatar字段到students表"""
    if not DB_PATH.exists():
        print("❌ 数据库不存在，请先运行 init_db.py")
        return False

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # 检查avatar字段是否已存在
        cursor.execute("PRAGMA table_info(students)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'avatar' in columns:
            print("✅ avatar字段已存在，无需迁移")
            return True

        # 添加avatar字段
        print("📦 添加avatar字段到students表...")
        cursor.execute("""
            ALTER TABLE students
            ADD COLUMN avatar TEXT DEFAULT 'rabbit'
        """)

        conn.commit()
        print("✅ 迁移成功！avatar字段已添加")
        return True

    except Exception as e:
        print(f"❌ 迁移失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


if __name__ == '__main__':
    print("=" * 60)
    print("数据库迁移：添加avatar字段")
    print("=" * 60)
    print()

    migrate()

    print()
    print("=" * 60)
    print("完成！")
    print("=" * 60)
