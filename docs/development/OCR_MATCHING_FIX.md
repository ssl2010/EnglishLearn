# OCR-LLM Matching 修复总结

**日期**: 2025-12-31

## 问题描述

用户报告了两个匹配问题：

### 问题1：两道题的手写识别被合并显示
- **现象**: "13.猪" (pig) 和 "14.马" (horse) 的OCR识别框在一起，显示时也合并在一栏
- **根本原因**: `_build_ocr_lines()` 函数使用过宽松的合并阈值 (line_height * 0.6)，将print文本（题目）和handwriting文本（答案）混合合并
- **具体情况**: Pig (top=732, height=79) 和 horse (top=778) 垂直距离46px < 79*0.6=47.4px，因此被合并成一行 `'13.猪: Pig horse'`

### 问题2：存在未作答题目时匹配错位
- **现象**: 当学生有未做答的题目时，OCR和LLM匹配出现错位
- **根本原因**:
  - LLM识别所有24道题（包括空题）
  - OCR只识别14个手写答案
  - 当前匹配逻辑使用sequential fallback（顺序匹配），遇到空题时序号错位

## 解决方案

### 修改1：分离handwriting和print文本 (backend/app/services.py:771-799)

**修改内容**:
- `_build_ocr_lines()` 现在只处理handwriting类型的单词（学生答案）
- 不再将print文本（题目）和handwriting文本（答案）混合合并
- 使用更严格的合并阈值（0.4而不是0.6），可通过环境变量 `EL_OCR_HANDWRITING_MERGE_THRESHOLD` 配置

**代码变更**:
```python
# 只提取handwriting单词
handwriting_words = []
for wobj in words:
    if wobj.get("words_type") != "handwriting":
        continue
    # ... 提取位置信息

# 使用更严格的阈值
merge_threshold = float(os.environ.get("EL_OCR_HANDWRITING_MERGE_THRESHOLD", "0.4"))
lines = _merge_words_to_lines(handwriting_words, merge_threshold=merge_threshold)
```

### 修改2：添加position-based matching (backend/app/services.py:815-936)

**新增功能**:
1. **提取题目位置**: 从OCR的print文本中提取题号和位置（如 "13.猪:" → Q13 at top=740）
2. **三策略匹配**（按优先级）:
   - **Strategy 1**: 文本相似度匹配（ratio ≥ 0.6） - 最高优先级
   - **Strategy 2**: 基于位置匹配（找到距离题目最近的OCR答案，100px以内） - 中优先级
   - **Strategy 3**: 顺序fallback - 最低优先级
3. **跳过空答案**: LLM识别为空的题目不参与OCR匹配

**代码变更**:
```python
# 提取题目位置
question_positions_by_page: Dict[int, Dict[int, float]] = {}
for page_idx, words in ocr_by_page.items():
    questions = _extract_question_positions(words)
    question_positions_by_page[page_idx] = {q["q_num"]: q["top"] for q in questions}

# 匹配时优先使用position-based
if q_num in q_positions:
    expected_top = q_positions[q_num]
    # 找到距离最近的OCR行
    for idx_ln, ln in enumerate(lines):
        dist = abs(ln_top - expected_top)
        if dist < closest_dist and dist < 100:
            closest_idx = idx_ln
```

### 修改3：新增辅助函数 (backend/app/services.py:19-110)

添加了三个新的辅助函数：

1. **`_extract_question_number(text: str) -> Optional[int]`**
   - 从文本中提取题号（支持 "13.猪:", "2农场;", 等格式）
   - 使用正则表达式匹配数字+分隔符 或 数字+汉字

2. **`_extract_question_positions(words: List[Dict]) -> List[Dict]`**
   - 从OCR的print文本中提取所有题目的位置信息
   - 返回按垂直位置排序的题目列表

3. **`_merge_words_to_lines(words: List[Dict], merge_threshold: float) -> List[Dict]`**
   - 通用的单词合并函数，支持自定义合并阈值
   - 被 `_build_ocr_lines()` 调用

## 测试验证

### 测试1: OCR行分离测试
**测试脚本**: `test_ocr_line_merge.py`

**结果**:
```
Before fix: Line text: '13.猪: Pig horse' (merged)
After fix:  Line 11: 'Pig'
           Line 12: 'horse'
✓ SUCCESS: Pig and horse are in SEPARATE lines
```

### 测试2: 完整匹配测试
**测试脚本**: `test_improved_matching.py`

**关键结果**:
- ✓ 所有14个手写答案都被识别为独立的OCR行
- ✓ Pig和horse正确分离
- ✓ 题号提取成功（Q1-Q15）
- ✓ 空答案（Q6, Q16-Q24）不参与OCR匹配

### 测试3: 实际数据验证
**测试脚本**: `analyze_matching_issue.py`

**匹配结果示例**:
```
Q#   Status  LLM Text        OCR Text        Match Method
1    ✗       tail            teil            text_similarity_0.75
13   ✓       pig             Pig             text_similarity_1.00
14   ✓       horse           horse           text_similarity_1.00
6    ✓                                       empty_answer
16   ✓                                       empty_answer
```

## 配置选项

新增环境变量：

```bash
# OCR handwriting合并阈值（默认0.4，越小越严格）
EL_OCR_HANDWRITING_MERGE_THRESHOLD=0.4
```

现有环境变量保持不变：
```bash
# OCR文本相似度匹配阈值（默认0.6）
EL_OCR_MATCH_THRESHOLD=0.6

# LLM-OCR一致性检查阈值（默认0.88）
EL_MATCH_SIM_THRESHOLD=0.88
```

## 预期效果

### Before (修复前)
- OCR行: `'13.猪: Pig horse'` (合并)
- Q13匹配到 "Pig horse" → 错误
- Q14找不到OCR匹配 → 顺序fallback → 错位

### After (修复后)
- OCR行: `'Pig'`, `'horse'` (分离)
- Q13通过position匹配到 "Pig" → 正确
- Q14通过position匹配到 "horse" → 正确
- Q6 (未作答) 不参与OCR匹配 → 保持空

## 向后兼容性

- ✓ 现有会话数据不受影响（已存储在数据库）
- ✓ 只影响新提交的批改
- ✓ 无需数据库迁移
- ✓ 保持现有API接口不变

## 相关文件

### 修改的文件
- `backend/app/services.py` - 核心修改

### 新增的测试文件
- `test_ocr_line_merge.py` - 测试OCR行合并
- `test_improved_matching.py` - 测试改进的匹配逻辑
- `analyze_matching_issue.py` - 分析匹配问题

### 文档更新
- `SPEC.md` - 添加OCR-LLM匹配改进说明

## 下一步建议

1. **在实际环境测试**: 使用真实的学生作业照片测试新的匹配逻辑
2. **监控match_method字段**: 观察哪种匹配策略使用最多
3. **调整阈值**: 如果发现position-based匹配效果不佳，可调整100px的距离阈值
4. **考虑多页情况**: 当前实现假设题目和答案在同一页，多页场景需要额外处理
