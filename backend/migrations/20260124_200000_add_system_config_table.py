#!/usr/bin/env python3
"""
测试迁移：添加系统配置表

用于测试迁移系统功能
"""

import sqlite3


def migrate(conn: sqlite3.Connection):
    """执行迁移：添加系统配置表"""
    cursor = conn.cursor()

    # 创建系统配置表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS system_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            config_key TEXT NOT NULL UNIQUE,
            config_value TEXT,
            description TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 创建索引
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_system_config_key
        ON system_config(config_key)
    """)

    # 插入默认配置
    cursor.execute("""
        INSERT OR IGNORE INTO system_config (config_key, config_value, description)
        VALUES
            ('app_version', '1.0.0', '应用版本'),
            ('migration_enabled', '1', '是否启用数据库迁移'),
            ('last_upgrade_check', '', '最后检查更新时间')
    """)

    conn.commit()
    print("✅ 已创建 system_config 表并插入默认配置")


if __name__ == '__main__':
    import os
    from pathlib import Path

    db_path = Path(__file__).parent.parent / "el.db"

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
