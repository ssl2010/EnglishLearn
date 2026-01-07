#!/usr/bin/env python3
"""
数据库迁移脚本：为bases表添加元数据和封面图片字段

新增字段：
- education_stage TEXT - 学段（小学/初中/高中）
- grade TEXT - 年级（4年级）
- term TEXT - 学期（上学期/下学期）
- version TEXT - 版本（2025年秋）
- publisher TEXT - 出版社
- cover_image TEXT - 封面图片路径
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
        # 检查字段是否已存在（避免重复迁移）
        cursor.execute("PRAGMA table_info(bases)")
        columns = [col[1] for col in cursor.fetchall()]

        fields_to_add = {
            "education_stage": "TEXT",  # 学段
            "grade": "TEXT",  # 年级
            "term": "TEXT",  # 学期
            "version": "TEXT",  # 版本
            "publisher": "TEXT",  # 出版社
            "cover_image": "TEXT",  # 封面图片
        }

        added = []
        for field_name, field_type in fields_to_add.items():
            if field_name not in columns:
                sql = f"ALTER TABLE bases ADD COLUMN {field_name} {field_type}"
                cursor.execute(sql)
                added.append(field_name)
                print(f"✅ 添加字段: {field_name}")
            else:
                print(f"⏭️  字段已存在: {field_name}")

        if added:
            conn.commit()
            print(f"\n✅ 迁移完成！添加了 {len(added)} 个字段")
        else:
            print("\n✅ 无需迁移（所有字段已存在）")

        return True

    except Exception as e:
        print(f"❌ 迁移失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


if __name__ == '__main__':
    print("=" * 60)
    print("数据库迁移：添加资料库元数据字段")
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
