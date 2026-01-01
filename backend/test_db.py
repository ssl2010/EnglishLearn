#!/usr/bin/env python3
"""
测试db.py的基础查询函数
"""
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

from app import db

def test_students():
    """测试学生相关函数"""
    print("\n=== 测试学生相关函数 ===")

    with db.db() as conn:
        # 获取所有学生
        students = db.get_students(conn)
        print(f"✓ get_students(): {len(students)} 个学生")
        for s in students:
            print(f"  - {s['id']}: {s['name']} ({s['grade']})")

        # 获取单个学生
        if students:
            student = db.get_student(conn, students[0]['id'])
            print(f"✓ get_student({students[0]['id']}): {student['name']}")


def test_bases():
    """测试资料库相关函数"""
    print("\n=== 测试资料库相关函数 ===")

    with db.db() as conn:
        # 获取所有资料库
        all_bases = db.get_bases(conn)
        print(f"✓ get_bases(): {len(all_bases)} 个资料库")

        # 获取系统资料库
        system_bases = db.get_bases(conn, is_system=True)
        print(f"✓ get_bases(is_system=True): {len(system_bases)} 个")
        for b in system_bases:
            print(f"  - [系统] {b['id']}: {b['name']}")

        # 获取自定义资料库
        custom_bases = db.get_bases(conn, is_system=False)
        print(f"✓ get_bases(is_system=False): {len(custom_bases)} 个")
        for b in custom_bases:
            print(f"  - [自定义] {b['id']}: {b['name']}")


def test_items():
    """测试词条相关函数"""
    print("\n=== 测试词条相关函数 ===")

    with db.db() as conn:
        # 获取第一个资料库的词条
        bases = db.get_bases(conn)
        if not bases:
            print("❌ 没有资料库，跳过词条测试")
            return

        base = bases[0]
        print(f"\n测试资料库: {base['name']} (ID={base['id']})")

        # 获取所有词条
        items = db.get_base_items(conn, base['id'])
        print(f"✓ get_base_items({base['id']}): {len(items)} 个词条")

        # 获取单元列表
        units = db.get_base_units(conn, base['id'])
        print(f"✓ get_base_units({base['id']}): {units}")

        # 按单元获取词条
        if units:
            unit_items = db.get_base_items(conn, base['id'], unit=units[0])
            print(f"✓ get_base_items({base['id']}, unit='{units[0]}'): {len(unit_items)} 个")
            # 显示前3个
            for item in unit_items[:3]:
                print(f"  - {item['position']}. {item['zh_text']} = {item['en_text']} ({item['item_type']})")


def test_learning_bases():
    """测试学生学习库相关函数"""
    print("\n=== 测试学生学习库相关函数 ===")

    with db.db() as conn:
        students = db.get_students(conn)
        if not students:
            print("❌ 没有学生，跳过学习库测试")
            return

        student = students[0]
        print(f"\n测试学生: {student['name']} (ID={student['id']})")

        # 获取学习库配置
        learning_bases = db.get_student_learning_bases(conn, student['id'])
        print(f"✓ get_student_learning_bases({student['id']}): {len(learning_bases)} 个")

        for lb in learning_bases:
            display_name = lb['custom_name'] if lb['custom_name'] else lb['base_name']
            is_system_tag = "[系统]" if lb['base_is_system'] else "[自定义]"
            progress = lb['current_unit'] if lb['current_unit'] else "未设置"
            active = "✓" if lb['is_active'] else "✗"
            print(f"  {active} {is_system_tag} {display_name} (进度: {progress})")


def test_sessions():
    """测试练习单相关函数"""
    print("\n=== 测试练习单相关函数 ===")

    with db.db() as conn:
        students = db.get_students(conn)
        if not students:
            print("❌ 没有学生，跳过练习单测试")
            return

        student = students[0]

        # 创建测试练习单
        session_id = db.create_session(conn, student['id'])
        print(f"✓ create_session({student['id']}): session_id={session_id}")

        # 获取练习单
        session = db.get_session(conn, session_id)
        print(f"✓ get_session({session_id}): {session}")

        # 添加词条到练习单
        bases = db.get_bases(conn)
        if bases:
            items = db.get_base_items(conn, bases[0]['id'])
            if items:
                # 添加前3个词条
                for i, item in enumerate(items[:3], 1):
                    db.add_session_item(conn, session_id, item['id'], i)
                print(f"✓ add_session_item(): 添加了 3 个词条")

                # 获取练习单词条
                session_items = db.get_session_items(conn, session_id)
                print(f"✓ get_session_items({session_id}): {len(session_items)} 个")
                for si in session_items:
                    print(f"  - {si['position']}. {si['zh_text']} = {si['en_text']}")


def test_crud():
    """测试增删改查"""
    print("\n=== 测试增删改查 ===")

    with db.db() as conn:
        # 创建自定义资料库
        base_id = db.create_base(conn, "测试资料库", "这是一个测试", is_system=False)
        print(f"✓ create_base(): base_id={base_id}")

        # 添加词条
        item_id1 = db.create_item(conn, base_id, "苹果", "apple", unit="__ALL__", item_type="WORD")
        item_id2 = db.create_item(conn, base_id, "香蕉", "banana", unit="__ALL__", item_type="WORD")
        print(f"✓ create_item(): 创建了 2 个词条 (id={item_id1}, {item_id2})")

        # 修改资料库
        db.update_base(conn, base_id, name="测试资料库(已修改)")
        base = db.get_base(conn, base_id)
        print(f"✓ update_base(): {base['name']}")

        # 修改词条
        db.update_item(conn, item_id1, zh_text="红苹果")
        item = db.get_item(conn, item_id1)
        print(f"✓ update_item(): {item['zh_text']} = {item['en_text']}")

        # 删除词条
        db.delete_item(conn, item_id2)
        print(f"✓ delete_item({item_id2}): 已删除")

        # 删除资料库
        db.delete_base(conn, base_id)
        print(f"✓ delete_base({base_id}): 已删除")


def main():
    """运行所有测试"""
    print("=" * 60)
    print("数据库查询函数测试")
    print("=" * 60)

    try:
        test_students()
        test_bases()
        test_items()
        test_learning_bases()
        test_sessions()
        test_crud()

        print("\n" + "=" * 60)
        print("✅ 所有测试通过！")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
