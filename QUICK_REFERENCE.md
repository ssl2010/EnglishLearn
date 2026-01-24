# EnglishLearn 运维快速参考卡片

## 🚀 快速部署

```bash
# 一键安装
curl -fsSL https://raw.githubusercontent.com/ssl2010/EnglishLearn/main/install.sh | sudo bash
```

安装完成后访问: `http://服务器IP`

---

## 📦 服务管理

```bash
sudo systemctl start englishlearn     # 启动服务
sudo systemctl stop englishlearn      # 停止服务
sudo systemctl restart englishlearn   # 重启服务
sudo systemctl status englishlearn    # 查看状态
```

---

## 💾 备份操作

```bash
cd /opt/EnglishLearn

# 创建备份
sudo ./deploy.sh backup

# 查看备份列表
sudo ./deploy.sh list

# 恢复最新备份
sudo ./deploy.sh restore latest
```

**Web 界面备份**: 访问 `http://服务器IP/backup.html` (管理员)

---

## 📝 日志查看

```bash
# 实时日志
sudo journalctl -u englishlearn -f

# 最近100行
sudo journalctl -u englishlearn -n 100

# 只看错误
sudo journalctl -u englishlearn -p err

# Nginx 日志
sudo tail -f /var/log/nginx/englishlearn_access.log
sudo tail -f /var/log/nginx/englishlearn_error.log
```

---

## 🔄 代码更新

```bash
cd /opt/EnglishLearn
sudo ./deploy.sh update
```

更新流程:
1. 停止服务
2. 拉取最新代码
3. 更新依赖
4. 重启服务

---

## 🔍 故障排查

### 服务无法启动
```bash
sudo journalctl -u englishlearn -n 100
sudo netstat -tulnp | grep 8000
ls -la /opt/EnglishLearn/data
```

### 502 Bad Gateway
```bash
sudo systemctl status englishlearn
curl http://127.0.0.1:8000/api/health
sudo nginx -t
```

### 磁盘空间不足
```bash
df -h
sudo journalctl --vacuum-time=7d
cd /opt/EnglishLearn && sudo ./deploy.sh cleanup
```

### 数据库问题
```bash
sqlite3 /opt/EnglishLearn/data/el.db "PRAGMA integrity_check;"
sudo ./deploy.sh restore latest
```

---

## 📊 性能优化

```bash
# 优化数据库
sqlite3 /opt/EnglishLearn/data/el.db "VACUUM; ANALYZE;"

# 查看资源占用
htop

# 检查磁盘IO
iotop
```

---

## 🔐 安全检查

```bash
# 配置 HTTPS (Let's Encrypt)
sudo certbot --nginx -d your-domain.com

# 查看防火墙状态
sudo ufw status

# 查看登录失败记录
sudo grep "Failed password" /var/log/auth.log | tail -20
```

---

## 📍 重要文件位置

| 文件/目录 | 路径 |
|----------|------|
| 应用目录 | `/opt/EnglishLearn` |
| 数据库 | `/opt/EnglishLearn/data/el.db` |
| 媒体文件 | `/opt/EnglishLearn/data/media/` |
| 备份目录 | `/opt/EnglishLearn_Backups` |
| 环境配置 | `/etc/englishlearn.env` |
| systemd 服务 | `/etc/systemd/system/englishlearn.service` |
| Nginx 配置 | `/etc/nginx/sites-available/englishlearn` |
| 应用日志 | `/var/log/englishlearn/` |
| Nginx 日志 | `/var/log/nginx/` |

---

## ⏰ 定时任务

```bash
# 编辑 crontab
sudo crontab -e

# 每天凌晨2点备份
0 2 * * * cd /opt/EnglishLearn && ./deploy.sh backup

# 每周日凌晨3点清理旧备份
0 3 * * 0 find /opt/EnglishLearn_Backups -name "*.tar.gz" -mtime +30 -delete

# 每天凌晨4点优化数据库
0 4 * * * sqlite3 /opt/EnglishLearn/data/el.db "VACUUM; ANALYZE;"
```

---

## 🆘 紧急情况

### 回滚到上一个版本
```bash
sudo systemctl stop englishlearn
cd /opt/EnglishLearn
sudo -u englishlearn git reset --hard HEAD~1
sudo ./deploy.sh restore latest
sudo systemctl restart englishlearn
```

### 紧急联系
- GitHub Issues: https://github.com/ssl2010/EnglishLearn/issues
- 文档: `/opt/EnglishLearn/docs/DEPLOYMENT.md`

---

## 📞 支持

- **文档**: `docs/DEPLOYMENT.md` - 完整部署文档
- **文档**: `docs/OPS_BEST_PRACTICES.md` - 运维最佳实践
- **脚本**: `install.sh` - 一键安装脚本
- **脚本**: `deploy.sh` - 运维管理脚本

**保存此卡片以便快速查阅!**
