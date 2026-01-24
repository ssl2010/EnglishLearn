# English Learning - 英语学习系统

一个面向小学生的英语默写练习与智能批改系统，支持多资料库学习、AI辅助批改和学习进度跟踪。

## 核心功能

### 1. 学习库管理
- **多资料库支持**：学生可同时使用多个资料库（系统课本 + 自定义词库）
- **学习进度跟踪**：为每个资料库设置当前学习进度（按单元）
- **系统课本**：内置人教版等标准教材
- **自定义资料库**：家长可创建并导入自己的词汇表

### 2. 智能练习单生成
- **灵活出题范围**：
  - 学习进度内（推荐）：根据设置的学习进度自动计算范围
  - 全部单元：不限单元范围
  - 自定义单元：手动指定单元
- **题型混合**：支持单词、短语、句子三种题型及比例配置
- **难度筛选**：可按"会写"、"会认"要求筛选词条
- **随机扰动选题**：相同范围重新生成也能得到不同题目
- **PDF导出**：一键生成题目单和答案单

### 3. AI智能批改
- **双引擎识别**：
  - LLM视觉识别（OpenAI GPT-4o / 字节ARK）：理解试卷结构和批改标记
  - OCR文字识别（百度OCR）：精确定位答案位置
- **并行处理**：LLM和OCR同时工作，结果交叉验证提高准确率
- **可视化反馈**：
  - 自动绘制批改标记（红叉/绿勾）
  - 生成答案裁剪图
  - 支持多页试卷识别
- **人工确认**：识别结果可编辑，确认后才入库

### 4. 手动批改
- **纸质批改**：家长在试卷上标记错误（推荐只标错）
- **拍照上传**：拍摄批改后的试卷
- **手动录入**：可手动输入学生答案进行批改

### 5. 练习单管理
- **历史练习单列表**：按时间、UUID、知识点筛选
- **分页与删除**：支持删除历史练习单
- **练习单查看**：展示批改详情、原图/缩略图、批改图
- **PDF重新生成**：在查看页重新生成并下载题目单/答案单

### 6. 学习统计与看板
- **掌握度跟踪**：基于连续正确次数判断词汇掌握情况
- **易错统计**：自动记录高频错误词汇
- **练习日历**：可视化练习历史
- **学习进展**：已学/已掌握词汇数量统计

## 快速开始

### 1. 安装依赖

```bash
cd backend
pip install -r requirements.txt
```

### 2. 配置环境变量（可选）

复制 `.env.example` 为 `.env`，配置API密钥：

```bash
# OpenAI API（用于AI批改）
OPENAI_API_KEY=your_key

# 或使用字节ARK API
ARK_API_KEY=your_key
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3

# 百度OCR API（用于辅助定位）
BAIDU_OCR_API_KEY=your_key
BAIDU_OCR_SECRET_KEY=your_secret

# 调试模式（保存AI识别原始数据）
EL_AI_DEBUG_SAVE=1

# 管理员账号（首次启动需设置）
EL_ADMIN_USER=admin
EL_ADMIN_PASS=your_admin_password

# AI配置文件（默认使用仓库根目录的 ai_config.json）
EL_AI_CONFIG_PATH=./ai_config.json

# 自动清理任务（北京时间）
EL_CLEANUP_TIME=03:00
EL_CLEANUP_INTERVAL_DAYS=1
EL_CLEANUP_UNDOWNLOADED_DAYS=14
```

### 3. 初始化数据库

```bash
cd backend
python3 init_db.py
```

系统会自动创建数据库并加载示例资料库（人教版PEP教材）。

**如果是升级现有系统**，需要运行数据库迁移：

```bash
cd backend
python3 migration_manager.py migrate
```

查看迁移状态：

```bash
python3 migration_manager.py status
```

### 4. 启动服务

```bash
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 5. 访问系统

打开浏览器访问：http://localhost:8000/login.html

- **应用壳**：统一导航入口（顶部选择学生/学习库）
- **学习库管理**：添加/管理资料库，设置学习进度
- **生成练习单**：创建默写练习并导出PDF
- **提交与批改**：上传试卷照片进行AI批改
- **学习统计**：查看学习进展和易错分析

## 使用流程

### 首次使用
1. 访问首页，输入学生姓名和年级完成初始化
2. 系统自动添加默认资料库到学习库
3. 前往"学习库管理"添加更多资料库或设置学习进度

### 日常使用
1. **管理学习库**
   - 在学习库管理页面选择系统课本或创建自定义资料库
   - 为每个资料库设置当前学习进度（如"Unit 3"）
   - 可以启用/禁用资料库

2. **生成练习单**
   - 选择资料库和出题范围
   - 设置题量和题型比例
   - 下载PDF并打印给孩子练习

3. **批改提交**
   - **推荐方式**：家长在纸质试卷上批改（只标错），拍照上传
   - 系统AI自动识别对错，家长确认后提交
   - 或选择手动录入答案方式

4. **查看进展**
   - 访问统计看板查看学习进展
   - 了解掌握情况和易错词汇
   - 参考练习日历合理安排学习

## AI批改说明

### 工作原理
系统采用LLM+OCR双引擎并行识别：
- **LLM视觉识别**：理解试卷整体结构、题目分区、批改标记
- **OCR文字识别**：精确识别手写答案的文字内容
- **交叉验证**：两个引擎结果互相验证，提高准确率

### 批改建议
- 家长先在纸质试卷上批改（**只标错**：红叉/圈错/划线）
- 正确的题目留空不标记
- 拍照时保持光线充足、避免反光
- AI识别结果仅供参考，请家长确认后再提交

### 调试模式
开启 `EL_AI_DEBUG_SAVE=1` 后，每次识别会保存原始数据到 `backend/media/uploads/debug_last/`，方便调试。

## 系统配置

### 掌握阈值
默认连续正确2次视为掌握，可在首页调整（1-10次）。

### 学习进度
- **Unit 3**：表示学到Unit 3，出题范围为Unit 1-3
- **全部**：不限单元或已学完全部
- **未设置**：尚未设置进度

## 测试

运行AI批改功能测试：
```bash
cd tests
python3 test_ai_grading.py
```

测试会使用 `tests/fixtures/` 中的固定测试数据验证AI批改功能。

## 数据导入

### 导入资料库
支持JSON格式批量导入词条：
```json
{
  "items": [
    {
      "zh_text": "苹果",
      "en_text": "apple",
      "unit": "Unit 1",
      "item_type": "WORD",
      "difficulty_tag": "write"
    }
  ]
}
```

如需导入封面，可在 `assets` 中提供 `id="cover"` 的 base64 图片数据。

基准导入测试文件：`C:\temp\Join in G4 with cover.json`（包含封面与单元元数据）。

参考 `seed/` 目录中的示例文件。

## 项目结构

详见 `docs/PROJECT_STRUCTURE.md` 文档。

## 文档

- `README.md` - 本文件，项目概述和使用指南
- `docs/PROJECT_STRUCTURE.md` - 项目结构说明
- `docs/LEARNING_LIBRARY_COMPLETE.md` - 学习库系统完整文档
- `docs/FEATURES.md` - 功能要点清单
- `backend/DATABASE.md` - 数据库说明
- `docs/UUID_DUPLICATE_DETECTION.md` - UUID识别与重复检测说明
- `docs/CHANGELOG.md` - 变更日志
- `docs/SPEC.md` - 功能规格说明
- `docs/TEST_AI_GRADING.md` - AI批改测试文档
- `docs/development/` - 开发文档和技术笔记
- `CLAUDE.md` - Claude Code 项目指南

## 技术栈

- **后端**：FastAPI + SQLite
- **前端**：原生HTML/CSS/JavaScript
- **AI**：OpenAI GPT-4o / 字节ARK Vision API
- **OCR**：百度OCR
- **PDF生成**：ReportLab

## License

MIT
