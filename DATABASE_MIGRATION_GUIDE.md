# 数据库迁移系统说明

## 📦 概述

EnglishLearn 现在支持**自动数据库迁移**，可以在升级时自动处理数据库结构变更，实现真正的一键升级。

## ✨ 功能特性

### 1. 自动迁移管理
- 🔍 自动检测待执行的迁移
- 📝 记录迁移历史
- ✅ 幂等性设计（可重复执行）
- 🔄 升级时自动运行

### 2. 迁移版本控制
- 📅 基于时间戳的版本号
- 📋 迁移执行状态跟踪
- ⏱️ 执行时间统计
- 🗄️ 迁移历史记录

### 3. 安全机制
- 🛡️ 事务支持，失败自动回滚
- ⚠️ 错误停止机制
- 📦 升级前自动备份
- 🔙 支持回滚到备份

## 🗂️ 目录结构

```
backend/
├── migration_manager.py      # 迁移管理器
├── migrations/               # 迁移脚本目录
│   ├── _template.py         # 迁移脚本模板
│   ├── 20260124_150000_add_upgrade_log_table.py  # 示例迁移
│   └── YYYYMMDD_HHMMSS_description.py           # 其他迁移
└── data/
    └── el.db                # 数据库（包含 schema_migrations 表）
```

## 📝 数据库表

### schema_migrations
记录所有已执行的迁移

```sql
CREATE TABLE schema_migrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version TEXT NOT NULL UNIQUE,          -- 版本号: YYYYMMDD_HHMMSS
    name TEXT NOT NULL,                    -- 迁移文件名
    applied_at TEXT NOT NULL,              -- 执行时间
    execution_time_ms INTEGER,             -- 执行耗时（毫秒）
    success INTEGER DEFAULT 1,             -- 是否成功
    error_message TEXT                     -- 错误信息
)
```

### upgrade_logs (由迁移创建)
记录系统升级历史

```sql
CREATE TABLE upgrade_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version_from TEXT,                     -- 升级前版本
    version_to TEXT NOT NULL,              -- 升级后版本
    upgrade_type TEXT NOT NULL,            -- 升级类型：git_pull
    started_at TEXT NOT NULL,              -- 开始时间
    completed_at TEXT,                     -- 完成时间
    status TEXT NOT NULL,                  -- 状态：running/success/failed
    error_message TEXT,                    -- 错误信息
    backup_file TEXT,                      -- 备份文件名
    pip_installed INTEGER DEFAULT 0,       -- 是否安装了依赖
    service_restarted INTEGER DEFAULT 0,   -- 是否重启了服务
    duration_seconds INTEGER,              -- 总耗时（秒）
    triggered_by TEXT DEFAULT 'web',       -- 触发方式：web/cli
    notes TEXT                             -- 备注
)
```

## 🔧 使用方法

### 1. 创建新迁移

**使用模板创建**:

```bash
cd backend
cp migrations/_template.py migrations/$(date +%Y%m%d_%H%M%S)_your_description.py
```

**编辑迁移脚本**:

```python
#!/usr/bin/env python3
"""
添加新功能的数据库变更
"""

import sqlite3

def migrate(conn: sqlite3.Connection):
    """执行迁移"""
    cursor = conn.cursor()

    # 添加新表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS new_feature (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 添加新列（注意处理已存在的情况）
    try:
        cursor.execute("""
            ALTER TABLE existing_table
            ADD COLUMN new_column TEXT
        """)
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e).lower():
            raise

    # 创建索引
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_new_feature_name
        ON new_feature(name)
    """)

    # 数据迁移
    cursor.execute("""
        UPDATE existing_table
        SET new_column = 'default'
        WHERE new_column IS NULL
    """)

    conn.commit()
```

### 2. 测试迁移

**单独测试**:

```bash
python backend/migrations/20260124_150000_your_migration.py
```

**检查迁移状态**:

```bash
python backend/migration_manager.py status
```

**执行所有待运行的迁移**:

```bash
python backend/migration_manager.py migrate
```

**仅检查是否需要迁移**:

```bash
python backend/migration_manager.py check
```

### 3. 自动迁移（升级时）

迁移会在以下情况自动执行：

**Web 界面升级**:
- 系统管理 → 系统设置 → 系统升级 → 开始升级
- 迁移在 Git Pull 和 Pip Install 之后自动执行

**命令行升级**:
```bash
./deploy.sh update
# 自动执行迁移，除非设置 SKIP_MIGRATION=1
```

**跳过迁移**:
```bash
SKIP_MIGRATION=1 ./deploy.sh update
```

## 📋 升级流程（包含迁移）

```
1. 升级前自动备份
   ↓
2. Git pull (拉取最新代码)
   ↓
3. Pip install (安装依赖)
   ↓
4. 数据库迁移 ⭐ 新增
   ├─ 检查是否有待执行的迁移
   ├─ 按版本号顺序执行
   ├─ 记录执行结果
   └─ 失败则停止升级
   ↓
5. 重启服务
   ↓
6. 升级完成
```

## ⚠️ 最佳实践

### 编写迁移脚本

1. **幂等性**
   ```python
   # ✅ 好的做法 - 可重复执行
   cursor.execute("CREATE TABLE IF NOT EXISTS ...")

   # ❌ 不好的做法 - 第二次会失败
   cursor.execute("CREATE TABLE ...")
   ```

2. **添加列处理**
   ```python
   # ✅ 好的做法 - 处理列已存在的情况
   try:
       cursor.execute("ALTER TABLE ... ADD COLUMN ...")
   except sqlite3.OperationalError as e:
       if "duplicate column name" not in str(e).lower():
           raise

   # ❌ 不好的做法 - 列存在时会失败
   cursor.execute("ALTER TABLE ... ADD COLUMN ...")
   ```

3. **数据迁移**
   ```python
   # ✅ 好的做法 - 只更新需要的数据
   cursor.execute("""
       UPDATE table SET new_col = 'value'
       WHERE new_col IS NULL
   """)

   # ⚠️ 注意 - 大表数据迁移可能很慢
   # 考虑分批处理或在低峰时段执行
   ```

4. **索引创建**
   ```python
   # ✅ 好的做法 - 使用 IF NOT EXISTS
   cursor.execute("CREATE INDEX IF NOT EXISTS idx_name ON table(col)")
   ```

### 命名规范

**文件名**:
```
YYYYMMDD_HHMMSS_description.py

示例:
20260124_150000_add_upgrade_log_table.py
20260124_160000_add_user_preferences.py
20260125_090000_migrate_old_data_format.py
```

**描述规范**:
- 使用小写字母
- 单词之间用下划线分隔
- 简洁明了地描述变更内容
- 使用动词开头（add, remove, update, migrate 等）

### 测试流程

1. **开发环境测试**
   ```bash
   # 1. 创建迁移
   cp migrations/_template.py migrations/20260124_150000_my_feature.py

   # 2. 编辑迁移脚本
   vim migrations/20260124_150000_my_feature.py

   # 3. 单独测试
   python migrations/20260124_150000_my_feature.py

   # 4. 通过管理器测试
   python migration_manager.py migrate

   # 5. 检查结果
   python migration_manager.py status
   ```

2. **生产环境部署**
   ```bash
   # 1. 提交迁移脚本到 Git
   git add backend/migrations/20260124_150000_my_feature.py
   git commit -m "Add migration: my feature"
   git push

   # 2. 在生产环境升级（自动执行迁移）
   ./deploy.sh update

   # 或使用 Web 界面升级
   ```

## 🔍 故障排查

### 查看迁移状态

```bash
python backend/migration_manager.py status
```

输出示例:
```
数据库迁移状态:
  数据库: /opt/EnglishLearn/data/el.db
  当前版本: 20260124_150000
  已应用: 5 个迁移
  待执行: 2 个迁移
  最后迁移: 20260124_150000_add_upgrade_log_table.py
           于 2026-01-24T15:30:00

⚠️  需要执行 2 个迁移
```

### 查询数据库

```bash
sqlite3 backend/data/el.db

# 查看已执行的迁移
SELECT version, name, applied_at, success
FROM schema_migrations
ORDER BY applied_at DESC
LIMIT 10;

# 查看失败的迁移
SELECT version, name, error_message
FROM schema_migrations
WHERE success = 0;
```

### 迁移失败处理

**情况1: 迁移脚本有错误**

```bash
# 1. 查看错误信息
python migration_manager.py status

# 2. 修复迁移脚本
vim backend/migrations/YYYYMMDD_HHMMSS_xxx.py

# 3. 删除失败记录
sqlite3 backend/data/el.db
DELETE FROM schema_migrations WHERE version = 'YYYYMMDD_HHMMSS';

# 4. 重新执行
python migration_manager.py migrate
```

**情况2: 升级时迁移失败**

```bash
# 1. 查看升级日志（Web 界面会显示详细错误）

# 2. 恢复升级前备份
./deploy.sh restore latest

# 3. 修复迁移脚本后重新升级
```

## 📊 迁移示例

### 示例1: 添加新表

```python
# 20260124_150000_add_user_settings.py
def migrate(conn: sqlite3.Connection):
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            setting_key TEXT NOT NULL,
            setting_value TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, setting_key)
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_settings_user_id
        ON user_settings(user_id)
    """)

    conn.commit()
```

### 示例2: 添加列

```python
# 20260124_160000_add_email_to_students.py
def migrate(conn: sqlite3.Connection):
    cursor = conn.cursor()

    try:
        cursor.execute("""
            ALTER TABLE students
            ADD COLUMN email TEXT
        """)
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e).lower():
            raise

    conn.commit()
```

### 示例3: 数据迁移

```python
# 20260124_170000_migrate_old_format.py
def migrate(conn: sqlite3.Connection):
    cursor = conn.cursor()

    # 添加新列
    try:
        cursor.execute("ALTER TABLE items ADD COLUMN tags TEXT")
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e).lower():
            raise

    # 迁移旧数据
    cursor.execute("""
        UPDATE items
        SET tags = '["general"]'
        WHERE tags IS NULL
    """)

    conn.commit()
```

## 🔒 安全注意事项

1. **始终在升级前备份**
   - Web 升级默认会自动备份
   - 命令行升级建议手动备份: `./deploy.sh backup`

2. **测试环境先行**
   - 新迁移先在开发/测试环境验证
   - 确认无误后再部署到生产环境

3. **不要修改已应用的迁移**
   - 已执行的迁移不应该再修改
   - 如需变更，创建新的迁移脚本

4. **大数据量迁移**
   - 考虑分批处理
   - 在低峰时段执行
   - 提前评估执行时间

5. **准备回滚方案**
   - 保留升级前备份
   - 知道如何恢复备份
   - 记录升级时间和版本

## 🎯 总结

**现在升级 EnglishLearn 系统，即使有数据库结构变更，也能做到真正的一键升级！**

**升级流程**:
1. ✅ 自动备份
2. ✅ 拉取代码
3. ✅ 安装依赖
4. ✅ **自动迁移数据库** ⭐
5. ✅ 重启服务

**无需手动**:
- ❌ SSH 登录
- ❌ 执行 SQL 脚本
- ❌ 修改数据库
- ❌ 担心数据丢失

**只需点击**:
- 🖱️ "检查更新"
- 🖱️ "开始升级"

---

**更新时间**: 2026-01-24
**版本**: 1.0
