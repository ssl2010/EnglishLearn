# EnglishLearn 安装指南

## 快速安装

```bash
# 一键安装（仓库已公开，无需认证）
curl -fsSL https://raw.githubusercontent.com/ssl2010/EnglishLearn/main/install.sh | sudo bash
```

或者下载后安装：
```bash
wget https://raw.githubusercontent.com/ssl2010/EnglishLearn/main/install.sh
sudo bash install.sh
```

---

## 安装方式

### 方式1: 远程一键安装（推荐）

```bash
curl -fsSL https://raw.githubusercontent.com/ssl2010/EnglishLearn/main/install.sh | sudo bash
```

### 方式2: 手动克隆后安装

```bash
# 克隆代码
git clone https://github.com/ssl2010/EnglishLearn.git /opt/EnglishLearn

# 进入目录并安装
cd /opt/EnglishLearn
SKIP_GIT_CLONE=true sudo -E bash install.sh
```

### 方式3: 已有安装升级

```bash
cd /opt/EnglishLearn
sudo bash install.sh
# 脚本会自动 git pull 更新代码
```

---

## 安装后配置

### 1. 配置 AI 批改功能（必须）

编辑环境配置文件：
```bash
sudo nano /etc/englishlearn.env
```

#### 方式A: OpenAI 兼容 API（推荐）

支持 OpenAI、火山引擎豆包、阿里通义千问等。

**火山引擎豆包（推荐国内使用）：**
```bash
ARK_API_KEY=你的火山引擎API密钥
EL_OPENAI_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
EL_OPENAI_VISION_MODEL=doubao-seed-1-6-251015
```

**OpenAI 官方：**
```bash
OPENAI_API_KEY=sk-xxx
EL_OPENAI_BASE_URL=https://api.openai.com/v1
EL_OPENAI_VISION_MODEL=gpt-4o-mini
```

**阿里通义千问：**
```bash
OPENAI_API_KEY=sk-xxx
EL_OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EL_OPENAI_VISION_MODEL=qwen-vl-max
```

#### 方式B: 百度 OCR

```bash
BAIDU_OCR_API_KEY=你的百度OCR API Key
BAIDU_OCR_SECRET_KEY=你的百度OCR Secret Key
```

### 2. 重启服务使配置生效

```bash
sudo systemctl restart englishlearn
```

### 3. 验证配置

```bash
# 查看服务状态
sudo systemctl status englishlearn

# 查看实时日志
journalctl -u englishlearn -f
```

---

## 环境变量说明

### 安装选项

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SKIP_GIT_CLONE` | `false` | 跳过 git 克隆步骤 |
| `SKIP_GIT_PULL` | `false` | 跳过 git 拉取 |
| `ALLOW_GIT_PULL_FAILURE` | `false` | 拉取失败不终止安装 |
| `ALLOW_DIRTY_PULL` | `false` | 工作区有改动也尝试拉取 |

### AI/LLM 配置

| 变量 | 说明 |
|------|------|
| `OPENAI_API_KEY` | OpenAI API 密钥 |
| `ARK_API_KEY` | 火山引擎 API 密钥 |
| `EL_OPENAI_BASE_URL` | API 地址 |
| `EL_OPENAI_VISION_MODEL` | 模型名称 |
| `BAIDU_OCR_API_KEY` | 百度 OCR API Key |
| `BAIDU_OCR_SECRET_KEY` | 百度 OCR Secret Key |
| `EL_MARK_GRADING_PROVIDER` | 批改服务: `auto`/`openai`/`baidu` |

### 系统配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `EL_DB_PATH` | `/opt/EnglishLearn/data/el.db` | 数据库路径 |
| `EL_MEDIA_DIR` | `/opt/EnglishLearn/data/media` | 媒体文件目录 |
| `BACKUP_DIR` | `/opt/EnglishLearn_Backups` | 备份目录 |

---

## 常用命令

### 服务管理

```bash
# 启动/停止/重启
sudo systemctl start englishlearn
sudo systemctl stop englishlearn
sudo systemctl restart englishlearn

# 查看状态
sudo systemctl status englishlearn

# 查看日志
journalctl -u englishlearn -f
journalctl -u englishlearn -n 100
```

### 备份与恢复

```bash
cd /opt/EnglishLearn

# 手动备份
sudo ./deploy.sh backup

# 查看备份列表
sudo ./deploy.sh list

# 恢复备份
sudo ./deploy.sh restore latest
```

### 密码重置

如果忘记管理员密码：
```bash
cd /opt/EnglishLearn
sudo -u englishlearn \
  EL_DB_PATH=/opt/EnglishLearn/data/el.db \
  venv/bin/python -c \
  "from backend.app.auth import set_account_password; set_account_password(1, 'NewPassword123')"
sudo systemctl restart englishlearn
```

---

## 目录结构

安装完成后的目录结构：

```
/opt/EnglishLearn/          # 应用目录
├── backend/                # 后端代码
├── frontend/               # 前端代码
├── venv/                   # Python 虚拟环境
└── data/                   # 数据目录
    ├── el.db               # SQLite 数据库
    └── media/              # 媒体文件

/opt/EnglishLearn_Backups/  # 备份目录

/etc/englishlearn.env       # 环境配置文件
/etc/systemd/system/englishlearn.service  # systemd 服务
/etc/nginx/sites-available/englishlearn   # Nginx 配置
/var/log/englishlearn/      # 日志目录
```

---

## 故障排除

### 问题: 无法登录

**可能原因：**
1. 数据库中已有旧账号，密码未知
2. 管理员账号未正确初始化

**解决方案：**
```bash
# 检查账号是否存在
sqlite3 /opt/EnglishLearn/data/el.db "SELECT id,username,is_super_admin FROM accounts;"

# 重置密码（见上文"密码重置"）
```

### 问题: AI 批改不工作

**检查步骤：**
```bash
# 1. 检查配置
grep -E "OPENAI|ARK|BAIDU" /etc/englishlearn.env

# 2. 查看日志
journalctl -u englishlearn | grep -i "openai\|api\|error"

# 3. 测试 API 连接
curl -H "Authorization: Bearer $YOUR_API_KEY" \
  https://ark.cn-beijing.volces.com/api/v3/models
```

### 问题: 服务启动失败

```bash
# 查看详细错误
sudo systemctl status englishlearn
journalctl -u englishlearn -n 50

# 常见问题：
# - 权限问题：检查数据目录权限
sudo chown -R englishlearn:englishlearn /opt/EnglishLearn/data

# - 端口占用
sudo lsof -i :8000
```

### 问题: Nginx 502 错误

```bash
# 检查后端服务是否运行
sudo systemctl status englishlearn

# 检查端口
curl http://127.0.0.1:8000/api/auth/me
# 应返回 401（未认证）或 200

# 重启 Nginx
sudo systemctl restart nginx
```

---

## 卸载

```bash
# 停止并禁用服务
sudo systemctl stop englishlearn
sudo systemctl disable englishlearn

# 删除服务文件
sudo rm /etc/systemd/system/englishlearn.service
sudo systemctl daemon-reload

# 删除 Nginx 配置
sudo rm /etc/nginx/sites-enabled/englishlearn
sudo rm /etc/nginx/sites-available/englishlearn
sudo systemctl restart nginx

# 删除应用目录
sudo rm -rf /opt/EnglishLearn

# 删除备份目录（可选）
sudo rm -rf /opt/EnglishLearn_Backups

# 删除环境变量文件
sudo rm /etc/englishlearn.env

# 删除日志目录
sudo rm -rf /var/log/englishlearn

# 删除用户（可选）
sudo userdel englishlearn
sudo groupdel englishlearn
```

---

## 更新记录

### 2026-01-27
- 修复用户组创建问题（解决 chown 失败）
- 修复管理员账号初始化逻辑（解决无法登录）
- 增强数据库权限验证和自动修复
- 改进 systemd 服务权限配置
- 添加完整的 LLM/OCR 配置支持
- 增强安装后自检功能
- 改进密码来源提示

### 2026-01-24
- 修复 useradd 命令找不到问题
- 改进 git 克隆和认证处理
- 添加多种安装方式支持

---

## 技术支持

- GitHub Issues: https://github.com/ssl2010/EnglishLearn/issues
- 配置文件模板: `.env.example`
