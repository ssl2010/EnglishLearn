# EnglishLearn 维护检查清单

每次修改代码后，请检查以下脚本是否需要同步更新。

## 重要提醒

**Python 缓存问题**: 升级后如遇到路径相关错误，可能是 `__pycache__` 中的 `.pyc` 文件缓存了旧路径。
`elctl update/upgrade` 和 `install.sh` 已自动清理缓存，如需手动清理：
```bash
find /opt/EnglishLearn -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
sudo systemctl restart englishlearn
```

## 需要检查的脚本

### 1. `install.sh` - 安装脚本

当以下情况发生时需要更新：

| 修改内容 | 需要检查的部分 |
|---------|--------------|
| 新增配置文件 | `setup_data_directories()` - 确保文件被复制 |
| 新增环境变量 | `create_env_file()` - 添加到模板 |
| 新增 Python 依赖 | `setup_python_env()` - requirements.txt 会自动处理 |
| 新增 systemd 服务/定时器 | `setup_systemd_service()` / `setup_backup_timer()` |
| 修改目录结构 | `setup_data_directories()` - 更新目录创建逻辑 |
| 修改数据库 schema | 确保迁移脚本存在且被调用 |
| 新增系统依赖 | `install_system_deps()` - 添加 apt 包 |

### 2. `elctl` - 管理工具

当以下情况发生时需要更新：

| 修改内容 | 需要检查的部分 |
|---------|--------------|
| 新增配置文件 | `backup_data()` - 确保备份包含新文件 |
| 修改备份内容 | `backup_data()` / `restore_data()` |
| 新增环境变量 | `merge_env_config()` - 确保合并逻辑正确 |
| 新增管理功能 | 添加新的命令函数和 case 分支 |
| 修改服务名称 | `SERVICE_NAME` 默认值 |
| 修改数据目录 | `DATA_DIR` / `DB_PATH` / `MEDIA_DIR` |

## 检查清单模板

每次提交前，复制以下清单并打勾：

```markdown
### 本次修改检查

- [ ] 是否新增了配置文件？
  - [ ] install.sh: 文件会被正确复制/创建
  - [ ] elctl: 备份会包含该文件

- [ ] 是否新增了环境变量？
  - [ ] .env.example 已更新
  - [ ] install.sh: create_env_file() 已更新
  - [ ] INSTALL_GUIDE.md 已更新

- [ ] 是否修改了目录结构？
  - [ ] install.sh: 目录会被正确创建
  - [ ] elctl: 路径配置正确

- [ ] 是否新增了系统依赖？
  - [ ] install.sh: install_system_deps() 已更新
  - [ ] INSTALL_GUIDE.md 已更新

- [ ] 是否新增了 systemd 服务？
  - [ ] install.sh: 服务会被安装和启用
  - [ ] elctl: 添加管理命令（如需要）
```

## 关键配置文件清单

以下文件必须存在于生产环境：

| 文件 | 位置 | 说明 |
|-----|------|------|
| `ai_config.json` | 项目根目录 | AI 批改提示词配置 |
| `.env` 或 `/etc/englishlearn.env` | - | 环境变量配置 |
| `el.db` | `$DATA_DIR/` | SQLite 数据库 |
| `media/` | `$DATA_DIR/` | 媒体文件目录 |

## 快速验证命令

安装后在服务器上运行：

```bash
# 检查关键文件
ls -la /opt/EnglishLearn/ai_config.json
ls -la /opt/EnglishLearn/data/el.db
ls -la /etc/englishlearn.env

# 检查服务状态
sudo systemctl status englishlearn
sudo systemctl status englishlearn-backup.timer

# 检查环境变量
sudo grep -E "OPENAI|ARK|BAIDU" /etc/englishlearn.env

# 测试 API
curl -s http://localhost:8000/api/health || curl -s http://127.0.0.1:8000/api/auth/me
```

## 版本更新时的检查流程

1. **代码更新后**：
   ```bash
   cd /opt/EnglishLearn
   sudo git pull origin main
   ```

2. **检查新文件**：
   ```bash
   git diff --name-status HEAD~5..HEAD | grep "^A"
   ```

3. **检查配置变更**：
   ```bash
   git diff HEAD~5..HEAD -- .env.example install.sh elctl
   ```

4. **重启服务**：
   ```bash
   sudo systemctl restart englishlearn
   ```

5. **验证功能**：
   - 登录 Web 界面
   - 测试批改功能
   - 检查备份功能
