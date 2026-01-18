# Changelog

所有重要的变更都会记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [2.1.0] - 2026-01-18

### Added
- 家长看板 V2 接口：`/api/dashboard/overview` 与 `/api/dashboard/student`，提供多学生概览与学习库聚合统计
- 看板双态页面：全部学生概览 + 单学生详情（资料库掌握、近期练习、易错）
- 提交/批改在 ALL 模式下可通过练习单编号解析学生与资料库后入库

### Changed
- 应用默认进入 ALL 概览，学生选择在不同页面按需显示/限制
- 练习单管理支持 ALL 模式查询当前账号下所有学生
- 近期练习链接统一跳转到 `practice-view.html`

### Fixed
- ALL/单学生切换在跨页面时状态不同步的问题
- 学生管理编辑区布局与操作区域一致性

## [2.0.0] - 2026-01-01

### Added

#### AI自动批改核心功能
- **LLM + OCR双引擎识别**：集成百度OCR和OpenAI Vision API实现试卷自动识别和批改
  - 支持单词、短语、句子三种题型识别
  - 自动判断正确性并生成批改标记（✓/✗）
  - 支持多页试卷识别，准确定位每道题所在页面
  - 并行调用LLM和OCR，提升识别准确度和速度
  - LLM与OCR一致性检查，对不一致结果给出警告
  - 生成带批改标记的图片供家长查看
  - 提取试卷日期信息用于练习单匹配

#### 后端集成
- **OCR集成** (`backend/app/baidu_ocr.py`)
  - 百度OCR API集成
  - 支持手写+印刷混合识别
  - 文档分析模式优化试卷识别
  - 白平衡预处理提升识别准确度

- **AI配置** (`backend/app/ai_config.json`)
  - LLM提示词配置，支持结构化JSON输出
  - OCR参数配置
  - 优化后的提示词减少40%字符，提升效率

- **裁剪缩略图生成**
  - 自动裁剪每道题的作答区域保存为crop图片
  - 支持客户端和服务端两种生成方式
  - 在识别结果表中显示答案缩略图，点击放大查看

#### 前端交互优化 (`frontend/submit.html`)
- **照片上传与预览**
  - 支持多张照片上传
  - 缩略图预览，可删除和继续添加
  - 批改后图片自动替换原缩略图（绿色边框标识）

- **识别结果展示**
  - Section分组显示（单词/短语/句子）
  - 逐题显示识别结果和参考答案
  - 彩色行背景：绿色=正确，红色=错误
  - 拼写错误单词红色高亮显示（短语/句子题型）
  - 一致性警告提示（LLM与OCR结果不一致时）
  - 答案裁剪缩略图（点击放大查看）
  - 未作答题目显示"查看练习单"链接

- **交互操作**
  - 点击✓/✗图标切换正确性
  - 勾选框控制是否入库
  - 图片缩放查看（点击任意图片）
  - **图片拖拽功能**：放大图片支持鼠标拖拽调整位置
  - **智能定位**：放大图片显示在鼠标左上角（图片右下角对齐鼠标）
  - 显示提取的试卷日期和匹配的练习单

- **调试模式**
  - "模拟运行"按钮加载上次调试数据
  - 无需真实API调用即可测试UI

#### 测试基础设施
- **自动化测试脚本** (`tests/test_ai_grading.py`)
  - 验证AI配置（OpenAI/ARK、百度OCR）
  - 加载测试图片（优先fixtures，降级debug_last）
  - 执行完整AI批改流程
  - 验证结果结构和页码准确性
  - 生成彩色测试报告
  - 保存详细结果到JSON文件

- **固定测试数据** (`tests/fixtures/`)
  - 包含真实试卷样本（2页，29题）
  - 测试多页识别、页码准确性、多题型混合
  - 已纳入版本控制，测试可独立运行
  - 详见 `docs/TEST_AI_GRADING.md`

#### 项目文档完善
- **项目结构文档** (`PROJECT_STRUCTURE.md`)
  - 完整的目录结构说明
  - 核心功能模块介绍
  - 配置文件说明
  - 开发和测试流程指南

- **功能规格说明** (`docs/SPEC.md`)
  - 详细的功能需求和实现方案

- **测试指南** (`docs/TEST_AI_GRADING.md`)
  - 测试脚本使用方法
  - 输出说明和故障排查
  - CI/CD集成示例

- **Claude Code指南** (`CLAUDE.md`)
  - 项目运行方法
  - 开发约定和注意事项

### Changed

- **批改标记优化**
  - 正确答案：绿色✓标记在答案右侧
  - 错误答案：红色椭圆圈住答案区域
  - 未作答：橙色矩形框标记位置
  - 标记大小和位置根据BBox自动调整

- **环境变量配置** (`.env.example`)
  - 添加OpenAI/ARK API配置
  - 添加百度OCR API配置
  - 添加调试开关配置 `EL_AI_DEBUG_SAVE`

- **提示词优化**
  - 字符数减少约40%，从1200+降至700+
  - 提升API调用效率，降低成本
  - 保持识别准确率不变

### Fixed

- **页码识别准确性**：优化LLM提示词，准确识别多页试卷中每道题所在页面
- **数据库约束错误**：修复`confirm_ai_extracted`中position唯一性约束冲突
- **调试模式文件选择问题**：修复调试模式后无法选择新文件的bug
- **OCR匹配精度**：改进OCR文本与题目的模糊匹配算法
- **题目排序问题**：修复跨section题目排序错误，按section内position正确排序
- **页码顺序问题**：支持用户任意上传页面顺序，自动识别题目所在页面
- **图片显示位置**：修复放大图片显示位置，改为显示在鼠标左上角
- **测试脚本环境变量**：修复测试脚本未加载.env文件的问题

### Technical Details

- **新增依赖**：`openai`, `baidu-aip`, `python-dotenv` (见 `backend/requirements.txt`)
- **API调用流程**：
  1. 并行调用LLM Vision API和百度OCR
  2. LLM解析题目结构和答案
  3. OCR提供文字定位信息(BBox)
  4. 合并LLM和OCR结果
  5. 生成批改标记图片
  6. 裁剪单题缩略图
- **白平衡预处理**：对图片应用白平衡算法提升OCR识别准确度
- **BBox匹配算法**：基于Y坐标+模糊文本匹配实现LLM与OCR结果关联
- **一致性检查**：对比LLM和OCR识别的文本，标记不一致项供人工复核

### Development Notes

详细的开发文档已组织至 `docs/development/` 目录：
- `OCR_MATCHING_FIX.md` - OCR匹配修复记录
- `PROMPT_OPTIMIZATION.md` - 提示词优化记录
- `DRAWING_IMPROVEMENTS.md` - 批改标记改进
- `UI_IMPROVEMENTS.md` - UI交互优化
- `QUESTION_ORDERING_FIX.md` - 题目排序修复
- `GRADING_MARKS_UPDATE.md` - 批改标记更新
- `FIXES_SUMMARY.md` - 修复汇总
- `CACHE_REFRESH_GUIDE.md` - 缓存刷新指南

### Migration Guide

如需从旧版本迁移：

1. **安装新依赖**：
   ```bash
   pip install -r backend/requirements.txt
   ```

2. **配置API密钥** (`.env`):
   ```bash
   # 二选一
   OPENAI_API_KEY=sk-xxx
   # 或
   ARK_API_KEY=xxx
   ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3

   # 百度OCR
   BAIDU_OCR_API_KEY=xxx
   BAIDU_OCR_SECRET_KEY=xxx

   # 可选：启用调试模式
   EL_AI_DEBUG_SAVE=1
   ```

3. **测试AI批改功能**：
   ```bash
   python3 tests/test_ai_grading.py
   ```

---

## [1.0.0] - 2025-12-30

### Initial Release

- 练习单生成功能
- 手动批改功能
- 统计面板
- 知识库管理
- SQLite数据库存储
- PDF生成功能

---

## 贡献指南

本项目使用 [Claude Code](https://claude.com/claude-code) 辅助开发。

如需贡献代码，请参考：
- `CLAUDE.md` - 项目开发指南
- `PROJECT_STRUCTURE.md` - 项目结构说明
- `docs/SPEC.md` - 功能规格说明
