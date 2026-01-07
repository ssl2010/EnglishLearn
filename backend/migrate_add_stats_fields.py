#!/usr/bin/env python3
"""
数据库迁移：为student_item_stats表添加total_attempts和correct_attempts字段
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "el.db"


def migrate():
    """添加缺失字段到student_item_stats表"""
    if not DB_PATH.exists():
        print("❌ 数据库不存在")
        return False

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # 检查字段是否已存在
        cursor.execute("PRAGMA table_info(student_item_stats)")
        columns = [col[1] for col in cursor.fetchall()]

        fields_to_add = []
        if 'total_attempts' not in columns:
            fields_to_add.append(('total_attempts', 'INTEGER DEFAULT 0'))
        if 'correct_attempts' not in columns:
            fields_to_add.append(('correct_attempts', 'INTEGER DEFAULT 0'))

        if not fields_to_add:
            print("✅ 所有字段已存在，无需迁移")
            return True

        # 添加缺失的字段
        for field_name, field_def in fields_to_add:
            print(f"📦 添加{field_name}字段到student_item_stats表...")
            cursor.execute(f"""
                ALTER TABLE student_item_stats
                ADD COLUMN {field_name} {field_def}
            """)

        conn.commit()
        print(f"✅ 迁移成功！已添加 {len(fields_to_add)} 个字段")
        return True

    except Exception as e:
        print(f"❌ 迁移失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


if __name__ == '__main__':
    print("=" * 60)
    print("数据库迁移：添加total_attempts和correct_attempts字段")
    print("=" * 60)
    print()

    migrate()

    print()
    print("=" * 60)
    print("完成！")
    print("=" * 60)
