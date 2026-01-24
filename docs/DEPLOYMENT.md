# EnglishLearn 部署运维文档

## 目录

1. [快速开始](#快速开始)
2. [一键部署](#一键部署)
3. [备份策略](#备份策略)
4. [升级维护](#升级维护)
5. [监控告警](#监控告警)
6. [故障排查](#故障排查)
7. [安全加固](#安全加固)
8. [性能优化](#性能优化)

---

## 快速开始

### 系统要求

**最低配置:**
- CPU: 2核
- 内存: 2GB
- 磁盘: 20GB
- 操作系统: Ubuntu 20.04+ / Debian 11+ / CentOS 8+

**推荐配置:**
- CPU: 4核
- 内存: 4GB
- 磁盘: 50GB (SSD)
- 操作系统: Ubuntu 22.04 LTS

---

## 一键部署

### 方式 1: 在线安装 (推荐)

```bash
# 下载并执行安装脚本
curl -fsSL https://raw.githubusercontent.com/ssl2010/EnglishLearn/main/install.sh | sudo bash

# 或使用 wget
wget -O - https://raw.githubusercontent.com/ssl2010/EnglishLearn/main/install.sh | sudo bash
```

### 方式 2: 本地安装

```bash
# 克隆代码
git clone https://github.com/ssl2010/EnglishLearn.git
cd EnglishLearn

# 执行安装脚本
sudo bash install.sh
```

### 安装过程

安装脚本会自动完成以下步骤:

1. ✅ 检测操作系统
2. ✅ 安装系统依赖 (Python, Nginx, SQLite, OpenCV 等)
3. ✅ 创建系统用户 `englishlearn`
4. ✅ 克隆代码到 `/opt/EnglishLearn`
5. ✅ 创建 Python 虚拟环境并安装依赖
6. ✅ 初始化数据库
7. ✅ 配置环境变量 (`/etc/englishlearn.env`)
8. ✅ 配置 systemd 服务
9. ✅ 配置 Nginx 反向代理
10. ✅ 启动服务

### 安装后配置

安装完成后,脚本会显示:

```
管理员账号: admin@example.com
管理员密码: <随机生成的密码>
```

**重要:** 请立即登录并修改管理员密码!

---

## 备份策略

### 2.1 自动备份 (推荐)

#### 方案 1: Cron 定时任务

```bash
# 编辑 crontab
sudo crontab -e

# 添加以下行 (每天凌晨 2 点自动备份)
0 2 * * * cd /opt/EnglishLearn && ./deploy.sh backup >> /var/log/englishlearn/backup.log 2>&1

# 每周日凌晨 3 点清理 30 天前的旧备份
0 3 * * 0 cd /opt/EnglishLearn && find /opt/EnglishLearn_Backups -name "EL_backup_*.tar.gz" -mtime +30 -delete
```

#### 方案 2: systemd timer

创建定时器服务:

```bash
# 创建服务文件
sudo tee /etc/systemd/system/englishlearn-backup.service <<EOF
[Unit]
Description=EnglishLearn Backup Service

[Service]
Type=oneshot
User=root
ExecStart=/opt/EnglishLearn/deploy.sh backup
EOF

# 创建定时器
sudo tee /etc/systemd/system/englishlearn-backup.timer <<EOF
[Unit]
Description=EnglishLearn Daily Backup Timer

[Timer]
OnCalendar=daily
OnCalendar=02:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

# 启用并启动定时器
sudo systemctl enable englishlearn-backup.timer
sudo systemctl start englishlearn-backup.timer

# 查看定时器状态
sudo systemctl list-timers
```

### 2.2 手动备份

#### 命令行备份

```bash
# 基本备份 (包含数据库和媒体文件)
cd /opt/EnglishLearn
sudo ./deploy.sh backup

# 热备份 (不停止服务)
BACKUP_NO_STOP=1 sudo ./deploy.sh backup

# 查看备份列表
sudo ./deploy.sh list

# 恢复最新备份
sudo ./deploy.sh restore latest

# 恢复指定备份
sudo ./deploy.sh restore /path/to/EL_backup_20260124_120000.tar.gz
```

#### Web 界面备份 (管理员功能)

1. 登录系统
2. 进入"备份管理"页面
3. 点击"创建备份"按钮
4. 选择备份内容 (数据库/媒体文件)
5. 点击"创建备份"
6. 备份完成后可下载到本地

### 2.3 备份内容

备份包含以下内容:

- ✅ **数据库**: `el.db` (SQLite 数据库文件)
- ✅ **媒体文件**: `media/` 目录下的所有文件
  - 学生头像
  - 资料库封面图片
  - 练习单照片
  - 上传的音频文件

### 2.4 备份存储

**本地存储:**
- 默认位置: `/opt/EnglishLearn_Backups`
- 建议挂载独立磁盘用于备份

**远程存储 (推荐):**

```bash
# 方案 1: rsync 到远程服务器
rsync -avz --delete /opt/EnglishLearn_Backups/ user@remote-server:/path/to/backups/

# 方案 2: 上传到云存储 (以阿里云 OSS 为例)
ossutil cp -r /opt/EnglishLearn_Backups/ oss://your-bucket/englishlearn-backups/

# 方案 3: 上传到 S3 兼容存储
aws s3 sync /opt/EnglishLearn_Backups/ s3://your-bucket/englishlearn-backups/
```

### 2.5 备份验证

定期验证备份完整性:

```bash
# 验证备份文件完整性
cd /opt/EnglishLearn_Backups
for file in EL_backup_*.tar.gz; do
    if tar -tzf "$file" > /dev/null 2>&1; then
        echo "✓ $file - OK"
    else
        echo "✗ $file - CORRUPTED"
    fi
done

# 测试恢复 (在测试环境)
sudo ./deploy.sh restore latest
```

---

## 升级维护

### 3.1 升级步骤

#### 自动升级 (推荐)

```bash
cd /opt/EnglishLearn
sudo ./deploy.sh update
```

自动升级会:
1. 停止服务
2. 从 GitHub 拉取最新代码
3. 安装/更新 Python 依赖
4. 重启服务

#### 手动升级

```bash
# 1. 备份当前数据
sudo ./deploy.sh backup

# 2. 停止服务
sudo systemctl stop englishlearn

# 3. 拉取最新代码
cd /opt/EnglishLearn
sudo -u englishlearn git pull

# 4. 更新依赖
sudo -u englishlearn /opt/EnglishLearn/venv/bin/pip install -r backend/requirements.txt

# 5. 数据库迁移 (如果需要)
# sudo -u englishlearn /opt/EnglishLearn/venv/bin/python backend/migrate.py

# 6. 重启服务
sudo systemctl restart englishlearn
sudo systemctl restart nginx

# 7. 验证
sudo systemctl status englishlearn
```

### 3.2 回滚操作

如果升级出现问题:

```bash
# 1. 停止服务
sudo systemctl stop englishlearn

# 2. 回滚代码
cd /opt/EnglishLearn
sudo -u englishlearn git reset --hard <previous-commit-hash>

# 或回滚到上一个版本
sudo -u englishlearn git reset --hard HEAD~1

# 3. 恢复备份
sudo ./deploy.sh restore latest

# 4. 重启服务
sudo systemctl restart englishlearn
```

### 3.3 数据库迁移

**注意:** 当前版本使用 SQLite,无需复杂的迁移脚本。

如果未来需要迁移到 PostgreSQL/MySQL:

```bash
# 1. 导出 SQLite 数据
sqlite3 /opt/EnglishLearn/data/el.db .dump > backup.sql

# 2. 转换 SQL 语法 (根据目标数据库)
# ... 使用工具转换 ...

# 3. 导入到新数据库
# psql -U user -d database < backup.sql  # PostgreSQL
# mysql -u user -p database < backup.sql  # MySQL

# 4. 更新环境变量
# DATABASE_URL=postgresql://user:pass@localhost/dbname
```

---

## 监控告警

### 4.1 服务监控

#### 基本监控

```bash
# 查看服务状态
sudo systemctl status englishlearn

# 实时查看日志
sudo journalctl -u englishlearn -f

# 查看最近错误
sudo journalctl -u englishlearn -p err -n 50

# 查看 Nginx 日志
sudo tail -f /var/log/nginx/englishlearn_access.log
sudo tail -f /var/log/nginx/englishlearn_error.log
```

#### 进程监控脚本

```bash
# 创建监控脚本
sudo tee /opt/EnglishLearn/scripts/health_check.sh <<'EOF'
#!/bin/bash
# EnglishLearn 健康检查脚本

LOG_FILE="/var/log/englishlearn/health_check.log"

check_service() {
    if ! systemctl is-active --quiet englishlearn; then
        echo "[$(date)] ERROR: Service is down, attempting restart" >> "$LOG_FILE"
        systemctl restart englishlearn
        # 发送告警 (邮件/钉钉/微信等)
        # curl -X POST https://webhook.example.com/alert ...
    fi
}

check_disk() {
    USAGE=$(df /opt/EnglishLearn/data | tail -1 | awk '{print $5}' | sed 's/%//')
    if [ "$USAGE" -gt 80 ]; then
        echo "[$(date)] WARN: Disk usage is ${USAGE}%" >> "$LOG_FILE"
    fi
}

check_backup() {
    LATEST=$(find /opt/EnglishLearn_Backups -name "EL_backup_*.tar.gz" -mtime -2 | wc -l)
    if [ "$LATEST" -eq 0 ]; then
        echo "[$(date)] WARN: No backup in last 48 hours" >> "$LOG_FILE"
    fi
}

check_service
check_disk
check_backup
EOF

sudo chmod +x /opt/EnglishLearn/scripts/health_check.sh

# 添加到 crontab (每 5 分钟检查一次)
echo "*/5 * * * * /opt/EnglishLearn/scripts/health_check.sh" | sudo crontab -
```

### 4.2 性能监控

使用 `htop` 或 `glances` 监控系统资源:

```bash
# 安装监控工具
sudo apt install htop glances

# 运行
htop
glances
```

### 4.3 日志管理

#### 日志轮转

```bash
# 创建 logrotate 配置
sudo tee /etc/logrotate.d/englishlearn <<EOF
/var/log/englishlearn/*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    create 0640 englishlearn englishlearn
    sharedscripts
    postrotate
        systemctl reload englishlearn > /dev/null 2>&1 || true
    endscript
}
EOF
```

#### 日志分析

```bash
# 统计访问量
sudo awk '{print $1}' /var/log/nginx/englishlearn_access.log | sort | uniq -c | sort -rn | head -20

# 统计 API 调用
sudo grep "GET /api" /var/log/nginx/englishlearn_access.log | wc -l

# 查找错误
sudo grep -i error /var/log/englishlearn/app.log

# 分析响应时间
sudo awk '{print $NF}' /var/log/nginx/englishlearn_access.log | sort -n | tail -100
```

---

## 故障排查

### 5.1 服务无法启动

**症状:** `systemctl start englishlearn` 失败

**排查步骤:**

```bash
# 1. 查看详细错误
sudo systemctl status englishlearn
sudo journalctl -u englishlearn -n 100

# 2. 检查端口占用
sudo netstat -tulnp | grep 8000
sudo lsof -i :8000

# 3. 检查文件权限
ls -la /opt/EnglishLearn/data
ls -la /opt/EnglishLearn/backend

# 4. 手动启动测试
cd /opt/EnglishLearn
sudo -u englishlearn ./venv/bin/uvicorn backend.app.main:app --host 0.0.0.0 --port 8000

# 5. 检查 Python 依赖
./venv/bin/pip list
./venv/bin/pip check
```

**常见原因:**
- 端口被占用 → 修改端口或杀死占用进程
- 权限问题 → `chown -R englishlearn:englishlearn /opt/EnglishLearn`
- Python 依赖缺失 → 重新安装依赖
- 数据库损坏 → 恢复备份

### 5.2 Nginx 502 Bad Gateway

**症状:** 访问页面显示 502 错误

**排查步骤:**

```bash
# 1. 检查后端服务是否运行
sudo systemctl status englishlearn

# 2. 检查 Nginx 配置
sudo nginx -t

# 3. 查看 Nginx 错误日志
sudo tail -f /var/log/nginx/englishlearn_error.log

# 4. 检查端口监听
sudo netstat -tulnp | grep 8000

# 5. 测试后端连接
curl http://127.0.0.1:8000/api/health
```

**常见原因:**
- 后端服务未启动 → `systemctl start englishlearn`
- 端口配置错误 → 检查 Nginx upstream 配置
- 防火墙阻止 → `ufw allow 8000` (内部端口)

### 5.3 数据库损坏

**症状:** 服务启动失败,日志显示数据库错误

**修复步骤:**

```bash
# 1. 检查数据库完整性
sqlite3 /opt/EnglishLearn/data/el.db "PRAGMA integrity_check;"

# 2. 如果损坏,尝试修复
sqlite3 /opt/EnglishLearn/data/el.db ".recover" > recovered.sql
mv /opt/EnglishLearn/data/el.db /opt/EnglishLearn/data/el.db.corrupted
sqlite3 /opt/EnglishLearn/data/el.db < recovered.sql

# 3. 如果无法修复,恢复备份
sudo ./deploy.sh restore latest

# 4. 重启服务
sudo systemctl restart englishlearn
```

### 5.4 磁盘空间不足

**症状:** 服务异常,日志显示 "No space left on device"

**解决步骤:**

```bash
# 1. 检查磁盘使用情况
df -h
du -sh /opt/EnglishLearn/*

# 2. 清理日志
sudo journalctl --vacuum-time=7d
sudo find /var/log -name "*.gz" -mtime +30 -delete

# 3. 清理旧备份
cd /opt/EnglishLearn
sudo ./deploy.sh cleanup  # 清理 30 天前的备份

# 4. 清理媒体文件 (谨慎!)
# 删除未使用的媒体文件需要数据库查询

# 5. 扩展磁盘或挂载新磁盘
# ... 根据云服务商操作 ...
```

### 5.5 性能问题

**症状:** 页面加载慢,API 响应慢

**优化步骤:**

```bash
# 1. 检查系统资源
top
htop
free -h

# 2. 检查数据库大小
du -h /opt/EnglishLearn/data/el.db

# 3. 优化数据库
sqlite3 /opt/EnglishLearn/data/el.db "VACUUM;"
sqlite3 /opt/EnglishLearn/data/el.db "ANALYZE;"

# 4. 增加 Nginx 缓存
# 编辑 /etc/nginx/sites-available/englishlearn
# 添加:
# proxy_cache_path /var/cache/nginx levels=1:2 keys_zone=my_cache:10m;
# proxy_cache my_cache;

# 5. 增加 uvicorn worker 数量
# 编辑 /etc/systemd/system/englishlearn.service
# ExecStart 添加 --workers 4
```

---

## 安全加固

### 6.1 HTTPS 配置

#### Let's Encrypt 免费证书

```bash
# 1. 安装 certbot
sudo apt install certbot python3-certbot-nginx

# 2. 获取证书
sudo certbot --nginx -d your-domain.com

# 3. 自动续期
sudo certbot renew --dry-run

# Certbot 会自动配置 Nginx HTTPS
```

#### 手动配置 HTTPS

```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # ... 其他配置 ...
}

server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$server_name$request_uri;
}
```

### 6.2 防火墙配置

```bash
# UFW (Ubuntu/Debian)
sudo ufw enable
sudo ufw allow 22/tcp   # SSH
sudo ufw allow 80/tcp   # HTTP
sudo ufw allow 443/tcp  # HTTPS
sudo ufw deny 8000/tcp  # 禁止外部访问后端端口

# Firewalld (CentOS/RHEL)
sudo firewall-cmd --permanent --add-service=ssh
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
```

### 6.3 安全检查清单

- [ ] 修改默认管理员密码
- [ ] 禁用 root SSH 登录
- [ ] 配置 SSH 密钥认证
- [ ] 启用防火墙
- [ ] 配置 HTTPS
- [ ] 限制 API 访问频率 (Rate Limiting)
- [ ] 定期更新系统和依赖包
- [ ] 配置备份加密
- [ ] 启用审计日志
- [ ] 定期安全扫描

---

## 性能优化

### 7.1 数据库优化

```bash
# 定期优化数据库
sqlite3 /opt/EnglishLearn/data/el.db <<EOF
VACUUM;
ANALYZE;
PRAGMA optimize;
EOF
```

### 7.2 Nginx 优化

```nginx
# 编辑 /etc/nginx/nginx.conf

worker_processes auto;
worker_rlimit_nofile 65535;

events {
    worker_connections 4096;
    use epoll;
    multi_accept on;
}

http {
    # 启用 gzip 压缩
    gzip on;
    gzip_vary on;
    gzip_comp_level 6;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml;

    # 静态文件缓存
    open_file_cache max=10000 inactive=30s;
    open_file_cache_valid 60s;
    open_file_cache_min_uses 2;

    # 连接优化
    keepalive_timeout 65;
    keepalive_requests 100;
}
```

### 7.3 应用优化

```bash
# 增加 uvicorn workers
# 编辑 /etc/systemd/system/englishlearn.service
ExecStart=/opt/EnglishLearn/venv/bin/uvicorn backend.app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 4 \
    --log-level info

sudo systemctl daemon-reload
sudo systemctl restart englishlearn
```

---

## 附录

### 常用命令速查

```bash
# 服务管理
sudo systemctl start englishlearn     # 启动
sudo systemctl stop englishlearn      # 停止
sudo systemctl restart englishlearn   # 重启
sudo systemctl status englishlearn    # 状态
sudo systemctl enable englishlearn    # 开机启动

# 日志查看
sudo journalctl -u englishlearn -f    # 实时日志
sudo journalctl -u englishlearn -n 100 # 最近 100 行

# 备份管理
cd /opt/EnglishLearn
sudo ./deploy.sh backup               # 创建备份
sudo ./deploy.sh restore latest       # 恢复最新备份
sudo ./deploy.sh list                 # 列出备份

# 代码更新
sudo ./deploy.sh update               # 更新代码并重启

# 数据库
sqlite3 /opt/EnglishLearn/data/el.db  # 进入数据库
.tables                                # 列出表
.schema students                       # 查看表结构
SELECT * FROM students LIMIT 10;       # 查询数据
```

### 重要文件位置

```
/opt/EnglishLearn              # 应用根目录
  ├── backend/                 # 后端代码
  ├── frontend/                # 前端代码
  ├── data/                    # 数据目录
  │   ├── el.db               # 数据库
  │   └── media/              # 媒体文件
  ├── venv/                    # Python 虚拟环境
  └── deploy.sh                # 部署脚本

/etc/englishlearn.env          # 环境变量配置
/etc/systemd/system/englishlearn.service  # systemd 服务
/etc/nginx/sites-available/englishlearn   # Nginx 配置
/opt/EnglishLearn_Backups      # 备份目录
/var/log/englishlearn/         # 应用日志
/var/log/nginx/                # Nginx 日志
```

---

**文档版本:** 1.0
**更新时间:** 2026-01-24
**维护者:** EnglishLearn Team
