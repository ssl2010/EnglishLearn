"""
数据库访问层
提供基础的数据库查询函数
"""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

# 数据库路径
DB_PATH = os.environ.get(
    "EL_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "el.db"),
)


def utcnow_iso() -> str:
    """获取当前UTC时间的ISO格式字符串"""
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    """创建数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db() -> Iterable[sqlite3.Connection]:
    """数据库上下文管理器"""
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ============================================================
# 工具函数
# ============================================================

def qone(conn: sqlite3.Connection, sql: str, args: Tuple[Any, ...] = ()) -> Optional[sqlite3.Row]:
    """查询单行"""
    cur = conn.execute(sql, args)
    return cur.fetchone()


def qall(conn: sqlite3.Connection, sql: str, args: Tuple[Any, ...] = ()) -> List[sqlite3.Row]:
    """查询多行"""
    cur = conn.execute(sql, args)
    return cur.fetchall()


def exec1(conn: sqlite3.Connection, sql: str, args: Tuple[Any, ...] = ()) -> int:
    """执行SQL并返回lastrowid"""
    cur = conn.execute(sql, args)
    return cur.lastrowid


def to_json(obj: Any) -> str:
    """转换为JSON字符串"""
    return json.dumps(obj, ensure_ascii=False)


def from_json(s: str) -> Any:
    """从JSON字符串解析"""
    return json.loads(s)


def row_to_dict(row: Optional[sqlite3.Row]) -> Optional[Dict]:
    """将Row对象转换为字典"""
    if row is None:
        return None
    return dict(row)


def rows_to_dicts(rows: List[sqlite3.Row]) -> List[Dict]:
    """将Row列表转换为字典列表"""
    return [dict(row) for row in rows]


# ============================================================
# 学生相关
# ============================================================

def get_students(conn: sqlite3.Connection) -> List[Dict]:
    """获取所有学生"""
    rows = qall(conn, "SELECT * FROM students ORDER BY id")
    return rows_to_dicts(rows)


def get_student(conn: sqlite3.Connection, student_id: int) -> Optional[Dict]:
    """获取单个学生"""
    row = qone(conn, "SELECT * FROM students WHERE id = ?", (student_id,))
    return row_to_dict(row)


def create_student(conn: sqlite3.Connection, name: str, grade: str = None) -> int:
    """创建学生"""
    sql = "INSERT INTO students (name, grade) VALUES (?, ?)"
    return exec1(conn, sql, (name, grade))


def update_student(conn: sqlite3.Connection, student_id: int, name: str = None, grade: str = None) -> None:
    """更新学生信息"""
    updates = []
    args = []

    if name is not None:
        updates.append("name = ?")
        args.append(name)
    if grade is not None:
        updates.append("grade = ?")
        args.append(grade)

    if updates:
        updates.append("updated_at = ?")
        args.append(utcnow_iso())
        args.append(student_id)

        sql = f"UPDATE students SET {', '.join(updates)} WHERE id = ?"
        conn.execute(sql, args)


# ============================================================
# 资料库相关
# ============================================================

def get_bases(conn: sqlite3.Connection, is_system: bool = None) -> List[Dict]:
    """获取资料库列表

    Args:
        is_system: None=全部, True=仅系统, False=仅自定义
    """
    if is_system is None:
        sql = "SELECT * FROM bases ORDER BY is_system DESC, id"
        rows = qall(conn, sql)
    else:
        sql = "SELECT * FROM bases WHERE is_system = ? ORDER BY id"
        rows = qall(conn, sql, (1 if is_system else 0,))

    return rows_to_dicts(rows)


def get_base(conn: sqlite3.Connection, base_id: int) -> Optional[Dict]:
    """获取单个资料库"""
    row = qone(conn, "SELECT * FROM bases WHERE id = ?", (base_id,))
    return row_to_dict(row)


def create_base(conn: sqlite3.Connection, name: str, description: str = None, is_system: bool = False) -> int:
    """创建资料库"""
    sql = "INSERT INTO bases (name, description, is_system) VALUES (?, ?, ?)"
    return exec1(conn, sql, (name, description, 1 if is_system else 0))


def update_base(conn: sqlite3.Connection, base_id: int, name: str = None, description: str = None) -> None:
    """更新资料库（仅限自定义资料库）"""
    # 检查是否为系统资料库
    base = get_base(conn, base_id)
    if base and base['is_system']:
        raise ValueError("Cannot update system base")

    updates = []
    args = []

    if name is not None:
        updates.append("name = ?")
        args.append(name)
    if description is not None:
        updates.append("description = ?")
        args.append(description)

    if updates:
        updates.append("updated_at = ?")
        args.append(utcnow_iso())
        args.append(base_id)

        sql = f"UPDATE bases SET {', '.join(updates)} WHERE id = ?"
        conn.execute(sql, args)


def delete_base(conn: sqlite3.Connection, base_id: int) -> None:
    """删除资料库（仅限自定义资料库）"""
    # 检查是否为系统资料库
    base = get_base(conn, base_id)
    if base and base['is_system']:
        raise ValueError("Cannot delete system base")

    conn.execute("DELETE FROM bases WHERE id = ?", (base_id,))


# ============================================================
# 词条相关
# ============================================================

def get_base_items(
    conn: sqlite3.Connection,
    base_id: int,
    unit: str = None,
    item_type: str = None
) -> List[Dict]:
    """获取资料库的词条

    Args:
        base_id: 资料库ID
        unit: 单元过滤 (None=全部, "__ALL__"=不分单元, "Unit 1"=具体单元)
        item_type: 类型过滤 (None=全部, "WORD"/"PHRASE"/"SENTENCE")
    """
    sql = "SELECT * FROM items WHERE base_id = ?"
    args = [base_id]

    if unit is not None:
        sql += " AND unit = ?"
        args.append(unit)

    if item_type is not None:
        sql += " AND item_type = ?"
        args.append(item_type)

    sql += " ORDER BY unit, position"
    rows = qall(conn, sql, tuple(args))
    return rows_to_dicts(rows)


def get_base_units(conn: sqlite3.Connection, base_id: int) -> List[str]:
    """获取资料库的所有单元列表"""
    sql = """
        SELECT DISTINCT unit
        FROM items
        WHERE base_id = ? AND unit IS NOT NULL AND unit != '__ALL__'
        ORDER BY unit
    """
    rows = qall(conn, sql, (base_id,))
    return [row['unit'] for row in rows]


def get_item(conn: sqlite3.Connection, item_id: int) -> Optional[Dict]:
    """获取单个词条"""
    row = qone(conn, "SELECT * FROM items WHERE id = ?", (item_id,))
    return row_to_dict(row)


def create_item(
    conn: sqlite3.Connection,
    base_id: int,
    zh_text: str,
    en_text: str,
    unit: str = "__ALL__",
    position: int = None,
    item_type: str = "WORD"
) -> int:
    """创建词条"""
    # 如果未指定position，自动计算
    if position is None:
        row = qone(
            conn,
            "SELECT COALESCE(MAX(position), 0) + 1 as next_pos FROM items WHERE base_id = ? AND unit = ?",
            (base_id, unit)
        )
        position = row['next_pos']

    sql = """
        INSERT INTO items (base_id, unit, position, zh_text, en_text, item_type)
        VALUES (?, ?, ?, ?, ?, ?)
    """
    return exec1(conn, sql, (base_id, unit, position, zh_text, en_text, item_type))


def update_item(
    conn: sqlite3.Connection,
    item_id: int,
    zh_text: str = None,
    en_text: str = None,
    unit: str = None,
    position: int = None,
    item_type: str = None
) -> None:
    """更新词条"""
    updates = []
    args = []

    if zh_text is not None:
        updates.append("zh_text = ?")
        args.append(zh_text)
    if en_text is not None:
        updates.append("en_text = ?")
        args.append(en_text)
    if unit is not None:
        updates.append("unit = ?")
        args.append(unit)
    if position is not None:
        updates.append("position = ?")
        args.append(position)
    if item_type is not None:
        updates.append("item_type = ?")
        args.append(item_type)

    if updates:
        updates.append("updated_at = ?")
        args.append(utcnow_iso())
        args.append(item_id)

        sql = f"UPDATE items SET {', '.join(updates)} WHERE id = ?"
        conn.execute(sql, args)


def delete_item(conn: sqlite3.Connection, item_id: int) -> None:
    """删除词条"""
    conn.execute("DELETE FROM items WHERE id = ?", (item_id,))


# ============================================================
# 学生学习库相关
# ============================================================

def get_student_learning_bases(conn: sqlite3.Connection, student_id: int, is_active: bool = None) -> List[Dict]:
    """获取学生的学习库配置

    返回格式包含资料库完整信息
    """
    sql = """
        SELECT
            slb.*,
            b.name as base_name,
            b.description as base_description,
            b.is_system as base_is_system
        FROM student_learning_bases slb
        JOIN bases b ON slb.base_id = b.id
        WHERE slb.student_id = ?
    """
    args = [student_id]

    if is_active is not None:
        sql += " AND slb.is_active = ?"
        args.append(1 if is_active else 0)

    sql += " ORDER BY slb.display_order, slb.id"
    rows = qall(conn, sql, tuple(args))
    return rows_to_dicts(rows)


def add_learning_base(
    conn: sqlite3.Connection,
    student_id: int,
    base_id: int,
    custom_name: str = None,
    current_unit: str = None
) -> int:
    """为学生添加资料库到学习库"""
    # 获取当前最大display_order
    row = qone(
        conn,
        "SELECT COALESCE(MAX(display_order), -1) + 1 as next_order FROM student_learning_bases WHERE student_id = ?",
        (student_id,)
    )
    display_order = row['next_order']

    sql = """
        INSERT INTO student_learning_bases
        (student_id, base_id, custom_name, current_unit, display_order)
        VALUES (?, ?, ?, ?, ?)
    """
    return exec1(conn, sql, (student_id, base_id, custom_name, current_unit, display_order))


def update_learning_base(
    conn: sqlite3.Connection,
    lb_id: int,
    custom_name: str = None,
    current_unit: str = None,
    is_active: bool = None
) -> None:
    """更新学生学习库配置"""
    updates = []
    args = []

    if custom_name is not None:
        updates.append("custom_name = ?")
        args.append(custom_name)
    if current_unit is not None:
        updates.append("current_unit = ?")
        args.append(current_unit)
    if is_active is not None:
        updates.append("is_active = ?")
        args.append(1 if is_active else 0)

    if updates:
        updates.append("updated_at = ?")
        args.append(utcnow_iso())
        args.append(lb_id)

        sql = f"UPDATE student_learning_bases SET {', '.join(updates)} WHERE id = ?"
        conn.execute(sql, args)


def remove_learning_base(conn: sqlite3.Connection, lb_id: int) -> None:
    """从学生学习库移除资料库"""
    conn.execute("DELETE FROM student_learning_bases WHERE id = ?", (lb_id,))


# ============================================================
# 练习单相关（基础版本，后续完善）
# ============================================================

def create_session(conn: sqlite3.Connection, student_id: int, session_date: str = None) -> int:
    """创建练习单"""
    if session_date is None:
        session_date = datetime.now().strftime("%Y-%m-%d")

    sql = "INSERT INTO sessions (student_id, session_date) VALUES (?, ?)"
    return exec1(conn, sql, (student_id, session_date))


def get_session(conn: sqlite3.Connection, session_id: int) -> Optional[Dict]:
    """获取练习单"""
    row = qone(conn, "SELECT * FROM sessions WHERE id = ?", (session_id,))
    return row_to_dict(row)


def add_session_item(conn: sqlite3.Connection, session_id: int, item_id: int, position: int) -> int:
    """添加词条到练习单"""
    sql = "INSERT INTO session_items (session_id, item_id, position) VALUES (?, ?, ?)"
    return exec1(conn, sql, (session_id, item_id, position))


def get_session_items(conn: sqlite3.Connection, session_id: int) -> List[Dict]:
    """获取练习单的词条列表"""
    sql = """
        SELECT
            si.*,
            i.base_id,
            i.unit,
            i.zh_text,
            i.en_text,
            i.item_type
        FROM session_items si
        JOIN items i ON si.item_id = i.id
        WHERE si.session_id = ?
        ORDER BY si.position
    """
    rows = qall(conn, sql, (session_id,))
    return rows_to_dicts(rows)
