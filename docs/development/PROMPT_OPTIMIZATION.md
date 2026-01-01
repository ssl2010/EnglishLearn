# LLM提示词优化 - 精简版本

## 改进目标

1. **减少输入token**（提示词精简）
2. **减少输出token**（缩短字段名）
3. **更通用的结构**（sections嵌套格式）
4. **降低使用成本**

## 新的JSON格式

### 结构设计

```json
{
  "sections": [
    {
      "title": "一、单词默写(15个)",
      "type": "WORD",
      "items": [
        {"q": 1, "hint": "尾巴", "ans": "tail", "ok": true, "conf": 1.0, "pg": 0, "note": "", "bbox": [0.1, 0.2, 0.3, 0.25]},
        {"q": 2, "hint": "农场", "ans": "farm", "ok": true, "conf": 1.0, "pg": 0, "note": "", "bbox": [0.1, 0.26, 0.3, 0.31]}
      ]
    },
    {
      "title": "二、短语默写(8个)",
      "type": "PHRASE",
      "items": [
        {"q": 16, "hint": "遛狗", "ans": "", "ok": false, "conf": 1.0, "pg": 0, "note": "未作答", "bbox": null}
      ]
    }
  ]
}
```

### 优势对比

**之前**：
- 每个题目重复存储 section_type 和 section_title（后续题目为空字符串）
- 字段名冗长：`student_text`, `is_correct`, `confidence`, `zh_hint`, `page_index`
- 扁平化结构，不符合练习单的实际层级

**现在**：
- Section信息只存储一次（title, type）
- 字段名缩短：`ans`, `ok`, `conf`, `hint`, `pg`
- 嵌套结构更清晰，符合"大题-小题"的层级关系

## Token节省估算

### 输入（提示词）

| 版本 | 字符数 | 估算Token |
|------|--------|-----------|
| 旧版 | 2411 | ~600 |
| 新版 | ~600 | ~150 |
| **节省** | **75%** | **75%** |

### 输出（24题示例）

| 字段 | 旧版 | 新版 | 节省 |
|------|------|------|------|
| section_type × 24 | ~240 chars | ~40 chars (3次) | 83% |
| section_title × 24 | ~600 chars | ~60 chars (3次) | 90% |
| zh_hint → hint | zh_hint | hint | 50% |
| student_text → ans | student_text | ans | 70% |
| is_correct → ok | is_correct | ok | 80% |
| confidence → conf | confidence | conf | 50% |
| page_index → pg | page_index | pg | 75% |

**预计总体输出节省**：~40-50%

## 提示词精简策略

### 1. 去掉所有示例
- 之前：包含完整JSON示例（~400字符）
- 现在：仅说明格式（~50字符）
- 节省：~350字符

### 2. 去掉多余空格和换行
- 之前：格式化排版，易读但占空间
- 现在：紧凑格式，用\n分隔
- 节省：~200字符

### 3. 简化说明文字
- 之前：详细解释每个字段的含义和要求
- 现在：最小化必要说明，用=代替冒号
- 节省：~1200字符

### 4. 缩短字段名
- 之前：student_text, is_correct, confidence, zh_hint, page_index
- 现在：ans, ok, conf, hint, pg
- 节省：每个题目 ~30字符

## 实现细节

### 后端兼容性

**openai_vision.py (Line 473-500)**：
- 检测新的 `sections` 格式
- 扁平化为后端期望的 `items` 数组
- 映射短字段名到长字段名
- 保持向后兼容（仍支持旧格式）

```python
# 新格式：sections嵌套
sections = data.get("sections")
if isinstance(sections, list):
    items = []
    for sec in sections:
        sec_title = sec.get("title")
        sec_type = sec.get("type")
        for idx, it in enumerate(sec.get("items", [])):
            items.append({
                "q": it.get("q"),
                "section_title": sec_title if idx == 0 else "",
                "section_type": sec_type,
                "zh_hint": it.get("hint"),
                "student_text": it.get("ans"),
                "is_correct": it.get("ok"),
                "confidence": it.get("conf"),
                "page_index": it.get("pg"),
                # ...
            })
```

### 字段映射表

| 新格式（短） | 旧格式（长） | 说明 |
|------------|------------|------|
| q | q | 题号（保持不变） |
| hint | zh_hint | 中文提示 |
| ans | student_text | 学生答案 |
| ok | is_correct | 是否正确 |
| conf | confidence | 置信度 |
| pg | page_index | 页码 |
| note | note | 备注（保持不变） |
| bbox | handwriting_bbox / line_bbox | 边界框 |

## 完整的新提示词

```
识别英语练习单，输出JSON: {sections:[{title,type,items:[{q,hint,ans,ok,conf,pg,note,bbox}]}]}
字段:
title=大题标题如"一、单词默写(15个)"
type=WORD/PHRASE/SENTENCE/null
q=题号(整数)
hint=中文提示(不含题号如"1.")
ans=学生答案(手写英文)
ok=是否正确(true/false)
conf=置信度(0-1)
pg=页码(0起)
note=备注("未作答"/"拼写错误"等)
bbox=手写区域[x1,y1,x2,y2]归一化坐标0-1
要求:
1.按题号顺序识别,保持连续性
2.识别大题标题(一、二、三、)和类型
3.hint只含中文内容,去掉"1."等题号
4.未作答ans为空,ok=false,note="未作答"
5.判断正确性:考虑拼写/语法/大小写
返回纯JSON,无其他文字。
```

**特点**：
- 单行JSON格式说明（紧凑）
- 用=代替冒号（更短）
- 用\n分隔（避免多余空格）
- 去掉所有示例和多余解释
- 保留核心要求

## 成本估算（以24题为例）

### 旧版
- 输入：~600 tokens
- 输出：~800 tokens
- 总计：~1400 tokens

### 新版
- 输入：~150 tokens
- 输出：~400 tokens
- 总计：~550 tokens

**节省**：~60%

### 按月估算（每天10次识别）
- 旧版：1400 × 10 × 30 = 420,000 tokens/月
- 新版：550 × 10 × 30 = 165,000 tokens/月
- **节省**：255,000 tokens/月

以豆包模型定价（假设￥0.01/1k tokens）：
- 旧版：￥4.2/月
- 新版：￥1.65/月
- **节省**：￥2.55/月（60%）

## 测试建议

1. **重启服务器**（加载新提示词）
2. **上传测试照片**
3. **检查日志**：
   ```
   openai_vision prompt(freeform) chars=~600
   ```
4. **验证结果**：
   - Section标题正确显示
   - 题目顺序正确
   - 所有字段正确映射

## 兼容性说明

- ✅ 完全向后兼容
- ✅ 自动检测新旧格式
- ✅ 前端无需修改
- ✅ 数据库结构无需修改

只需重启服务器即可生效！
