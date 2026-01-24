#!/usr/bin/env python3
"""
迁移脚本模板

文件命名规范: YYYYMMDD_HHMMSS_description.py
例如: 20260124_150000_add_upgrade_log_table.py

每个迁移脚本必须包含 migrate(conn) 函数
"""

import sqlite3


def migrate(conn: sqlite3.Connection):
    """
    执行迁移

    Args:
        conn: 数据库连接对象

    注意:
    - 迁移脚本应该是幂等的（可以重复执行而不出错）
    - 使用 IF NOT EXISTS 等条件语句
    - 迁移失败会抛出异常，自动回滚
    """
    cursor = conn.cursor()

    # 示例：添加新表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS example_table (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 示例：添加新列
    try:
        cursor.execute("""
            ALTER TABLE existing_table
            ADD COLUMN new_column TEXT
        """)
    except sqlite3.OperationalError as e:
        # 列可能已存在，忽略错误
        if "duplicate column name" not in str(e).lower():
            raise

    # 示例：创建索引
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_example_name
        ON example_table(name)
    """)

    # 示例：数据迁移
    cursor.execute("""
        UPDATE existing_table
        SET new_column = 'default_value'
        WHERE new_column IS NULL
    """)

    conn.commit()


if __name__ == '__main__':
    # 用于测试迁移脚本
    import os
    from pathlib import Path

    db_path = Path(__file__).parent.parent / "data" / "el.db"

    if not db_path.exists():
        print(f"数据库不存在: {db_path}")
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
