#!/usr/bin/env python3
"""诊断AI识别结果的知识库匹配情况"""
import json
import sqlite3
import re
import sys

def normalize_answer(text):
    """标准化答案文本"""
    if not text:
        return ""
    # Remove punctuation and extra spaces
    text = re.sub(r'[^\w\s]', '', text.lower())
    text = re.sub(r'\s+', ' ', text).strip()
    return text

# Read LLM result
with open('backend/media/uploads/debug_last/llm_raw.json', 'r', encoding='utf-8') as f:
    llm_data = json.load(f)

# Connect to database
conn = sqlite3.connect('backend/el.db')
conn.row_factory = sqlite3.Row

# Get student's active learning bases (assuming student_id=5 for diagnosis)
student_id = 5
base_rows = conn.execute("""
    SELECT base_id FROM student_learning_bases
    WHERE student_id = ? AND is_active = 1
""", (student_id,)).fetchall()

if not base_rows:
    print("错误：学生没有激活的学习库！")
    sys.exit(1)

base_ids = [row[0] for row in base_rows]
print(f"学生激活的学习库：{base_ids}\n")

# Get base names
for bid in base_ids:
    base_row = conn.execute("SELECT name FROM bases WHERE id=?", (bid,)).fetchone()
    if base_row:
        print(f"  - Base {bid}: {base_row[0]}")
print()

# Process each section
total_items = 0
matched_items = 0
unmatched_items = []

for section in llm_data['sections']:
    title = section['title']
    sec_type = section['type']
    items = section['items']

    print(f"\n{'='*60}")
    print(f"{title} ({sec_type})")
    print(f"{'='*60}")

    for idx, it in enumerate(items, 1):
        total_items += 1
        q_num = it.get('q', idx)
        hint = it.get('hint', '')
        ans = it.get('ans', '')
        ok = it.get('ok')

        # Try to match in knowledge base
        cleaned_ans = re.sub(r"^\s*(英文[:：]?\s*)", "", ans)
        norm = normalize_answer(cleaned_ans) if cleaned_ans else ""

        matched = False
        matched_item = None

        # Exact match by answer or hint
        if norm or hint:
            placeholders = ','.join('?' * len(base_ids))
            query = f"""
                SELECT id, en_text, zh_text, item_type FROM items
                WHERE base_id IN ({placeholders})
                  AND (
                    (LOWER(en_text)=? AND ?<>'')
                    OR (zh_text=? AND ?<>'')
                  )
                LIMIT 1
            """
            row = conn.execute(query, (*base_ids, cleaned_ans.lower(), cleaned_ans, hint, hint)).fetchone()
            if row:
                matched = True
                matched_item = dict(row)

        # Fuzzy match if no exact match
        if not matched and norm and len(norm) >= 6:
            placeholders = ','.join('?' * len(base_ids))
            query = f"""
                SELECT id, en_text, zh_text, item_type FROM items
                WHERE base_id IN ({placeholders})
                  AND LOWER(en_text) LIKE ?
                LIMIT 1
            """
            row = conn.execute(query, (*base_ids, f"%{norm.lower()}%")).fetchone()
            if row:
                matched = True
                matched_item = dict(row)

        # Print result
        status = "✓ 匹配" if matched else "✗ 未匹配"
        ok_status = "正确" if ok else "错误" if ok is False else "未知"

        print(f"\n题{q_num}. {hint}")
        print(f"  学生答案: {ans or '(未作答)'}")
        print(f"  LLM判断: {ok_status}")
        print(f"  知识库: {status}")

        if matched and matched_item:
            matched_items += 1
            print(f"  匹配到: {matched_item['en_text']} ({matched_item['item_type']})")
        else:
            unmatched_items.append({
                'section': title,
                'q': q_num,
                'hint': hint,
                'ans': ans,
                'ok': ok
            })
            print(f"  原因: {'答案为空' if not ans else '长度不足6' if len(norm) < 6 else '无法匹配'}")

# Summary
print(f"\n\n{'='*60}")
print("总结")
print(f"{'='*60}")
print(f"总题数: {total_items}")
print(f"匹配到知识库: {matched_items} ({matched_items/total_items*100:.1f}%)")
print(f"未匹配: {len(unmatched_items)} ({len(unmatched_items)/total_items*100:.1f}%)")

print(f"\n未匹配的题目详情：")
for item in unmatched_items:
    ok_str = "✓" if item['ok'] else "✗" if item['ok'] is False else "?"
    print(f"  [{ok_str}] {item['section']} - 题{item['q']}: {item['hint']}")
    print(f"      答案: {item['ans'] or '(未作答)'}")

conn.close()
