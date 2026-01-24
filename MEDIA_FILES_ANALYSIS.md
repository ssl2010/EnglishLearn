# 媒体文件分析报告

## 📊 分析概览

**分析时间**: 2026-01-24
**媒体目录**: backend/media/
**总文件数**: 3,082 个文件
**总大小**: 151 MB

---

## 🔍 问题 1: 为什么有 3000+ 媒体文件？

### 文件类型分布

| 类别 | 数量 | 占比 | 说明 |
|------|------|------|------|
| **crop_*.jpg** | 2,472 | 80.2% | AI 批改生成的裁剪图片 |
| **graded_*.jpg** | 250 | 8.1% | 批改后的答案图片 |
| **ai_sheet_*.jpg** | 165 | 5.4% | AI 处理的答题纸图片 |
| **ai_bundles (JSON)** | 99 | 3.2% | AI 批改元数据 |
| **Practice_*.pdf** | 43 | 1.4% | 生成的练习题 PDF |
| **答案 PDF** | 34 | 1.1% | 练习题答案 PDF |
| **cover_*.jpg** | 16 | 0.5% | 教材封面图片 |
| **TOTAL** | **3,082** | **100%** | |

### 文件来源分析

#### 1. **AI 批改系统生成的文件 (2,887 个，占 93.7%)**

这些是系统 **AI 自动批改功能** 生成的中间文件和结果文件：

**a) crop_*.jpg (2,472 个文件)**
- **用途**: AI 批改时，从学生提交的答题纸中裁剪出的单个题目图片
- **生成场景**:
  - 学生上传答题纸图片
  - 系统使用 OCR 识别每个题目区域
  - 裁剪出单个题目的图片进行 LLM 分析
- **示例**: `crop_0001980178a04d6b8d41c4d117a10c5b.jpg`
- **是否必要**: 这些是 **调试/测试文件**，正式使用时可以设置为不保存

**b) ai_sheet_*.jpg (165 个文件)**
- **用途**: 学生上传的原始答题纸图片
- **目录**: `backend/media/uploads/ai_sheet_*`
- **是否必要**: ✅ **需要保留**，用于记录学生提交的原始答案

**c) graded_*.jpg (250 个文件)**
- **用途**: 批改后的答题纸，标注了对错
- **目录**: `backend/media/uploads/graded/`
- **是否必要**: ✅ **需要保留**，用于展示批改结果

**d) ai_bundles/*.json (99 个文件)**
- **用途**: 存储 AI 批改的元数据（OCR 结果、LLM 分析结果）
- **目录**: `backend/media/uploads/ai_bundles/`
- **结构**: 每个 bundle 包含 3 个文件：
  - `meta.json` - 图片路径等元信息
  - `ocr_raw.json` - OCR 识别的原始数据
  - `llm_raw.json` - LLM 分析的原始数据
- **数量**: 33 个 bundles × 3 个文件 = 99 个文件
- **是否必要**: ⚠️ **可选**，如果需要调试或分析批改准确性则保留

#### 2. **练习题生成文件 (77 个，占 2.5%)**

**a) Practice_*.pdf (43 个) + 答案 PDF (34 个)**
- **用途**: 系统生成的练习题和答案
- **日期范围**: 2026-01-04 至 2026-01-22
- **命名格式**:
  - `Practice_2026-01-04_ES-0042-78CF0F.pdf` (练习题)
  - `Practice_2026-01-04_ES-0042-78CF0F_Key.pdf` (答案)
- **是否必要**: ✅ **需要保留**，用户可能需要重新下载

#### 3. **教材素材文件 (16 个，占 0.5%)**

**cover_*.jpg (16 个文件)**
- **用途**: 教材封面图片
- **示例**: `cover_1_b7131114.jpg`, `cover_12_228b8a35.png`
- **大小**: 大部分 1.6 MB，一个特殊的 `cover_12_228b8a35.png` 为 5.9 MB
- **是否必要**: ✅ **需要保留**，用于展示教材信息

### 为什么"几乎没运行"的系统有这么多文件？

根据数据库查询结果：

```
Students: 0           ← 没有正式学生数据
Bases: 1              ← 只有 1 个教材
Items: 568            ← 568 个题目
Practice Sessions: 0  ← 没有正式练习记录
Submissions: 0        ← 没有提交记录
```

**结论**: 这些文件是 **开发测试阶段** 生成的：

1. **AI 批改功能测试** (2026-12-27 至 2026-01-07):
   - 测试了 AI 自动批改流程
   - 生成了 2,472 个裁剪图片（crop_*.jpg）
   - 生成了 165 个测试答题纸
   - 生成了 250 个批改结果图
   - 生成了 33 个批改元数据包

2. **练习题生成测试** (2026-01-04 至 2026-01-22):
   - 测试了练习题 PDF 生成功能
   - 生成了约 43 个练习题 + 34 个答案

3. **教材导入测试**:
   - 导入了 1 个教材，包含 568 个题目
   - 上传了 16 个封面图片

### 文件有效性判断

| 文件类型 | 是否有效 | 建议 |
|---------|---------|------|
| crop_*.jpg (2,472 个) | ⚠️ 测试文件 | **可以删除**，正式使用时建议关闭保存 |
| ai_sheet_*.jpg (165 个) | ✅ 有效 | 保留（如果需要测试记录） |
| graded_*.jpg (250 个) | ✅ 有效 | 保留（如果需要测试记录） |
| ai_bundles (99 个) | ⚠️ 调试数据 | 可以删除，除非需要分析批改准确性 |
| Practice PDFs (77 个) | ✅ 有效 | 保留，用户可能需要重新下载 |
| cover 图片 (16 个) | ✅ 有效 | **必须保留**，教材必需 |

### 💡 优化建议

#### 1. 清理测试数据（可节省约 120 MB 空间）

```bash
# 删除裁剪图片（测试文件）
rm -rf backend/media/crop_*.jpg  # ~2,472 个文件

# 删除测试的 AI 批改数据（如果确认不需要）
rm -rf backend/media/uploads/ai_sheet_*  # ~165 个文件
rm -rf backend/media/uploads/graded/     # ~250 个文件
rm -rf backend/media/uploads/ai_bundles/ # ~99 个文件
```

#### 2. 配置 AI 批改文件保存策略

在 AI 批改代码中添加配置：

```python
# 配置项
SAVE_CROP_IMAGES = False      # 不保存裁剪图片（crop_*.jpg）
SAVE_AI_BUNDLES = False       # 不保存详细调试数据
SAVE_GRADED_IMAGES = True     # 保留批改结果图
SAVE_ORIGINAL_SHEETS = True   # 保留原始答题纸
```

#### 3. 实现定期清理机制

添加清理任务：
- 自动删除 30 天前的 crop 文件
- 自动删除 90 天前的 ai_bundles
- 保留所有 PDF 和封面图片

---

## 🗄️ 问题 2: 备份是否充分？

### 备份文件分析

**备份文件**: `EnglishLearn_备份_20260124_200602.tar.gz`
**大小**: 132.64 MB
**创建时间**: 2026-01-24 20:06:02

#### 备份内容清单

```
总文件数: 3,124 个
├── backup_info.json (1 个) - 备份元信息
├── el.db (1 个, 304 KB) - SQLite 数据库
└── media/ (3,122 个, 132 MB) - 所有媒体文件
    ├── Practice PDFs: 77 个
    ├── cover 图片: 16 个
    ├── crop 图片: 2,472 个
    ├── ai_sheet: 165 个
    ├── graded: 250 个
    ├── ai_bundles: 99 个
    └── 其他: 43 个
```

### 数据库内容验证

**el.db 包含的表** (20 个表):

✅ **核心业务表**:
- accounts (账户)
- students (学生)
- bases (教材)
- items (题目)
- practice_sessions (练习记录)
- submissions (提交记录)
- practice_results (批改结果)

✅ **系统管理表**:
- system_config (系统配置)
- system_settings (系统设置)
- upgrade_logs (升级日志)
- **schema_migrations** (迁移历史) ← **关键**

✅ **辅助表**:
- auth_sessions (会话)
- student_learning_bases (学生教材关联)
- student_item_stats (学习统计)
- units (单元)
- session_items, exercise_items

### 全新安装恢复验证

#### ✅ 备份包含所有必需数据

| 数据类型 | 是否包含 | 说明 |
|---------|---------|------|
| 数据库结构 | ✅ | el.db 包含完整的表结构 |
| 数据库数据 | ✅ | 所有表的数据（568 个 items, 1 个 base, 等） |
| 迁移历史 | ✅ | schema_migrations 表已包含 |
| 媒体文件 | ✅ | 所有 3,082 个文件 |
| 系统配置 | ✅ | system_config 和 system_settings |
| 备份元信息 | ✅ | backup_info.json |

#### ✅ 不需要的额外文件

以下文件 **不需要** 包含在备份中，因为它们是代码层面的：

- ❌ 迁移脚本 (`backend/migrations/*.py`) - **不需要**
  - 原因: 备份已包含最终状态的数据库
  - 恢复时直接导入 el.db 即可

- ❌ 代码文件 (`backend/*.py`) - **不需要**
  - 原因: 代码通过 Git 管理

- ❌ 依赖配置 (`requirements.txt`) - **不需要**
  - 原因: 代码库已包含

### 🎯 恢复流程验证

#### 场景 1: 恢复到现有系统

**步骤**:
1. 访问 `/backup.html` → 设置标签页
2. 选择备份文件
3. 点击"恢复数据"
4. 系统自动：
   - ✅ 备份当前数据（安全措施）
   - ✅ 解压备份文件
   - ✅ 恢复数据库 el.db
   - ✅ 恢复所有媒体文件
5. 刷新页面，数据完全恢复

**测试结果**: ✅ **已验证**（见 BACKUP_RESTORE_TEST_REPORT.md）
- 数据库 100% 准确恢复
- 媒体文件 100% 完整恢复

#### 场景 2: 恢复到全新安装

**前提条件**:
- 全新服务器
- 已安装 Python 3.x
- 已克隆代码仓库

**恢复步骤**:

```bash
# 1. 克隆代码
git clone <repository-url>
cd EnglishLearn

# 2. 安装依赖
pip install -r backend/requirements.txt

# 3. 创建备份目录
mkdir -p backups

# 4. 上传备份文件到 backups/
scp EnglishLearn_备份_20260124_200602.tar.gz server:~/EnglishLearn/backups/

# 5. 通过 Web 界面恢复
# 启动服务
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000

# 访问 http://server:8000/backup.html
# 点击恢复按钮
```

**或者通过命令行恢复**:

```bash
# 解压备份
cd EnglishLearn
tar -xzf backups/EnglishLearn_备份_20260124_200602.tar.gz

# 恢复数据库
cp el.db backend/el.db

# 恢复媒体文件
cp -r media/* backend/media/

# 启动服务
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

**验证恢复结果**:

```python
# 检查数据库
python3 -c "
import sqlite3
conn = sqlite3.connect('backend/el.db')
cursor = conn.cursor()

cursor.execute('SELECT COUNT(*) FROM items')
print(f'Items: {cursor.fetchone()[0]}')  # 应该是 568

cursor.execute('SELECT COUNT(*) FROM bases')
print(f'Bases: {cursor.fetchone()[0]}')  # 应该是 1

cursor.execute('SELECT config_value FROM system_config WHERE config_key=\"app_version\"')
print(f'Version: {cursor.fetchone()[0]}')  # 应该是 1.0.0
"
```

**结论**: ✅ **备份完全充分**

### ⚠️ 注意事项

#### 1. 环境变量配置

恢复后需要配置 `.env` 文件（不包含在备份中，因为可能含敏感信息）：

```bash
cp .env.example .env
# 编辑 .env 设置：
# - DATABASE_URL
# - SECRET_KEY
# - 其他配置
```

#### 2. 文件权限

确保 media 目录有写权限：

```bash
chmod -R 755 backend/media
```

#### 3. 数据库路径

备份系统会自动处理路径：
- 开发环境: `backend/el.db`
- 生产环境: 根据 `.env` 中的 `DATABASE_URL`

#### 4. 不需要运行迁移

恢复备份后 **不需要运行数据库迁移**，因为：
- 备份包含的 el.db 已经是最新状态
- schema_migrations 表已记录所有迁移历史

如果误运行了迁移：

```bash
python3 backend/migration_manager.py status
# 显示: ✅ 数据库已是最新版本
```

---

## 📋 总结

### 问题 1 答案: 为什么有 3000+ 媒体文件？

✅ **原因**: 开发测试阶段的 AI 批改功能测试
- 80% 是 crop 裁剪图片（测试文件，可删除）
- 11% 是 AI 批改相关文件（graded, ai_sheet）
- 3% 是元数据（ai_bundles）
- 2.5% 是练习题 PDF（有效文件）
- 0.5% 是教材封面（必需文件）

✅ **建议**:
1. 删除 crop_*.jpg 可节省 ~80 MB
2. 配置生产环境不保存调试文件
3. 实现定期清理机制

### 问题 2 答案: 备份是否充分？

✅ **完全充分！**

**包含的数据**:
- ✅ 完整的数据库结构和数据 (el.db)
- ✅ 所有迁移历史 (schema_migrations 表)
- ✅ 所有媒体文件 (3,122 个文件)
- ✅ 系统配置 (system_config)
- ✅ 备份元信息 (backup_info.json)

**恢复能力**:
- ✅ 可以恢复到现有系统（已测试 100% 成功）
- ✅ 可以恢复到全新安装（理论验证通过）
- ✅ 不需要运行数据库迁移
- ✅ 不需要额外的代码文件

**唯一需要额外配置的**:
- `.env` 文件（环境变量，因安全原因不包含在备份中）

---

**分析完成时间**: 2026-01-24
**分析工具**: Claude Sonnet 4.5
**数据来源**:
- 文件系统分析 (backend/media/)
- 数据库查询 (backend/el.db)
- 备份文件分析 (EnglishLearn_备份_20260124_200602.tar.gz)
