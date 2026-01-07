#!/usr/bin/env python3
"""
数据库迁移：为student_item_stats表添加consecutive_correct字段
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "el.db"


def migrate():
    """添加consecutive_correct字段到student_item_stats表"""
    if not DB_PATH.exists():
        print("❌ 数据库不存在")
        return False

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # 检查字段是否已存在
        cursor.execute("PRAGMA table_info(student_item_stats)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'consecutive_correct' in columns:
            print("✅ consecutive_correct字段已存在，无需迁移")
            return True

        # 添加consecutive_correct字段
        print("📦 添加consecutive_correct字段到student_item_stats表...")
        cursor.execute("""
            ALTER TABLE student_item_stats
            ADD COLUMN consecutive_correct INTEGER DEFAULT 0
        """)

        conn.commit()
        print("✅ 迁移成功！consecutive_correct字段已添加")
        return True

    except Exception as e:
        print(f"❌ 迁移失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


if __name__ == '__main__':
    print("=" * 60)
    print("数据库迁移：添加consecutive_correct字段")
    print("=" * 60)
    print()

    migrate()

    print()
    print("=" * 60)
    print("完成！")
    print("=" * 60)
