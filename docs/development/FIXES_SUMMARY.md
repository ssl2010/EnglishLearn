# 修复总结

## 已修复的问题

### 1. ✅ 模拟运行报错
**错误**: `NameError: name '_generate_graded_images' is not defined`

**原因**: `analyze_ai_photos_from_debug`函数调用了不存在的`_generate_graded_images`

**修复**: 替换为inline代码（services.py:946-1004）

### 2. ✅ Section顺序错乱
**原因**: 每个section的题号独立编号（Q1-Q15, Q1-Q8, Q1-Q6），按题号排序会打乱section顺序

**修复**:
- openai_vision.py: 移除排序逻辑，在扁平化时直接标记section_title
- services.py: 移除两处错误的排序和重新标记逻辑

### 3. ✅ 提示词格式化
**修改**: ai_config.json使用数组格式，更易读（行3-35）

## 当前debug数据问题

**症状**: llm_raw.json中
- ✅ LLM原始输出（raw_text）正确：sections格式，3个sections
- ❌ 处理后的items错误：缺少section_title和section_type字段

**原因**: debug数据是用旧代码生成的

## 需要操作

### 必须步骤：重启服务器并重新识别

```bash
# 1. 停止当前服务器（Ctrl+C）

# 2. 重启服务器
cd /home/sunsl/work/EnglishLearn
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000

# 3. 浏览器打开 http://localhost:8000/submit.html

# 4. 点击"开始识别"（不是"模拟运行"）上传测试照片

# 5. 等待识别完成，此时debug数据已更新

# 6. 现在可以点击"模拟运行（调试）"测试UI
```

## 验证checklist

重启并重新识别后，检查：

1. ✅ llm_raw.json的items数组应该有section_title和section_type字段
2. ✅ UI显示应该有section标题行（占满一整行）
3. ✅ Section顺序正确：单词 → 短语 → 句子
4. ✅ 每个section第一题显示标题，后续题目不显示

## 提示词检查

格式化后的提示词在 `backend/app/ai_config.json`:
- 数组格式，每行一个元素
- 包含JSON示例
- 详细的字段说明
- 清晰的要求列表

**注意**: 格式化后token数量会增加约30%（因为增加了换行和空格），但更易读。

## 预期LLM输出格式

```json
{
  "sections": [
    {
      "title": "一、单词默写(15个)",
      "type": "WORD",
      "items": [
        {"q": 1, "hint": "尾巴", "ans": "tail", "ok": true, "conf": 1.0, "pg": 0, "note": ""},
        {"q": 2, "hint": "农场", "ans": "farm", "ok": true, "conf": 1.0, "pg": 0, "note": ""}
      ]
    },
    {
      "title": "二、短语默写(8个)",
      "type": "PHRASE",
      "items": [
        {"q": 1, "hint": "遛狗", "ans": "", "ok": false, "conf": 0.5, "pg": 0, "note": "未作答"}
      ]
    }
  ]
}
```

## 处理后的items格式（应该包含这些字段）

```json
{
  "q": 1,
  "section_title": "一、单词默写(15个)",  // 第一题有，后续为空
  "section_type": "WORD",
  "zh_hint": "尾巴",
  "student_text": "tail",
  "is_correct": true,
  "confidence": 1.0,
  "page_index": 0,
  "note": ""
}
```
