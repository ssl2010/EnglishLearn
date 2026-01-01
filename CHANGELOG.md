# Changelog

## [Unreleased] - 2026-01-01

### Added
- **AI自动批改功能**：集成百度OCR和OpenAI Vision API实现试卷自动识别和批改
  - 支持单词、短语、句子三种题型识别
  - 自动判断正确性并生成批改标记（✓/✗）
  - 支持多页试卷识别，准确定位每道题所在页面
  - 生成带批改标记的图片供家长查看
  - 提取试卷日期信息用于练习单匹配

- **OCR集成** (`backend/app/baidu_ocr.py`)
  - 百度OCR API集成
  - 支持手写+印刷混合识别
  - 文档分析模式优化试卷识别

- **AI配置** (`backend/app/ai_config.json`)
  - LLM提示词配置，支持结构化JSON输出
  - OCR参数配置
  - 优化后的提示词减少40%字符，提升效率

- **前端交互优化** (`frontend/submit.html`)
  - 识别结果实时预览
  - 支持逐题确认正确性
  - 批改后图片替换原缩略图
  - 未作答题目显示"查看练习单"链接
  - 页面缩略图点击查看完整图片
  - 显示提取的试卷日期

### Changed
- **批改标记优化**：
  - 正确答案：绿色✓标记在答案右侧
  - 错误答案：红色椭圆圈住答案区域
  - 未作答：橙色矩形框标记位置

- **环境变量配置** (`.env.example`)
  - 添加OpenAI/ARK API配置
  - 添加百度OCR API配置
  - 添加调试开关配置

### Fixed
- **页码识别准确性**：优化LLM提示词，准确识别多页试卷中每道题所在页面
- **数据库约束错误**：修复`confirm_ai_extracted`中position唯一性约束冲突
- **调试模式文件选择问题**：修复调试模式后无法选择新文件的bug
- **OCR匹配精度**：改进OCR文本与题目的模糊匹配算法

### Technical Details
- 新增依赖：`openai`, `baidu-aip` (见 `backend/requirements.txt`)
- API调用流程：并行调用LLM和OCR，合并结果后生成批改图片
- 白平衡预处理：对图片应用白平衡算法提升识别准确度
- 裁剪图片生成：自动裁剪每道题的作答区域保存

### Development Notes
详细的开发文档已移至 `docs/development/` 目录：
- OCR_MATCHING_FIX.md - OCR匹配修复记录
- PROMPT_OPTIMIZATION.md - 提示词优化记录
- DRAWING_IMPROVEMENTS.md - 批改标记改进
- UI_IMPROVEMENTS.md - UI交互优化
- 其他技术文档...

---

## [Previous Releases]
见Git提交历史
