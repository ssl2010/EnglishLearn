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


def init_db() -> None:
    """初始化数据库（空函数 - 数据库由 init_db.py 脚本初始化）"""
    # Database is initialized separately using init_db.py script
    # This function is kept for compatibility with startup hooks
    pass


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


def create_student(conn: sqlite3.Connection, name: str, grade: str = None, avatar: str = None) -> int:
    """创建学生"""
    if avatar is None:
        sql = "INSERT INTO students (name, grade) VALUES (?, ?)"
        return exec1(conn, sql, (name, grade))
    sql = "INSERT INTO students (name, grade, avatar) VALUES (?, ?, ?)"
    return exec1(conn, sql, (name, grade, avatar))


def update_student(conn: sqlite3.Connection, student_id: int, name: str = None, grade: str = None, avatar: str = None) -> None:
    """更新学生信息"""
    updates = []
    args = []

    if name is not None:
        updates.append("name = ?")
        args.append(name)
    if grade is not None:
        updates.append("grade = ?")
        args.append(grade)
    if avatar is not None:
        updates.append("avatar = ?")
        args.append(avatar)

    if updates:
        updates.append("updated_at = ?")
        args.append(utcnow_iso())
        args.append(student_id)

        sql = f"UPDATE students SET {', '.join(updates)} WHERE id = ?"
        conn.execute(sql, args)


def delete_student(conn: sqlite3.Connection, student_id: int) -> None:
    """删除学生"""
    conn.execute("DELETE FROM students WHERE id = ?", (student_id,))


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


def create_base(
    conn: sqlite3.Connection,
    name: str,
    description: str = None,
    is_system: bool = False,
    education_stage: str = None,
    grade: str = None,
    term: str = None,
    version: str = None,
    publisher: str = None,
    editor: str = None,
    cover_image: str = None
) -> int:
    """创建资料库"""
    sql = """INSERT INTO bases
             (name, description, is_system, education_stage, grade, term, version, publisher, editor, cover_image)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
    return exec1(conn, sql, (
        name, description, 1 if is_system else 0,
        education_stage, grade, term, version, publisher, editor, cover_image
    ))


def update_base(
    conn: sqlite3.Connection,
    base_id: int,
    name: str = None,
    description: str = None,
    is_system: bool = None,
    education_stage: str = None,
    grade: str = None,
    term: str = None,
    version: str = None,
    publisher: str = None,
    editor: str = None,
    cover_image: str = None
) -> None:
    """更新资料库"""
    updates = []
    args = []

    if name is not None:
        updates.append("name = ?")
        args.append(name)
    if description is not None:
        updates.append("description = ?")
        args.append(description)
    if is_system is not None:
        updates.append("is_system = ?")
        args.append(1 if is_system else 0)
    if education_stage is not None:
        updates.append("education_stage = ?")
        args.append(education_stage)
    if grade is not None:
        updates.append("grade = ?")
        args.append(grade)
    if term is not None:
        updates.append("term = ?")
        args.append(term)
    if version is not None:
        updates.append("version = ?")
        args.append(version)
    if publisher is not None:
        updates.append("publisher = ?")
        args.append(publisher)
    if editor is not None:
        updates.append("editor = ?")
        args.append(editor)
    if cover_image is not None:
        updates.append("cover_image = ?")
        args.append(cover_image)

    if updates:
        updates.append("updated_at = ?")
        args.append(utcnow_iso())
        args.append(base_id)

        sql = f"UPDATE bases SET {', '.join(updates)} WHERE id = ?"
        conn.execute(sql, args)


def delete_base(conn: sqlite3.Connection, base_id: int) -> None:
    """删除资料库"""
    conn.execute("DELETE FROM bases WHERE id = ?", (base_id,))


# ============================================================
# 单元元数据相关
# ============================================================

def get_units(conn: sqlite3.Connection, base_id: int) -> List[Dict]:
    """获取资料库的单元元数据列表

    Args:
        base_id: 资料库ID

    Returns:
        单元列表，按unit_index排序
    """
    sql = """
        SELECT * FROM units
        WHERE base_id = ?
        ORDER BY unit_index, unit_code
    """
    rows = qall(conn, sql, (base_id,))
    return rows_to_dicts(rows)


def get_unit(conn: sqlite3.Connection, base_id: int, unit_code: str) -> Optional[Dict]:
    """获取单个单元元数据

    Args:
        base_id: 资料库ID
        unit_code: 单元代码（如"U1", "Unit 1"）

    Returns:
        单元信息字典，不存在则返回None
    """
    sql = "SELECT * FROM units WHERE base_id = ? AND unit_code = ?"
    row = qone(conn, sql, (base_id, unit_code))
    return row_to_dict(row)


def create_unit(
    conn: sqlite3.Connection,
    base_id: int,
    unit_code: str,
    unit_name: str = None,
    unit_index: int = None,
    description: str = None
) -> int:
    """创建单元元数据

    Args:
        base_id: 资料库ID
        unit_code: 单元代码（如"U1", "Unit 1"）
        unit_name: 单元名称（如"My school"）
        unit_index: 单元序号（用于排序）
        description: 单元描述

    Returns:
        新创建的单元ID
    """
    sql = """
        INSERT INTO units (base_id, unit_code, unit_name, unit_index, description)
        VALUES (?, ?, ?, ?, ?)
    """
    return exec1(conn, sql, (base_id, unit_code, unit_name, unit_index, description))


def update_unit(
    conn: sqlite3.Connection,
    unit_id: int,
    unit_name: str = None,
    unit_index: int = None,
    description: str = None
) -> None:
    """更新单元元数据

    Args:
        unit_id: 单元ID
        unit_name: 单元名称
        unit_index: 单元序号
        description: 单元描述
    """
    updates = []
    args = []

    if unit_name is not None:
        updates.append("unit_name = ?")
        args.append(unit_name)
    if unit_index is not None:
        updates.append("unit_index = ?")
        args.append(unit_index)
    if description is not None:
        updates.append("description = ?")
        args.append(description)

    if updates:
        args.append(unit_id)
        sql = f"UPDATE units SET {', '.join(updates)} WHERE id = ?"
        conn.execute(sql, args)


def upsert_units(conn: sqlite3.Connection, base_id: int, units: List[Dict]) -> Dict[str, int]:
    """批量插入或更新单元元数据

    Args:
        base_id: 资料库ID
        units: 单元列表，每个元素包含 unit_code, unit_name, unit_index, description 等字段

    Returns:
        统计信息：{"inserted": N, "updated": M}
    """
    inserted = 0
    updated = 0

    for unit_data in units:
        unit_code = unit_data.get("unit_code")
        if not unit_code:
            continue  # Skip units without code

        unit_name = unit_data.get("unit_name")
        unit_index = unit_data.get("unit_index")
        description = unit_data.get("description")

        # Check if unit already exists
        existing = get_unit(conn, base_id, unit_code)

        if existing:
            # Update existing unit
            update_unit(
                conn,
                existing["id"],
                unit_name=unit_name,
                unit_index=unit_index,
                description=description
            )
            updated += 1
        else:
            # Insert new unit
            create_unit(
                conn,
                base_id=base_id,
                unit_code=unit_code,
                unit_name=unit_name,
                unit_index=unit_index,
                description=description
            )
            inserted += 1

    return {"inserted": inserted, "updated": updated}


def delete_unit(conn: sqlite3.Connection, unit_id: int) -> None:
    """删除单元元数据

    Args:
        unit_id: 单元ID
    """
    conn.execute("DELETE FROM units WHERE id = ?", (unit_id,))


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
    item_type: str = "WORD",
    difficulty_tag: str = None
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
        INSERT INTO items (base_id, unit, position, zh_text, en_text, item_type, difficulty_tag)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """
    return exec1(conn, sql, (base_id, unit, position, zh_text, en_text, item_type, difficulty_tag))


def update_item(
    conn: sqlite3.Connection,
    item_id: int,
    zh_text: str = None,
    en_text: str = None,
    unit: str = None,
    position: int = None,
    item_type: str = None,
    difficulty_tag: str = None
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
    if difficulty_tag is not None:
        updates.append("difficulty_tag = ?")
        args.append(difficulty_tag)

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
            b.is_system as base_is_system,
            b.education_stage as base_education_stage,
            b.grade as base_grade,
            b.term as base_term,
            b.version as base_version,
            b.publisher as base_publisher,
            b.cover_image as base_cover_image
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
