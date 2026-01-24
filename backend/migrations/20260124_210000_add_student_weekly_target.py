#!/usr/bin/env python3
"""
为学生表添加周练习目标字段

允许为每个学生单独设置周练习目标天数（1-7天）
NULL表示使用系统全局默认值
"""

import sqlite3


def migrate(conn: sqlite3.Connection):
    """
    执行迁移

    添加 students.weekly_target_days 字段
    """
    cursor = conn.cursor()

    # 添加周练习目标字段
    try:
        cursor.execute("""
            ALTER TABLE students
            ADD COLUMN weekly_target_days INTEGER
        """)
    except sqlite3.OperationalError as e:
        # 列可能已存在，忽略错误
        if "duplicate column name" not in str(e).lower():
            raise

    conn.commit()


if __name__ == '__main__':
    # 用于测试迁移脚本
    import os
    from pathlib import Path

    # 尝试多个可能的数据库路径
    possible_paths = [
        Path(__file__).parent.parent / "el.db",
        Path(__file__).parent.parent / "app" / "el.db",
        Path(__file__).parent.parent / "data" / "el.db",
    ]

    db_path = None
    for path in possible_paths:
        if path.exists():
            db_path = path
            break

    if not db_path:
        print(f"数据库不存在，尝试的路径：")
        for path in possible_paths:
            print(f"  - {path}")
        exit(1)

    print(f"测试迁移: {db_path}")

    conn = sqlite3.connect(str(db_path))
    try:
        migrate(conn)
        print("✅ 迁移测试成功")
    except Exception as e:
        print(f"❌ 迁移测试失败: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()
