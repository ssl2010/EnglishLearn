#!/usr/bin/env python3
import argparse
import os
import shutil
import sqlite3
from datetime import datetime

from passlib.hash import bcrypt


DEFAULT_DB = os.path.join(os.path.dirname(__file__), "el.db")


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_super_admin BOOLEAN DEFAULT 0,
    is_active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    session_token_hash TEXT NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    last_seen_at TIMESTAMP,
    ip_addr TEXT,
    user_agent TEXT,
    current_student_id INTEGER,
    current_base_id INTEGER,
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_auth_sessions_account_id ON auth_sessions(account_id);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires_at ON auth_sessions(expires_at);
"""


def backup_db(path: str) -> str:
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{path}.bak.{timestamp}"
    shutil.copy2(path, backup_path)
    return backup_path


def ensure_admin(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT COUNT(1) FROM accounts").fetchone()
    count = int(row[0]) if row else 0
    if count > 0:
        return
    username = os.environ.get("EL_ADMIN_USER", "admin")
    password = os.environ.get("EL_ADMIN_PASS", "")
    if not password:
        raise RuntimeError("EL_ADMIN_PASS is required to initialize admin account")
    password_hash = bcrypt.hash(password)
    conn.execute(
        "INSERT INTO accounts (username, password_hash, is_super_admin, is_active) VALUES (?,?,1,1)",
        (username, password_hash),
    )


def migrate(db_path: str) -> None:
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"DB not found: {db_path}")
    backup_path = backup_db(db_path)
    print(f"✅ Backup created: {backup_path}")
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        ensure_admin(conn)
        conn.commit()
        print("✅ Auth tables ensured")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate auth tables for EnglishLearn")
    parser.add_argument("--db", default=DEFAULT_DB, help="Path to sqlite db (default: backend/el.db)")
    args = parser.parse_args()
    migrate(args.db)


if __name__ == "__main__":
    main()
