# 测试数据 (Test Fixtures)

此目录包含用于自动化测试的固定测试数据。

## 文件说明

### 图片文件
- `input_1.jpg` - 测试试卷第1页（句子默写部分）
- `input_2.jpg` - 测试试卷第2页（单词默写部分）

这些图片是真实的试卷照片样例，用于测试AI批改功能。

## 测试数据特点

**试卷信息**：
- 日期：2025-12-26
- 年级：四年级
- 题型：单词(15个) + 短语(8个) + 句子(6个)
- 页码顺序：已交换（第1页是原第2页，第2页是原第1页）

**测试价值**：
1. 多页试卷识别
2. 页码准确性验证
3. 多题型混合识别
4. 部分作答/未作答情况
5. 拼写错误检测

## 使用方式

测试脚本 `test_ai_grading.py` 会自动从此目录加载图片：

```bash
python3 test_ai_grading.py
```

## 更新测试数据

如需更新测试图片：

```bash
# 复制新的调试图片到fixtures
cp backend/media/uploads/debug_last/input_*.jpg tests/fixtures/

# 添加到git
git add -f tests/fixtures/*.jpg
```

## 注意事项

- 这些图片文件已通过 `git add -f` 强制加入版本控制
- 全局 `.gitignore` 忽略了 `*.jpg`，但 `tests/.gitignore` 中的规则允许跟踪这些测试图片
- 不要在此目录放置真实学生的隐私数据
