#!/usr/bin/env python3
"""
数据库初始化脚本
用于创建/重置EnglishLearn数据库
"""
import os
import sqlite3
import sys
from pathlib import Path

# 数据库文件路径
DB_PATH = Path(__file__).parent / "el.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def init_database(force=False):
    """初始化数据库

    Args:
        force: 是否强制重建（删除现有数据库）
    """
    # 检查数据库是否已存在
    if DB_PATH.exists():
        if not force:
            print(f"❌ 数据库已存在: {DB_PATH}")
            print("   如需重建，请使用 --force 参数")
            print("   警告：这将删除所有现有数据！")
            return False
        else:
            print(f"⚠️  删除现有数据库: {DB_PATH}")
            os.remove(DB_PATH)

    # 读取schema
    if not SCHEMA_PATH.exists():
        print(f"❌ Schema文件不存在: {SCHEMA_PATH}")
        return False

    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        schema_sql = f.read()

    # 创建数据库
    print(f"📦 创建新数据库: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # 执行schema
        cursor.executescript(schema_sql)
        conn.commit()
        print("✅ 数据库结构创建成功")

        # 显示创建的表
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = cursor.fetchall()
        print(f"\n📋 已创建 {len(tables)} 个表:")
        for table in tables:
            print(f"   - {table[0]}")

        return True

    except Exception as e:
        print(f"❌ 创建数据库失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def load_seed_data():
    """加载种子数据（示例系统资料库）"""
    from load_seed_data import load_seeds

    try:
        load_seeds()
        print("✅ 种子数据加载成功")
        return True
    except Exception as e:
        print(f"❌ 加载种子数据失败: {e}")
        return False


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description='EnglishLearn 数据库初始化')
    parser.add_argument('--force', action='store_true',
                       help='强制重建数据库（删除现有数据）')
    parser.add_argument('--with-seed', action='store_true',
                       help='加载种子数据（系统资料库和词条）')

    args = parser.parse_args()

    print("=" * 60)
    print("EnglishLearn 数据库初始化")
    print("=" * 60)
    print()

    # 初始化数据库
    if not init_database(force=args.force):
        sys.exit(1)

    # 加载种子数据
    if args.with_seed:
        print()
        print("=" * 60)
        print("加载种子数据")
        print("=" * 60)
        print()
        if not load_seed_data():
            print("⚠️  种子数据加载失败，但数据库已创建")

    print()
    print("=" * 60)
    print("✅ 初始化完成！")
    print("=" * 60)
    print()
    print("下一步:")
    print("  1. 启动后端服务: uvicorn backend.app.main:app --reload")
    print("  2. 访问前端页面: http://localhost:8000/")
    print()


if __name__ == '__main__':
    main()
