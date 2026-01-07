#!/usr/bin/env python3
"""
数据库迁移：移除students表的term字段
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "el.db"


def migrate():
    """移除term字段从students表"""
    if not DB_PATH.exists():
        print("❌ 数据库不存在，请先运行 init_db.py")
        return False

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # 检查term字段是否存在
        cursor.execute("PRAGMA table_info(students)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'term' not in columns:
            print("✅ term字段不存在，无需迁移")
            return True

        print("📦 从students表移除term字段...")

        # SQLite不支持直接DROP COLUMN，需要重建表
        # 1. 创建新表（不含term字段）
        cursor.execute("""
            CREATE TABLE students_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                grade TEXT,
                avatar TEXT DEFAULT 'rabbit',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 2. 复制数据（排除term字段）
        cursor.execute("""
            INSERT INTO students_new (id, name, grade, avatar, created_at, updated_at)
            SELECT id, name, grade, avatar, created_at, updated_at
            FROM students
        """)

        # 3. 删除旧表
        cursor.execute("DROP TABLE students")

        # 4. 重命名新表
        cursor.execute("ALTER TABLE students_new RENAME TO students")

        conn.commit()
        print("✅ 迁移成功！term字段已移除")
        return True

    except Exception as e:
        print(f"❌ 迁移失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


if __name__ == '__main__':
    print("=" * 60)
    print("数据库迁移：移除学生学期字段")
    print("=" * 60)
    print()

    migrate()

    print()
    print("=" * 60)
    print("完成！")
    print("=" * 60)
