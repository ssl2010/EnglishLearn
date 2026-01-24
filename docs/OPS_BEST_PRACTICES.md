# EnglishLearn 运维最佳实践与解决方案总结

## 📋 概述

本文档回答了以下核心问题:
1. ✅ 一键部署方案
2. ✅ 备份恢复机制
3. ✅ 管理员操作界面
4. ✅ 常见运维问题及解决方案

---

## 1️⃣ 一键部署方案

### ✅ 已实现

我们提供了 **完整的一键部署脚本** (`install.sh`),支持在全新服务器上快速部署。

### 🚀 使用方法

```bash
# 方式 1: 在线安装 (推荐)
curl -fsSL https://raw.githubusercontent.com/ssl2010/EnglishLearn/main/install.sh | sudo bash

# 方式 2: 本地安装
git clone https://github.com/ssl2010/EnglishLearn.git
cd EnglishLearn
sudo bash install.sh
```

### 📦 自动化内容

安装脚本会自动完成:

| 步骤 | 内容 | 说明 |
|------|------|------|
| 1 | 系统检测 | 自动识别 Ubuntu/Debian/CentOS |
| 2 | 依赖安装 | Python, Nginx, SQLite, OpenCV 等 |
| 3 | 用户创建 | 创建专用系统用户 `englishlearn` |
| 4 | 代码部署 | 克隆代码到 `/opt/EnglishLearn` |
| 5 | Python 环境 | 创建虚拟环境并安装依赖 |
| 6 | 数据初始化 | 创建数据库和数据目录 |
| 7 | 配置文件 | 生成环境变量和密钥 |
| 8 | 服务配置 | 配置 systemd 服务自动启动 |
| 9 | 反向代理 | 配置 Nginx 反向代理 |
| 10 | 防火墙 | 配置防火墙规则 |
| 11 | 服务启动 | 启动所有服务 |
| 12 | 信息显示 | 显示访问地址和管理员密码 |

### ⏱️ 部署时间

- **最小化安装**: 5-10 分钟
- **完整安装 (含依赖下载)**: 10-20 分钟

### 🔐 安全性

- ✅ 自动生成随机密钥和管理员密码
- ✅ 最小权限原则 (专用系统用户)
- ✅ 自动配置防火墙
- ✅ 安全的文件权限设置

---

## 2️⃣ 备份恢复机制

### ✅ 多种备份方式

我们提供了 **三种备份方式**,满足不同场景需求:

#### 方式 1: 自动备份 (推荐生产环境)

**Cron 定时任务:**

```bash
# 每天凌晨 2 点自动备份
0 2 * * * cd /opt/EnglishLearn && ./deploy.sh backup

# 每周日凌晨 3 点清理 30 天前的旧备份
0 3 * * 0 find /opt/EnglishLearn_Backups -name "*.tar.gz" -mtime +30 -delete
```

**systemd timer:**

```bash
# 创建定时备份服务
sudo systemctl enable englishlearn-backup.timer
sudo systemctl start englishlearn-backup.timer
```

#### 方式 2: 命令行手动备份

```bash
# 标准备份
cd /opt/EnglishLearn
sudo ./deploy.sh backup

# 热备份 (不停止服务)
BACKUP_NO_STOP=1 sudo ./deploy.sh backup

# 查看备份列表
sudo ./deploy.sh list

# 恢复最新备份
sudo ./deploy.sh restore latest
```

#### 方式 3: Web 界面备份 (管理员操作)

- ✅ 可视化备份管理界面
- ✅ 选择备份内容 (数据库/媒体文件)
- ✅ 一键下载到本地
- ✅ 在线恢复备份
- ✅ 查看备份统计信息

### 📊 备份内容

| 内容 | 说明 | 大小估算 |
|------|------|---------|
| 数据库 | SQLite 文件 (`el.db`) | 几百 KB - 几 MB |
| 媒体文件 | 图片、音频等 | 取决于用量,可能几十 MB - 几 GB |
| 配置文件 | 环境变量等 | 几 KB |

### 🔄 备份格式

```
EL_backup_20260124_120000.tar.gz
    └── temp_20260124_120000/
        ├── el.db              # 数据库
        ├── media/             # 媒体文件目录
        └── backup_info.txt    # 备份信息 (可选)
```

### ⚡ 备份速度

| 数据量 | 备份时间 |
|--------|---------|
| < 100 MB | < 10 秒 |
| 100 MB - 1 GB | 10-60 秒 |
| 1 GB - 10 GB | 1-5 分钟 |

### 🌐 远程备份

支持多种远程存储方案:

```bash
# 方案 1: rsync 到远程服务器
rsync -avz --delete /opt/EnglishLearn_Backups/ user@remote:/backups/

# 方案 2: 云存储 (OSS/S3)
aws s3 sync /opt/EnglishLearn_Backups/ s3://your-bucket/backups/

# 方案 3: 定时上传脚本
0 3 * * * /opt/EnglishLearn/scripts/upload_backup.sh
```

### 🔒 备份安全

**加密备份 (推荐):**

```bash
# 加密备份
gpg --symmetric --cipher-algo AES256 EL_backup_20260124_120000.tar.gz

# 解密恢复
gpg --decrypt EL_backup_20260124_120000.tar.gz.gpg > EL_backup_20260124_120000.tar.gz
```

**备份验证:**

```bash
# 验证备份完整性
tar -tzf EL_backup_20260124_120000.tar.gz > /dev/null && echo "OK" || echo "CORRUPTED"
```

---

## 3️⃣ 管理员操作界面

### ✅ 已实现功能

我们提供了 **Web 管理界面**,管理员可以在浏览器中完成所有运维操作:

#### 📦 备份管理页面 (`/backup.html`)

**功能列表:**

1. **创建备份**
   - 选择备份内容 (数据库/媒体文件)
   - 添加备份描述
   - 实时进度显示

2. **备份列表**
   - 查看所有备份文件
   - 显示文件大小、创建时间
   - 备份内容标识 (是否包含 DB/媒体)

3. **下载备份**
   - 一键下载到本地
   - 支持断点续传 (浏览器功能)

4. **恢复备份**
   - 选择要恢复的备份
   - 选择恢复内容 (数据库/媒体文件)
   - 安全确认机制

5. **删除备份**
   - 删除不需要的旧备份
   - 确认提示防止误删

6. **统计信息**
   - 备份总数
   - 备份占用空间
   - 磁盘可用空间
   - 磁盘使用率

7. **清理功能**
   - 自动清理 30 天前的旧备份
   - 显示释放的空间

#### 🎨 界面特点

- ✅ 响应式设计,支持移动端
- ✅ 美观的统计卡片
- ✅ 实时进度反馈
- ✅ 友好的错误提示
- ✅ 确认对话框防止误操作

### 🔌 API 接口

管理员界面基于 RESTful API:

```bash
# 列出备份
GET /api/admin/backup/list

# 创建备份
POST /api/admin/backup/create
Body: {
  "include_db": true,
  "include_media": true,
  "description": "月度备份"
}

# 下载备份
GET /api/admin/backup/download/{filename}

# 恢复备份
POST /api/admin/backup/restore
Body: {
  "filename": "EL_backup_20260124_120000.tar.gz",
  "restore_db": true,
  "restore_media": true
}

# 删除备份
DELETE /api/admin/backup/delete/{filename}

# 清理旧备份
POST /api/admin/backup/cleanup?keep_days=30

# 空间统计
GET /api/admin/backup/space
```

### 🔐 权限控制

**注意:** 备份管理功能应该:
- ✅ 仅限管理员访问
- ✅ 需要在 `backend/app/main.py` 中注册路由时添加管理员权限检查
- ✅ 建议添加操作审计日志

**权限检查示例:**

```python
# 在 backend/app/main.py 中添加
from app.routers import backup
from app.dependencies import get_current_admin  # 需要实现

# 注册路由时添加依赖
app.include_router(
    backup.router,
    dependencies=[Depends(get_current_admin)]
)
```

---

## 4️⃣ 常见运维问题与解决方案

### 问题 1: 服务无法启动

**症状:** `systemctl start englishlearn` 失败

**排查:**

```bash
# 查看错误日志
sudo journalctl -u englishlearn -n 100

# 检查端口占用
sudo netstat -tulnp | grep 8000

# 检查权限
ls -la /opt/EnglishLearn/data

# 手动启动测试
sudo -u englishlearn /opt/EnglishLearn/venv/bin/uvicorn backend.app.main:app
```

**解决:**
- 端口被占用 → 修改端口或杀死进程
- 权限问题 → `chown -R englishlearn:englishlearn /opt/EnglishLearn`
- 依赖缺失 → 重新运行 `pip install -r requirements.txt`

### 问题 2: Nginx 502 Bad Gateway

**症状:** 访问页面显示 502

**排查:**

```bash
# 检查后端服务
sudo systemctl status englishlearn

# 查看 Nginx 日志
sudo tail -f /var/log/nginx/englishlearn_error.log

# 测试后端连接
curl http://127.0.0.1:8000/api/health
```

**解决:**
- 后端未启动 → `systemctl start englishlearn`
- Nginx 配置错误 → `nginx -t` 检查配置

### 问题 3: 磁盘空间不足

**症状:** "No space left on device"

**解决:**

```bash
# 检查磁盘使用
df -h
du -sh /opt/EnglishLearn/*

# 清理日志
sudo journalctl --vacuum-time=7d

# 清理旧备份
cd /opt/EnglishLearn && sudo ./deploy.sh cleanup

# 清理媒体文件缓存
find /tmp -name "*.tmp" -mtime +7 -delete
```

### 问题 4: 数据库损坏

**症状:** 数据库错误,服务启动失败

**修复:**

```bash
# 检查完整性
sqlite3 /opt/EnglishLearn/data/el.db "PRAGMA integrity_check;"

# 尝试恢复
sqlite3 /opt/EnglishLearn/data/el.db ".recover" > recovered.sql

# 从备份恢复
sudo ./deploy.sh restore latest
```

### 问题 5: 性能缓慢

**症状:** 页面加载慢,API 响应慢

**优化:**

```bash
# 优化数据库
sqlite3 /opt/EnglishLearn/data/el.db "VACUUM; ANALYZE;"

# 增加 worker 数量
# 编辑 /etc/systemd/system/englishlearn.service
# 添加 --workers 4

# 启用 Nginx 缓存
# 编辑 Nginx 配置,添加 proxy_cache

# 检查系统资源
htop
```

### 问题 6: SSL 证书过期

**症状:** HTTPS 访问失败

**解决:**

```bash
# 手动续期
sudo certbot renew

# 检查自动续期
sudo systemctl status certbot.timer

# 强制续期
sudo certbot renew --force-renewal
```

### 问题 7: 备份失败

**症状:** 备份命令执行失败

**排查:**

```bash
# 检查备份目录权限
ls -la /opt/EnglishLearn_Backups

# 检查磁盘空间
df -h

# 手动测试备份
cd /opt/EnglishLearn
sudo ./deploy.sh backup
```

**解决:**
- 权限问题 → `mkdir -p /opt/EnglishLearn_Backups && chown englishlearn:englishlearn /opt/EnglishLearn_Backups`
- 空间不足 → 清理旧备份或扩展磁盘

### 问题 8: 升级后出现问题

**症状:** 升级后服务异常

**回滚:**

```bash
# 停止服务
sudo systemctl stop englishlearn

# 回滚代码
cd /opt/EnglishLearn
sudo -u englishlearn git reset --hard HEAD~1

# 恢复备份
sudo ./deploy.sh restore latest

# 重启服务
sudo systemctl restart englishlearn
```

---

## 5️⃣ 运维最佳实践

### 📅 日常运维检查清单

**每日:**
- [ ] 检查服务状态: `systemctl status englishlearn`
- [ ] 检查磁盘空间: `df -h`
- [ ] 查看错误日志: `journalctl -u englishlearn -p err`

**每周:**
- [ ] 查看备份列表,确保备份正常
- [ ] 检查系统更新: `apt update && apt list --upgradable`
- [ ] 分析访问日志,识别异常流量

**每月:**
- [ ] 测试备份恢复流程
- [ ] 优化数据库: `VACUUM; ANALYZE;`
- [ ] 清理旧备份和日志
- [ ] 更新系统和应用依赖
- [ ] 检查 SSL 证书有效期

### 🔒 安全最佳实践

1. ✅ **立即修改默认密码**
2. ✅ **启用 HTTPS**
3. ✅ **配置防火墙**
4. ✅ **禁用 root SSH 登录**
5. ✅ **定期更新系统**
6. ✅ **启用备份加密**
7. ✅ **配置日志监控**
8. ✅ **限制 API 访问频率**

### 📊 监控告警

**推荐监控项:**

| 监控项 | 阈值 | 告警方式 |
|--------|------|---------|
| 服务状态 | Down | 立即通知 |
| CPU 使用率 | > 80% | 警告 |
| 内存使用率 | > 85% | 警告 |
| 磁盘使用率 | > 80% | 警告 |
| 备份时间 | > 48h 无备份 | 警告 |
| 错误日志 | > 10 条/分钟 | 立即通知 |

**告警通知方式:**
- 邮件
- 钉钉/企业微信
- 短信 (紧急情况)

### 🔧 自动化工具

**推荐工具:**

1. **监控**: Prometheus + Grafana
2. **日志**: ELK Stack 或 Loki
3. **自动化**: Ansible / Terraform
4. **CI/CD**: GitHub Actions
5. **容器化**: Docker + Docker Compose (可选)

---

## 6️⃣ 高级运维方案

### Docker 部署 (可选)

虽然当前提供的是传统部署方式,但也可以容器化部署:

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    libopencv-dev \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY backend/ ./backend/
COPY frontend/ ./frontend/

EXPOSE 8000

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```yaml
# docker-compose.yml
version: '3.8'

services:
  app:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
    environment:
      - DATABASE_URL=sqlite:///data/el.db
    restart: unless-stopped

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
      - ./frontend:/usr/share/nginx/html
    depends_on:
      - app
    restart: unless-stopped
```

### 负载均衡 (多服务器)

使用 Nginx 做负载均衡:

```nginx
upstream englishlearn_cluster {
    server 192.168.1.10:8000 weight=1;
    server 192.168.1.11:8000 weight=1;
    server 192.168.1.12:8000 weight=1;
    keepalive 32;
}

server {
    listen 80;
    location /api/ {
        proxy_pass http://englishlearn_cluster;
    }
}
```

### 数据库读写分离 (未来扩展)

如果迁移到 PostgreSQL:

```python
# 主库 (写)
MASTER_DB = "postgresql://user:pass@master-host/db"

# 从库 (读)
REPLICA_DB = "postgresql://user:pass@replica-host/db"
```

---

## 7️⃣ 总结

### ✅ 完成的工作

| 功能 | 状态 | 说明 |
|------|------|------|
| 一键部署脚本 | ✅ | `install.sh` 支持 Ubuntu/Debian/CentOS |
| systemd 服务 | ✅ | 自动启动,资源限制 |
| Nginx 配置 | ✅ | 反向代理,静态文件,gzip |
| 备份脚本 | ✅ | `deploy.sh backup/restore/list` |
| Web 备份界面 | ✅ | `frontend/backup.html` |
| 备份 API | ✅ | `backend/app/routers/backup.py` |
| 运维文档 | ✅ | `docs/DEPLOYMENT.md` |

### 📚 文档清单

1. **install.sh** - 一键安装脚本
2. **deploy.sh** - 运维管理脚本 (已存在,本次未修改)
3. **backend/app/routers/backup.py** - 备份管理 API
4. **frontend/backup.html** - Web 备份管理界面
5. **docs/DEPLOYMENT.md** - 完整部署运维文档
6. **本文档** - 运维最佳实践总结

### 🚀 下一步建议

1. **集成到菜单**: 将 `backup.html` 添加到 `app.html` 的管理员菜单中
2. **权限控制**: 为备份 API 添加管理员权限检查
3. **操作审计**: 记录所有备份/恢复操作日志
4. **告警通知**: 集成钉钉/企业微信/邮件告警
5. **监控面板**: 添加系统监控页面 (CPU/内存/磁盘)
6. **自动化测试**: 添加备份恢复的自动化测试

---

**文档版本:** 1.0
**创建时间:** 2026-01-24
**作者:** EnglishLearn Team
