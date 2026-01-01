# UI和匹配逻辑改进总结

**日期**: 2025-12-31

## 实现的改进

### 1. OCR合并逻辑改进 ✓

**问题**：单词部分不应该合并，但短语/句子需要合并

**解决方案**：
- 修改 `_build_ocr_lines()` 函数，检测LLM结果中是否有多单词答案
- 单词部分：使用极小阈值（0.1）禁止合并
- 短语/句子部分：使用中等阈值（0.5）允许有限合并
- 新增环境变量：
  - `EL_OCR_WORD_MERGE_THRESHOLD=0.1` - 单词合并阈值（默认0.1）
  - `EL_OCR_PHRASE_MERGE_THRESHOLD=0.5` - 短语合并阈值（默认0.5）

**代码位置**: backend/app/services.py:775-821

### 2. UI列调整 ✓

**删除的列**：
- ~~OCR识别~~ - 不再显示
- ~~采信~~ - 不再需要选择（统一使用LLM）
- ~~手动输入~~ - 不再显示

**保留的列**：
- 题号
- 题目/提示
- LLM识别（当与OCR不一致时标红）
- 是否正确
- 入库
- 置信度
- 备注
- **识别图片**（新增）

**代码位置**: frontend/submit.html:194-237

### 3. LLM-OCR不一致高亮 ✓

**实现**：
- 当 `consistency_ok === false` 时，LLM识别文本显示为红色（#e5484d）
- 使用较粗字体（font-weight: 500）增强视觉效果
- 整行背景仍然保持淡红色（#ffecec）

**代码示例**：
```javascript
const llmOcrMatch = it.consistency_ok !== false;
const llmTextColor = llmOcrMatch ? '#333' : '#e5484d';
const llmTextStyle = `color:${llmTextColor};font-weight:${llmOcrMatch ? 'normal' : '500'}`;
```

**代码位置**: frontend/submit.html:207-210

### 4. 识别图片缩略图 ✓

**实现**：
- 最后一列显示识别到的手写答案的裁剪缩略图（80x40px）
- 使用Canvas从原始上传图片中裁剪bbox区域
- 添加10px padding使裁剪更完整
- 点击缩略图可放大查看
- ESC键或点击模态框关闭放大图

**关键功能**：
```javascript
function generateCropThumbnails() {
  // 从上传的原始图片中裁剪bbox区域
  // 使用Canvas生成缩略图
  // 支持normalized bbox坐标（0-1）
}

function showImageModal(src) {
  // 显示放大图
  // ESC键关闭（已实现）
}
```

**代码位置**: frontend/submit.html:267-325

## 关于人工修正LLM错误的建议

### 当前流程限制

目前UI已删除"采信"和"手动输入"列，统一使用LLM识别结果。这意味着：

**优点**：
- UI简洁，家长操作简单
- 减少选择困惑
- 提高批改效率

**缺点**：
- 当LLM识别错误时，无法直接修正
- 只能通过"是否正确"标记错误，但不能更正答案

### 建议的修正方案

#### 方案1：添加行内编辑功能（推荐）

**实现方式**：
- LLM识别列改为可编辑的input框（初始值为LLM文本）
- 当LLM和OCR不一致时，input框边框显示红色提醒
- 家长可以直接修改文本
- 修改后的文本作为最终的student_text提交

**优点**：
- UI保持简洁
- 支持直接修正
- 符合直觉

**实现难度**：低

**代码示例**：
```html
<td>
  <input type="text"
         data-pos="${it.position}"
         data-role="llm-edit"
         value="${llmText}"
         style="border:1px solid ${llmOcrMatch ? '#ddd' : '#e5484d'};padding:4px;width:100%"
         placeholder="LLM识别" />
</td>
```

#### 方案2：双击编辑模式

**实现方式**：
- 默认显示LLM文本（不可编辑）
- 双击LLM识别列进入编辑模式
- 编辑完成后回车或失焦保存
- 显示"已修改"标识

**优点**：
- 正常流程无需编辑，界面更简洁
- 仅在需要时才编辑
- 支持撤销

**实现难度**：中

#### 方案3：使用缩略图辅助判断（已实现）

**当前实现**：
- 识别图片列显示手写答案的裁剪图
- 家长可以对照缩略图判断LLM识别是否正确
- 如果错误，标记"是否正确"为×

**配合方案1使用**：
- 家长看缩略图发现LLM识别错误
- 直接在input框中修正
- 最佳用户体验

### 推荐实施路径

**短期（立即）**：
- 当前方案（LLM文本不可编辑 + 缩略图辅助判断）
- 适用于LLM准确率高的场景

**中期（优化）**：
- 实施方案1：添加行内编辑
- 5-10行代码即可实现
- 显著提升用户体验

**长期（完善）**：
- 添加修改历史记录
- 统计LLM vs 人工修正的比率
- 用于评估LLM性能

## 实现方案1的代码片段

如果你想立即添加行内编辑功能，可以这样修改：

**frontend/submit.html line 225**：
```javascript
// 原代码：
<td><span style="${llmTextStyle}">${llmText}</span></td>

// 改为：
<td>
  <input type="text"
         class="llm-edit"
         data-pos="${it.position}"
         value="${llmText}"
         style="width:100%;padding:4px;border:1px solid ${llmOcrMatch ? '#ddd' : '#e5484d'};border-radius:4px;font-size:14px" />
</td>
```

**frontend/submit.html confirmMarks()函数**：
```javascript
const items = window._extracted.map(it=>{
  // 获取可能被修改的LLM文本
  const editedInput = document.querySelector(`.llm-edit[data-pos="${it.position}"]`);
  const finalText = editedInput ? editedInput.value : it.llm_text;

  return {
    position: it.position,
    zh_hint: it.zh_hint || '',
    student_text: finalText,  // 使用编辑后的文本
    llm_text: it.llm_text || '',  // 保留原始LLM文本用于对比
    ocr_text: it.ocr_text || '',
    matched_item_id: it.matched_item_id || null,
    include: includeMap[it.position] !== false,
    is_correct: !!correctMap[it.position],
    source: 'llm'  // 或者如果被修改了可以改为 'manual'
  };
});
```

## 文件清单

**后端修改**：
- backend/app/services.py:775-821 - OCR合并逻辑改进
- backend/app/services.py:847 - 传入items参数

**前端修改**：
- frontend/submit.html:132-133 - 保存上传图片
- frontend/submit.html:194-237 - 表格UI改进
- frontend/submit.html:267-325 - 缩略图生成和显示
- frontend/submit.html:327-365 - 简化确认逻辑

**环境变量新增**：
```bash
# OCR合并阈值
EL_OCR_WORD_MERGE_THRESHOLD=0.1        # 单词部分（几乎不合并）
EL_OCR_PHRASE_MERGE_THRESHOLD=0.5      # 短语/句子部分（有限合并）
```

## 测试建议

1. **单词部分测试**：
   - 上传只有单词的练习单
   - 验证每个单词都是独立的OCR行
   - 验证Pig和horse不再合并

2. **短语部分测试**：
   - 上传包含短语的练习单（如"walk the dog"）
   - 验证同一短语的多个单词被正确合并
   - 验证不同短语不会错误合并

3. **UI功能测试**：
   - 验证LLM和OCR不一致时文本显示红色
   - 验证缩略图正确显示
   - 验证点击缩略图可放大
   - 验证ESC键关闭放大图
   - 验证删除"OCR识别"、"采信"、"手动输入"列后流程正常

4. **边界情况测试**：
   - 空答案（学生未作答）
   - 特别长的短语或句子
   - 多页图片
   - bbox为null的情况

## 下一步建议

1. **立即实施**：方案1（行内编辑）- 提升用户体验
2. **性能监控**：记录LLM vs OCR一致性比率
3. **数据收集**：统计人工修正的频率和类型
4. **模型优化**：根据修正数据优化prompt或模型
