# AI批改功能测试脚本

## 功能说明

`test_ai_grading.py` 是一个自动化测试脚本，用于验证AI批改功能的完整流程：

1. ✅ 检查AI配置（OpenAI/ARK API、百度OCR）
2. ✅ 加载调试目录中的测试图片
3. ✅ 执行完整的AI批改流程（LLM + OCR）
4. ✅ 验证返回结果的结构和完整性
5. ✅ 检查页码标记的准确性
6. ✅ 生成测试报告和详细结果

## 使用方法

### 前提条件

确保已配置好环境变量：
```bash
# .env 文件中需要包含
OPENAI_API_KEY=your_key  # 或 ARK_API_KEY
BAIDU_OCR_API_KEY=your_key
BAIDU_OCR_SECRET_KEY=your_secret
```

### 运行测试

```bash
# 方式1: 从项目根目录运行
python3 tests/test_ai_grading.py

# 方式2: 进入tests目录运行
cd tests
./test_ai_grading.py

# 方式3: 使用可执行权限（从根目录）
./tests/test_ai_grading.py
```

### 测试数据

脚本会优先使用 `tests/fixtures/` 目录中的固定测试图片，如果没有则尝试使用 `backend/media/uploads/debug_last/` 中的调试数据。

测试图片已包含在版本控制中，无需额外准备即可运行测试。

## 输出说明

### 控制台输出

测试脚本会在控制台输出详细的测试过程，使用颜色标记：
- 🟢 **绿色** ✓：测试通过
- 🔴 **红色** ✗：测试失败
- 🟡 **黄色** ⚠：警告信息
- 🔵 **蓝色** ℹ：提示信息

示例输出：
```
==========================================================
AI批改功能测试
==========================================================

=== 测试AI配置 ===
✓ AI配置正常
✓ 百度OCR配置正常

=== 加载测试图片 ===
ℹ 使用测试数据目录: tests/fixtures
✓ 加载图片 1: input_1.jpg (105476 bytes)
✓ 加载图片 2: input_2.jpg (146209 bytes)
ℹ 共加载 2 张图片

=== 执行AI批改 ===
ℹ 正在调用LLM和OCR...
✓ AI批改完成

=== 验证返回结果 ===
✓ 字段存在: items
✓ 字段存在: image_urls
✓ 字段存在: graded_image_urls
✓ 字段存在: image_count
ℹ 识别到 29 道题目
✓ 题目结构正确
ℹ 题目分布在 2 个页面: [0, 1]
✓ 提取到试卷日期: 2025-12-26
ℹ 未匹配到练习单

=== 题目摘要 ===

一、单词默写(15个)
  题目数: 15
  正确: 11, 错误: 4, 未知: 0
  页面分布: {0: 5, 1: 10}

二、短语默写（8个）
  题目数: 8
  正确: 0, 错误: 8, 未知: 0

三、句子默写（6个）
  题目数: 6
  正确: 0, 错误: 6, 未知: 0

=== 检查页码准确性 ===
ℹ Page 0: 15 道题
ℹ Page 1: 14 道题
✓ 页码分布看起来合理

==========================================================
测试完成！
==========================================================
ℹ 详细结果已保存到: test_ai_grading_result.json
```

### 结果文件

测试完成后会在 `tests/` 目录生成 `test_ai_grading_result.json`，包含完整的识别结果：

```json
{
  "items": [
    {
      "position": 1,
      "section_type": "WORD",
      "section_title": "一、单词默写(15个)",
      "zh_hint": "尾巴",
      "llm_text": "tail",
      "is_correct": true,
      "confidence": 1.0,
      "page_index": 1,
      ...
    }
  ],
  "image_urls": [...],
  "graded_image_urls": [...],
  "image_count": 2,
  "extracted_date": "2025-12-26"
}
```

## 检查项说明

### 1. AI配置检查
- 验证 OpenAI/ARK API 密钥是否配置
- 验证百度OCR密钥是否配置

### 2. 结果结构验证
- 检查必需字段是否存在
- 验证题目数组结构
- 检查题目基本字段完整性

### 3. 页码准确性检查
- 检查题目是否分布在多个页面
- 警告所有题目都在同一页的情况（多页试卷）
- 显示页面分布统计

### 4. 数据提取验证
- 验证试卷日期提取
- 验证练习单匹配结果
- 统计各section的正确率

## 故障排查

### 配置错误
```
✗ AI配置不可用，缺少API密钥
```
**解决**: 检查 `.env` 文件，确保配置了 `OPENAI_API_KEY` 或 `ARK_API_KEY`

### 找不到测试图片
```
✗ 未找到测试图片目录
```
**解决**:
- 测试图片应该已包含在 `tests/fixtures/` 目录中
- 如果缺失，从 `backend/media/uploads/debug_last/` 复制或重新运行前端识别

### API调用失败
```
✗ AI批改失败: LLM 识别失败: ...
```
**解决**:
1. 检查API密钥是否正确
2. 检查网络连接
3. 查看详细错误堆栈

### 页码识别问题
```
⚠ 所有 29 道题都标记在同一页，可能存在页码识别问题
```
**解决**: 这表明LLM可能没有正确识别多页试卷，需要：
1. 检查提示词配置 (`ai_config.json`)
2. 验证图片质量和清晰度
3. 考虑重新测试或调整提示词

## 注意事项

1. **不会入库**: 此测试脚本仅用于验证功能，不会将结果写入数据库
2. **使用真实API**: 测试会调用真实的OpenAI和百度OCR API，会产生费用
3. **测试数据**: 使用 `tests/fixtures/` 中的固定测试图片，已包含在版本控制中
4. **结果文件**: 每次测试会覆盖之前的 `tests/test_ai_grading_result.json`

## 集成到CI/CD

可以将此脚本集成到持续集成流程中：

```yaml
# .github/workflows/test.yml
- name: Test AI Grading
  run: |
    python3 test_ai_grading.py
  env:
    OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
    BAIDU_OCR_API_KEY: ${{ secrets.BAIDU_OCR_API_KEY }}
    BAIDU_OCR_SECRET_KEY: ${{ secrets.BAIDU_OCR_SECRET_KEY }}
```

## 扩展测试

如果需要测试不同的图片：

1. 将新图片复制到 `tests/fixtures/` 目录
2. 命名为 `input_1.jpg`, `input_2.jpg` 等
3. 运行测试脚本
4. （可选）提交到版本控制：`git add -f tests/fixtures/*.jpg`

---

**相关文档**:
- [项目结构说明](PROJECT_STRUCTURE.md)
- [变更日志](CHANGELOG.md)
