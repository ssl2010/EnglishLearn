#!/usr/bin/env python3
"""
数据库迁移: 添加 difficulty_tag 字段到 items 表

要求项目字段用于标记学习要求：
- "write": 会写（需要能够默写）
- "read": 会认（只需要能认识）
- NULL: 未设置
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "el.db")


def migrate():
    """添加 difficulty_tag 字段"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # Check if column already exists
        cursor.execute("PRAGMA table_info(items)")
        columns = [row[1] for row in cursor.fetchall()]

        if 'difficulty_tag' in columns:
            print("✓ difficulty_tag 字段已存在，无需迁移")
            return

        print("开始迁移: 添加 difficulty_tag 字段到 items 表...")

        # Add difficulty_tag column
        cursor.execute("""
            ALTER TABLE items
            ADD COLUMN difficulty_tag TEXT
        """)

        conn.commit()
        print("✓ 迁移完成: 已添加 difficulty_tag 字段")

        # Show statistics
        cursor.execute("SELECT COUNT(*) FROM items")
        total_items = cursor.fetchone()[0]
        print(f"  总词条数: {total_items}")
        print(f"  新字段默认值: NULL (未设置)")

    except Exception as e:
        conn.rollback()
        print(f"✗ 迁移失败: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
