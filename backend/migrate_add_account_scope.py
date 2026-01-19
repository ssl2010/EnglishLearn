#!/usr/bin/env python3
import argparse
import os
import shutil
import sqlite3
from datetime import datetime


DEFAULT_DB = os.path.join(os.path.dirname(__file__), "el.db")


def backup_db(path: str) -> str:
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{path}.bak.{timestamp}"
    shutil.copy2(path, backup_path)
    return backup_path


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def _column_exists(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(row[1] == column_name for row in rows)


def _get_default_account_id(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT id FROM accounts ORDER BY id ASC LIMIT 1").fetchone()
    if not row:
        raise RuntimeError(
            "accounts 为空，请先设置 EL_ADMIN_PASS 启动服务创建管理员账号后再迁移。"
        )
    return int(row[0])


def migrate(db_path: str) -> None:
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"DB not found: {db_path}")

    backup_path = backup_db(db_path)
    print(f"✅ Backup created: {backup_path}")

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")

        if not _table_exists(conn, "accounts"):
            raise RuntimeError("accounts 表不存在，请先运行 migrate_auth.py 或启动服务初始化账号")

        default_account_id = _get_default_account_id(conn)

        if not _column_exists(conn, "students", "account_id"):
            conn.execute(
                f"ALTER TABLE students ADD COLUMN account_id INTEGER NOT NULL DEFAULT {default_account_id}"
            )

        if not _column_exists(conn, "bases", "account_id"):
            conn.execute("ALTER TABLE bases ADD COLUMN account_id INTEGER")

        conn.execute(
            """
            UPDATE bases
            SET account_id = ?
            WHERE is_system = 0 AND (account_id IS NULL OR account_id = '')
            """,
            (default_account_id,),
        )
        conn.execute("UPDATE bases SET account_id = NULL WHERE is_system = 1")

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_students_account_id ON students(account_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_bases_account_id ON bases(account_id)"
        )

        conn.commit()
        print("✅ Account scoping migration completed")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate account scoping for students/bases")
    parser.add_argument("--db", default=DEFAULT_DB, help="Path to sqlite db (default: backend/el.db)")
    args = parser.parse_args()
    migrate(args.db)


if __name__ == "__main__":
    main()
