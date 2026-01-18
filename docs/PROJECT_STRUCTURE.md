# 项目结构说明

## 目录结构

```
EnglishLearn/
├── ai_config.json             # AI提示词和OCR配置
├── backend/                    # 后端服务
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py            # FastAPI主应用
│   │   ├── db.py              # 数据库操作
│   │   ├── services.py        # 业务逻辑（含AI批改）
│   │   ├── openai_vision.py   # OpenAI/ARK Vision API集成
│   │   ├── baidu_ocr.py       # 百度OCR集成
│   │   ├── pdf_gen.py         # PDF生成
│   │   ├── normalize.py       # 答案标准化
│   │   └── mark_detect.py     # 标记检测
│   ├── migrate_*.py           # 数据库迁移脚本
│   ├── requirements.txt       # Python依赖
│   └── media/                 # 运行时生成的媒体文件（gitignore）
│
├── frontend/                   # 前端页面
│   ├── app.html               # 应用壳（导航 + iframe）
│   ├── index.html             # 引导页
│   ├── login.html             # 登录页
│   ├── generate.html          # 练习单生成
│   ├── submit.html            # 提交与AI批改
│   ├── practice.html          # 练习单管理
│   ├── practice-view.html     # 练习单查看
│   ├── knowledge.html         # 学习库管理
│   ├── library.html           # 资料库列表
│   ├── library-edit.html      # 资料库编辑
│   ├── library-items.html     # 知识点管理
│   ├── profile.html           # 学生信息
│   ├── dashboard.html         # 统计面板
│   ├── grading_shared.js      # 批改页面共享组件
│   └── unit_tabs_shared.js    # 单元切换共享组件
│
├── docs/                       # 文档
│   ├── CHANGELOG.md           # 变更日志
│   ├── FEATURES.md            # 功能要点清单
│   ├── LEARNING_LIBRARY_COMPLETE.md # 学习库系统完整文档
│   ├── PHASE2_SUMMARY.md      # Phase 2 总结
│   ├── PHASE3_SUMMARY.md      # Phase 3 总结
│   ├── PROJECT_STRUCTURE.md   # 本文件
│   ├── SPEC.md                # 功能规格说明
│   ├── TEST_AI_GRADING.md     # AI批改测试文档
│   ├── UUID_DUPLICATE_DETECTION.md # UUID重复检测说明
│   └── development/           # 开发文档
│       ├── OCR_MATCHING_FIX.md
│       ├── PROMPT_OPTIMIZATION.md
│       ├── DRAWING_IMPROVEMENTS.md
│       └── ...
│
├── tests/                      # 测试
│   ├── fixtures/              # 测试数据
│   │   ├── input_1.jpg       # 测试试卷页面1
│   │   ├── input_2.jpg       # 测试试卷页面2
│   │   └── README.md
│   ├── .gitignore            # 允许jpg文件跟踪
│   └── test_ai_grading.py    # AI批改功能测试
│
├── seed/                       # 初始化数据
│   ├── README.md
│   ├── sample_items.json
│   ├── template_example.json
│   ├── complete_example.json
│   └── 4年级上学期英语系统资料.json
│
├── .env.example               # 环境变量模板
├── .gitignore                 # Git忽略配置
├── CLAUDE.md                  # Claude Code项目指南
└── README.md                  # 项目说明
```

## 核心功能模块

### AI自动批改 (`backend/app/`)
- **openai_vision.py**: Vision模型调用，识别试卷题目和答案
- **baidu_ocr.py**: OCR文字识别，辅助答案定位
- **ai_config.json**: AI提示词配置和OCR参数（位于仓库根目录）
- **services.py**: 
  - `analyze_ai_photos()`: 主流程，并行调用LLM和OCR
  - `confirm_ai_extracted()`: 确认并入库识别结果
  - 白平衡处理、批改标记绘制、裁剪图生成

### 前端交互 (`frontend/submit.html`)
- 照片上传预览
- AI识别结果展示（逐题）
- 批改标记实时显示
- 正确性确认和编辑
- 练习单匹配提示

### 自动化测试 (`tests/`)
- **test_ai_grading.py**: AI批改功能完整流程测试
  - 验证AI配置（OpenAI/ARK、百度OCR）
  - 加载测试图片（优先使用fixtures，降级到debug_last）
  - 执行完整AI批改流程
  - 验证结果结构和页码准确性
  - 生成详细测试报告
- **fixtures/**: 固定测试数据（已纳入版本控制）
  - 包含真实试卷样本（2页，29题）
  - 测试多页识别、页码准确性、多题型混合
  - 详见 `docs/TEST_AI_GRADING.md`

## 配置文件

### `.env` (基于 .env.example)
```bash
# OpenAI/ARK API
OPENAI_API_KEY=your_key
# 或
ARK_API_KEY=your_key
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3

# 百度OCR
BAIDU_OCR_API_KEY=your_key
BAIDU_OCR_SECRET_KEY=your_secret

# 数据库
DATABASE_URL=sqlite:///./backend/el.db

# 调试开关
EL_AI_DEBUG_SAVE=1

# AI配置文件
EL_AI_CONFIG_PATH=./ai_config.json

# 自动清理任务
EL_CLEANUP_TIME=03:00
EL_CLEANUP_INTERVAL_DAYS=1
EL_CLEANUP_UNDOWNLOADED_DAYS=14
```

### `ai_config.json`（仓库根目录）
```json
{
  "llm": {
    "freeform_prompt": ["提示词..."]
  },
  "ocr": {
    "provider": "baidu",
    "endpoint": "...",
    "params": {...}
  }
}
```

## 开发流程

1. **环境配置**: 复制 `.env.example` 为 `.env`，填写API密钥
2. **安装依赖**: `pip install -r backend/requirements.txt`
3. **运行后端**: `uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000`
4. **访问前端**: `http://localhost:8000/`

## 测试

运行AI批改功能测试:
```bash
python3 tests/test_ai_grading.py
```

测试会自动:
- 使用 `tests/fixtures/` 中的固定测试数据
- 验证API配置
- 执行完整AI批改流程
- 输出彩色测试报告
- 保存详细结果到 `tests/test_ai_grading_result.json`

详见 `docs/TEST_AI_GRADING.md`

## 调试模式

启用 `EL_AI_DEBUG_SAVE=1` 后，每次识别会保存调试数据到：
- `backend/media/uploads/debug_last/llm_raw.json` - LLM原始输出
- `backend/media/uploads/debug_last/ocr_raw.json` - OCR原始输出
- `backend/media/uploads/debug_last/input_*.jpg` - 输入图片

前端点击"模拟运行"可直接加载调试数据测试UI。

## 注意事项

- `media/` 目录由运行时生成，包含上传图片、批改图片、裁剪图等
- `.vscode/` 和 `.claude/` 为IDE配置，已忽略
- 测试数据保存在 `tests/fixtures/`，已纳入版本控制
- 调试数据保存在 `backend/media/uploads/debug_last/`，不在版本控制中
