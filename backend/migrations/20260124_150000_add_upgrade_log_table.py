#!/usr/bin/env python3
"""
添加升级日志表

用于记录系统升级历史
"""

import sqlite3


def migrate(conn: sqlite3.Connection):
    """执行迁移：添加升级日志表"""
    cursor = conn.cursor()

    # 创建升级日志表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS upgrade_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version_from TEXT,
            version_to TEXT NOT NULL,
            upgrade_type TEXT NOT NULL DEFAULT 'git_pull',
            started_at TEXT NOT NULL,
            completed_at TEXT,
            status TEXT NOT NULL DEFAULT 'running',
            error_message TEXT,
            backup_file TEXT,
            pip_installed INTEGER DEFAULT 0,
            service_restarted INTEGER DEFAULT 0,
            duration_seconds INTEGER,
            triggered_by TEXT DEFAULT 'web',
            notes TEXT
        )
    """)

    # 创建索引
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_upgrade_logs_started_at
        ON upgrade_logs(started_at DESC)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_upgrade_logs_status
        ON upgrade_logs(status)
    """)

    conn.commit()
    print("✅ 已创建 upgrade_logs 表")


if __name__ == '__main__':
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
