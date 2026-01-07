#!/usr/bin/env python3
"""
数据库迁移：添加 editor 字段到 bases 表
"""
import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "el.db")

def migrate():
    """添加 editor 字段"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # 检查字段是否已存在
        cursor.execute("PRAGMA table_info(bases)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'editor' not in columns:
            print("添加 editor 字段...")
            cursor.execute("""
                ALTER TABLE bases
                ADD COLUMN editor TEXT
            """)
            conn.commit()
            print("✓ 迁移完成: 已添加 editor 字段")
        else:
            print("⚠ editor 字段已存在，跳过迁移")

    except Exception as e:
        print(f"✗ 迁移失败: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
