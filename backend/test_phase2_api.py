#!/usr/bin/env python3
"""
Test script for Phase 2 API endpoints
Tests the new learning library API functionality
"""
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

from app import db

def test_students():
    """测试学生相关API函数"""
    print("\n=== 测试学生相关API函数 ===")

    with db.db() as conn:
        # Test get_students
        students = db.get_students(conn)
        print(f"✓ get_students(): {len(students)} 个学生")

        if students:
            # Test get_student
            student = db.get_student(conn, students[0]['id'])
            print(f"✓ get_student({students[0]['id']}): {student['name']}")


def test_bases():
    """测试资料库相关API函数"""
    print("\n=== 测试资料库相关API函数 ===")

    with db.db() as conn:
        # Test get_bases with filters
        all_bases = db.get_bases(conn, is_system=None)
        print(f"✓ get_bases(is_system=None): {len(all_bases)} 个资料库")

        system_bases = db.get_bases(conn, is_system=True)
        print(f"✓ get_bases(is_system=True): {len(system_bases)} 个系统资料库")

        custom_bases = db.get_bases(conn, is_system=False)
        print(f"✓ get_bases(is_system=False): {len(custom_bases)} 个自定义资料库")

        if all_bases:
            # Test get_base
            base = db.get_base(conn, all_bases[0]['id'])
            print(f"✓ get_base({all_bases[0]['id']}): {base['name']}")

            # Test get_base_items
            items = db.get_base_items(conn, all_bases[0]['id'])
            print(f"✓ get_base_items({all_bases[0]['id']}): {len(items)} 个词条")

            # Test get_base_units
            units = db.get_base_units(conn, all_bases[0]['id'])
            print(f"✓ get_base_units({all_bases[0]['id']}): {units}")


def test_learning_library():
    """测试学习库相关API函数"""
    print("\n=== 测试学习库相关API函数 ===")

    with db.db() as conn:
        students = db.get_students(conn)
        if not students:
            print("❌ 没有学生，跳过学习库测试")
            return

        student = students[0]
        print(f"\n测试学生: {student['name']} (ID={student['id']})")

        # Test get_student_learning_bases
        learning_bases = db.get_student_learning_bases(conn, student['id'])
        print(f"✓ get_student_learning_bases({student['id']}): {len(learning_bases)} 个")

        for lb in learning_bases:
            display_name = lb['custom_name'] if lb['custom_name'] else lb['base_name']
            is_system_tag = "[系统]" if lb['base_is_system'] else "[自定义]"
            progress = lb['current_unit'] if lb['current_unit'] else "未设置"
            active = "✓" if lb['is_active'] else "✗"
            print(f"  {active} {is_system_tag} {display_name} (进度: {progress})")

        # Test get active learning bases
        active_bases = db.get_student_learning_bases(conn, student['id'], is_active=True)
        print(f"✓ get_student_learning_bases({student['id']}, is_active=True): {len(active_bases)} 个")


def test_crud_operations():
    """测试增删改查操作"""
    print("\n=== 测试增删改查操作 ===")

    with db.db() as conn:
        # Test create student
        student_id = db.create_student(conn, "测试学生", "四年级")
        print(f"✓ create_student(): student_id={student_id}")

        # Test create custom base
        base_id = db.create_base(conn, "测试资料库", "测试描述", is_system=False)
        print(f"✓ create_base(): base_id={base_id}")

        # Test add items
        item_id1 = db.create_item(conn, base_id, "测试中文1", "test1", unit="__ALL__", item_type="WORD")
        item_id2 = db.create_item(conn, base_id, "测试中文2", "test2", unit="__ALL__", item_type="WORD")
        print(f"✓ create_item(): 创建了 2 个词条 (id={item_id1}, {item_id2})")

        # Test add to learning library
        lb_id = db.add_learning_base(conn, student_id, base_id, custom_name="我的测试资料库", current_unit="__ALL__")
        print(f"✓ add_learning_base(): lb_id={lb_id}")

        # Test update learning base
        db.update_learning_base(conn, lb_id, custom_name="修改后的名称", is_active=True)
        print(f"✓ update_learning_base(): 更新成功")

        # Test get updated learning bases
        learning_bases = db.get_student_learning_bases(conn, student_id)
        updated_lb = next((lb for lb in learning_bases if lb['id'] == lb_id), None)
        if updated_lb:
            print(f"✓ 验证更新: custom_name='{updated_lb['custom_name']}'")

        # Test cleanup
        db.remove_learning_base(conn, lb_id)
        print(f"✓ remove_learning_base({lb_id}): 已删除")

        db.delete_base(conn, base_id)
        print(f"✓ delete_base({base_id}): 已删除")


def main():
    """运行所有测试"""
    print("=" * 60)
    print("Phase 2 API 测试")
    print("=" * 60)

    try:
        test_students()
        test_bases()
        test_learning_library()
        test_crud_operations()

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
