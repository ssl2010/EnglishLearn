#!/usr/bin/env python3
"""
数据库迁移脚本：创建units表存储单元元数据

新增表：
- units表：存储base的单元信息（unit_code, unit_name等）
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "el.db"


def migrate():
    """执行迁移"""
    if not DB_PATH.exists():
        print(f"❌ 数据库不存在: {DB_PATH}")
        print("   请先运行 init_db.py 创建数据库")
        return False

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # 检查表是否已存在
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='units'")
        if cursor.fetchone():
            print("⏭️  units表已存在，跳过创建")
            return True

        # 创建units表
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS units (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            base_id INTEGER NOT NULL,
            unit_code TEXT NOT NULL,
            unit_name TEXT,
            unit_index INTEGER,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (base_id) REFERENCES bases(id) ON DELETE CASCADE,
            UNIQUE(base_id, unit_code)
        )
        """
        cursor.execute(create_table_sql)

        # 创建索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_units_base ON units(base_id)")

        conn.commit()
        print("✅ 创建units表成功")
        print("✅ 创建索引成功")
        return True

    except Exception as e:
        print(f"❌ 迁移失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


if __name__ == '__main__':
    print("=" * 60)
    print("数据库迁移：创建units表")
    print("=" * 60)
    print()

    if migrate():
        print()
        print("=" * 60)
        print("✅ 迁移成功！")
        print("=" * 60)
    else:
        print()
        print("=" * 60)
        print("❌ 迁移失败")
        print("=" * 60)
