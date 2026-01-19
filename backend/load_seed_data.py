#!/usr/bin/env python3
"""
种子数据加载脚本
提供示例系统课本资料库
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "el.db"


def load_seeds():
    """加载种子数据"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # ========================================
        # 系统课本资料库
        # ========================================
        system_bases = [
            {
                "name": "人教版四年级上册",
                "description": "人教版小学英语四年级上册（PEP）",
                "units": [
                    ("Unit 1", [
                        ("WORD", "教室", "classroom"),
                        ("WORD", "窗户", "window"),
                        ("WORD", "黑板", "blackboard"),
                        ("WORD", "电灯", "light"),
                        ("WORD", "图画", "picture"),
                        ("WORD", "门", "door"),
                        ("WORD", "讲台", "teacher's desk"),
                        ("WORD", "电脑", "computer"),
                        ("WORD", "风扇", "fan"),
                        ("WORD", "墙壁", "wall"),
                        ("WORD", "地板", "floor"),
                        ("PHRASE", "真的吗？", "Really?"),
                        ("PHRASE", "我们有一间新教室", "We have a new classroom"),
                        ("PHRASE", "让我们去看看", "Let's go and see"),
                        ("PHRASE", "它在哪里？", "Where is it?"),
                    ]),
                    ("Unit 2", [
                        ("WORD", "书包", "schoolbag"),
                        ("WORD", "数学书", "maths book"),
                        ("WORD", "英语书", "English book"),
                        ("WORD", "语文书", "Chinese book"),
                        ("WORD", "故事书", "storybook"),
                        ("WORD", "糖果", "candy"),
                        ("WORD", "笔记本", "notebook"),
                        ("WORD", "玩具", "toy"),
                        ("WORD", "钥匙", "key"),
                        ("PHRASE", "我有一个新书包", "I have a new schoolbag"),
                        ("PHRASE", "它是什么颜色的？", "What colour is it?"),
                        ("PHRASE", "它是黑白相间的", "It's black and white"),
                    ]),
                    ("Unit 3", [
                        ("WORD", "强壮的", "strong"),
                        ("WORD", "友好的", "friendly"),
                        ("WORD", "安静的", "quiet"),
                        ("WORD", "头发", "hair"),
                        ("WORD", "鞋", "shoe"),
                        ("WORD", "眼镜", "glasses"),
                        ("PHRASE", "他叫什么名字？", "What's his name?"),
                        ("PHRASE", "他的名字叫张鹏", "His name is Zhang Peng"),
                        ("PHRASE", "他戴眼镜", "He has glasses"),
                        ("PHRASE", "她的鞋是红色的", "Her shoes are red"),
                    ]),
                ]
            },
            {
                "name": "人教版五年级上册",
                "description": "人教版小学英语五年级上册（PEP）",
                "units": [
                    ("Unit 1", [
                        ("WORD", "老的；年纪大的", "old"),
                        ("WORD", "年轻的", "young"),
                        ("WORD", "滑稽的；可笑的", "funny"),
                        ("WORD", "体贴的；慈祥的", "kind"),
                        ("WORD", "要求严格的；严厉的", "strict"),
                        ("WORD", "有礼貌的", "polite"),
                        ("WORD", "工作努力的", "hard-working"),
                        ("WORD", "有用的", "helpful"),
                        ("WORD", "聪明的", "clever"),
                        ("WORD", "羞怯的；腼腆的", "shy"),
                        ("PHRASE", "他是谁？", "Who's he?"),
                        ("PHRASE", "他是我们的音乐老师", "He's our music teacher"),
                        ("PHRASE", "她是什么样的人？", "What's she like?"),
                        ("PHRASE", "她很和蔼", "She's kind"),
                    ]),
                ]
            },
        ]

        for base_data in system_bases:
            # 插入资料库
            cursor.execute(
                "INSERT INTO bases (name, description, is_system) VALUES (?, ?, 1)",
                (base_data["name"], base_data["description"])
            )
            base_id = cursor.lastrowid

            # 插入词条
            for unit_name, items in base_data["units"]:
                for position, (item_type, zh_text, en_text) in enumerate(items, 1):
                    cursor.execute(
                        """INSERT INTO items
                           (base_id, unit, position, zh_text, en_text, item_type)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (base_id, unit_name, position, zh_text, en_text, item_type)
                    )

        print(f"  ✅ 创建 {len(system_bases)} 个系统课本资料库")

        conn.commit()
        print()
        print("📊 种子数据统计:")

        # 统计数据
        cursor.execute("SELECT COUNT(*) FROM students")
        print(f"   学生: {cursor.fetchone()[0]} 个")

        cursor.execute("SELECT COUNT(*) FROM bases WHERE is_system=1")
        print(f"   系统资料库: {cursor.fetchone()[0]} 个")

        cursor.execute("SELECT COUNT(*) FROM bases WHERE is_system=0")
        print(f"   自定义资料库: {cursor.fetchone()[0]} 个")

        cursor.execute("SELECT COUNT(*) FROM items")
        print(f"   词条: {cursor.fetchone()[0]} 个")

        cursor.execute("SELECT COUNT(*) FROM student_learning_bases")
        print(f"   学习库配置: {cursor.fetchone()[0]} 条")

    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


if __name__ == '__main__':
    load_seeds()
