import hashlib
import os
import re
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from passlib.hash import bcrypt

from .db import db, exec1, qall, qone, row_to_dict, rows_to_dicts, utcnow_iso


def hash_password(plain: str) -> str:
    return bcrypt.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.verify(plain, hashed)
    except Exception:
        return False


def _sha256(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now_utc() -> datetime:
    return datetime.utcnow()


def _expires_at(ttl_seconds: int) -> str:
    return (_now_utc() + timedelta(seconds=ttl_seconds)).isoformat()


def create_session(account_id: int, ip: Optional[str], user_agent: Optional[str], ttl_seconds: int) -> str:
    token = secrets.token_urlsafe(32)
    token_hash = _sha256(token)
    expires_at = _expires_at(ttl_seconds)
    with db() as conn:
        conn.execute(
            """
            INSERT INTO auth_sessions(account_id, session_token_hash, expires_at, last_seen_at, ip_addr, user_agent)
            VALUES (?,?,?,?,?,?)
            """,
            (account_id, token_hash, expires_at, utcnow_iso(), ip, user_agent),
        )
    return token


def delete_session(token: str) -> None:
    token_hash = _sha256(token)
    with db() as conn:
        conn.execute("DELETE FROM auth_sessions WHERE session_token_hash = ?", (token_hash,))


def get_account_by_session(token: Optional[str]) -> Optional[Dict[str, Any]]:
    if not token:
        return None
    token_hash = _sha256(token)
    now_iso = _now_utc().isoformat()
    with db() as conn:
        row = qone(
            conn,
            """
            SELECT a.id, a.username, a.is_super_admin, a.is_active,
                   s.current_student_id, s.current_base_id, s.expires_at
            FROM auth_sessions s
            JOIN accounts a ON s.account_id = a.id
            WHERE s.session_token_hash = ?
            """,
            (token_hash,),
        )
        if not row:
            return None
        if row["expires_at"] and row["expires_at"] <= now_iso:
            conn.execute("DELETE FROM auth_sessions WHERE session_token_hash = ?", (token_hash,))
            return None
        if row["is_active"] == 0:
            return None
        conn.execute(
            "UPDATE auth_sessions SET last_seen_at = ? WHERE session_token_hash = ?",
            (utcnow_iso(), token_hash),
        )
        account = row_to_dict(row)
        return account


def ensure_super_admin() -> None:
    username = os.environ.get("EL_ADMIN_USER", "admin")
    with db() as conn:
        row = qone(conn, "SELECT COUNT(1) AS c FROM accounts")
        count = int(row["c"]) if row else 0
        if count > 0:
            return
        password = os.environ.get("EL_ADMIN_PASS", "")
        if not password:
            raise RuntimeError("EL_ADMIN_PASS is required to initialize admin account (first run only)")
        try:
            _validate_password(password)
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
        conn.execute(
            """
            INSERT INTO accounts(username, password_hash, is_super_admin, is_active, created_at, updated_at)
            VALUES (?,?,?,?,?,?)
            """,
            (username, hash_password(password), 1, 1, utcnow_iso(), utcnow_iso()),
        )


_USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{3,32}$")


def _validate_username(username: str) -> None:
    if not username or not _USERNAME_RE.match(username):
        raise ValueError("用户名需为 3~32 位字母/数字/._-")


def _validate_password(pw: str) -> None:
    if not pw or len(pw) < 8:
        raise ValueError("密码至少 8 位")


def delete_sessions_for_account(account_id: int) -> None:
    with db() as conn:
        conn.execute("DELETE FROM auth_sessions WHERE account_id = ?", (account_id,))


def count_active_admins(conn) -> int:
    row = qone(conn, "SELECT COUNT(1) AS c FROM accounts WHERE is_super_admin=1 AND is_active=1")
    return int(row["c"]) if row else 0


def list_accounts_with_last_seen() -> List[Dict[str, Any]]:
    with db() as conn:
        rows = qall(
            conn,
            """
            SELECT
              a.id, a.username, a.is_super_admin, a.is_active, a.created_at, a.updated_at,
              MAX(s.last_seen_at) AS last_seen_at
            FROM accounts a
            LEFT JOIN auth_sessions s ON s.account_id = a.id
            GROUP BY a.id
            ORDER BY a.is_super_admin DESC, a.username ASC
            """,
        )
    return rows_to_dicts(rows)


def create_account(username: str, password: str, is_super_admin: bool = False) -> Dict[str, Any]:
    _validate_username(username)
    _validate_password(password)
    now = utcnow_iso()
    with db() as conn:
        account_id = exec1(
            conn,
            """
            INSERT INTO accounts(username, password_hash, is_super_admin, is_active, created_at, updated_at)
            VALUES (?,?,?,?,?,?)
            """,
            (username, hash_password(password), 1 if is_super_admin else 0, 1, now, now),
        )
        row = qone(
            conn,
            """
            SELECT id, username, is_super_admin, is_active, created_at, updated_at
            FROM accounts
            WHERE id = ?
            """,
            (account_id,),
        )
    return row_to_dict(row)


def set_account_password(account_id: int, new_password: str) -> None:
    _validate_password(new_password)
    with db() as conn:
        conn.execute(
            "UPDATE accounts SET password_hash = ?, updated_at = ? WHERE id = ?",
            (hash_password(new_password), utcnow_iso(), account_id),
        )


def update_account_flags(account_id: int, is_active: Optional[bool], is_super_admin: Optional[bool]) -> None:
    updates = []
    args: List[Any] = []
    if is_active is not None:
        updates.append("is_active = ?")
        args.append(1 if is_active else 0)
    if is_super_admin is not None:
        updates.append("is_super_admin = ?")
        args.append(1 if is_super_admin else 0)
    if not updates:
        return
    updates.append("updated_at = ?")
    args.append(utcnow_iso())
    args.append(account_id)
    with db() as conn:
        conn.execute(f"UPDATE accounts SET {', '.join(updates)} WHERE id = ?", args)


def deactivate_account(account_id: int) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE accounts SET is_active = 0, updated_at = ? WHERE id = ?",
            (utcnow_iso(), account_id),
        )
        conn.execute("DELETE FROM auth_sessions WHERE account_id = ?", (account_id,))


def delete_account_permanently(account_id: int) -> Dict[str, Any]:
    """
    永久删除账号及其所有关联数据

    注意：此操作不可恢复！会删除：
    - 账号本身
    - 该账号下所有学生及其练习记录
    - 该账号创建的私有资料库
    - 所有会话

    由于数据库外键设置了 ON DELETE CASCADE，关联数据会自动级联删除

    Returns:
        删除统计信息
    """
    stats = {
        "students_deleted": 0,
        "bases_deleted": 0,
        "sessions_deleted": 0,
    }

    with db() as conn:
        # 启用外键约束（确保级联删除生效）
        conn.execute("PRAGMA foreign_keys = ON")

        # 统计将被删除的数据
        row = qone(conn, "SELECT COUNT(1) AS c FROM students WHERE account_id = ?", (account_id,))
        stats["students_deleted"] = int(row["c"]) if row else 0

        row = qone(conn, "SELECT COUNT(1) AS c FROM bases WHERE account_id = ? AND is_system = 0", (account_id,))
        stats["bases_deleted"] = int(row["c"]) if row else 0

        row = qone(conn, "SELECT COUNT(1) AS c FROM auth_sessions WHERE account_id = ?", (account_id,))
        stats["sessions_deleted"] = int(row["c"]) if row else 0

        # 删除账号（级联删除关联数据）
        conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))

    return stats
