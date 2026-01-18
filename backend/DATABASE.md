# 数据库管理

## 初始化数据库

### 首次安装

```bash
# 在项目根目录执行
cd backend
python3 init_db.py
```

这将创建数据库并加载示例数据，包括：
- 2个示例学生（小明、小红）
- 2个系统课本资料库（人教版四年级/五年级上册）
- 1个自定义资料库示例
- 学习库配置示例

### 重建数据库

⚠️ **警告：这将删除所有现有数据！**

```bash
cd backend
python3 init_db.py --force
```

### 仅创建空数据库（不加载种子数据）

```bash
cd backend
python3 init_db.py --force --no-seed
```

## 数据库结构

数据库结构定义在 `backend/schema.sql` 中。

### 核心表

| 表名 | 说明 |
|------|------|
| `students` | 学生信息 |
| `bases` | 资料库（系统课本 + 自定义） |
| `units` | 单元元数据 |
| `items` | 词条（单词/短语/句子） |
| `student_learning_bases` | 学生学习库配置 |
| `practice_sessions` | 练习单会话（生成/状态/PDF） |
| `exercise_items` | 练习单题目明细 |
| `submissions` | 提交记录（批改结果/手动录入） |
| `practice_results` | 批改入库结果 |
| `student_item_stats` | 学生词条练习统计 |
| `system_settings` | 系统配置（掌握阈值等） |
| `accounts` | 登录账号 |
| `auth_sessions` | 登录会话 |
| `sessions` | 旧版练习单（兼容保留） |
| `session_items` | 旧版练习单关联（兼容保留） |

### 重要字段说明

#### `bases.is_system`
- `0`: 自定义资料库（家长可编辑）
- `1`: 系统课本资料库（只读）

#### `items.unit`
- `"__ALL__"`: 不分单元
- `"Unit 1"`, `"Unit 2"` 等: 具体单元
- `NULL`: 需要设置单元但尚未设置

#### `student_learning_bases.current_unit`
- `"__ALL__"`: 全部（不分单元或已学完全部）
- `"Unit 3"`: 学到Unit 3（可出题范围: Unit 1-3）
- `NULL`: 未设置进度

#### `practice_sessions.status`
- `DRAFT`: 已生成未提交
- `CORRECTED`: 已批改并入库
- 其他历史状态保留用于兼容

## 数据导入导出

### 导入资料库
- **界面**：`/library.html` -> 从文件导入
- **API**：`POST /api/knowledge-bases/import-file`（支持 `mode=skip|update`）

## 种子数据

种子数据在 `backend/load_seed_data.py` 中定义。

可以修改此文件来添加更多系统课本资料库或示例数据。

修改后重新运行初始化：

```bash
python3 init_db.py --force
```

## 备份与恢复

### 备份数据库

```bash
cp el.db el.db.backup_$(date +%Y%m%d_%H%M%S)
```

### 恢复数据库

```bash
cp el.db.backup_20260101_120000 el.db
```

## 常见问题

### Q: 如何添加新的系统课本？

A: 编辑 `backend/load_seed_data.py`，在 `system_bases` 列表中添加新的课本数据，然后重新初始化数据库。

### Q: 如何清除所有数据但保留结构？

A:
```bash
python3 init_db.py --force --no-seed
```

### Q: 初始化失败怎么办？

A: 检查：
1. 是否在 `backend` 目录下执行命令
2. `schema.sql` 文件是否存在
3. 是否有写入权限
4. 查看详细错误信息

### Q: 如何验证数据库内容？

A:
```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('el.db')
cursor = conn.cursor()
cursor.execute('SELECT name FROM sqlite_master WHERE type=\"table\"')
print('Tables:', [row[0] for row in cursor.fetchall()])
cursor.execute('SELECT COUNT(*) FROM bases')
print('Bases:', cursor.fetchone()[0])
cursor.execute('SELECT COUNT(*) FROM items')
print('Items:', cursor.fetchone()[0])
conn.close()
"
```
