#!/usr/bin/env bash
#
# EnglishLearn 一键安装脚本
# 适用于 Ubuntu 20.04+ / Debian 11+ / CentOS 8+
#
# 使用方法:
#   curl -fsSL https://raw.githubusercontent.com/ssl2010/EnglishLearn/main/install.sh | sudo bash
#   或者:
#   wget -O - https://raw.githubusercontent.com/ssl2010/EnglishLearn/main/install.sh | sudo bash
#   或者本地执行:
#   sudo bash install.sh
#

set -euo pipefail

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

info() { echo -e "${BLUE}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# 检查是否为 root
if [[ $EUID -ne 0 ]]; then
   error "此脚本必须以 root 权限运行 (使用 sudo)"
fi

# 配置变量
APP_NAME="EnglishLearn"
APP_DIR="/opt/EnglishLearn"
DATA_DIR="$APP_DIR/data"
DB_PATH="$DATA_DIR/el.db"
MEDIA_DIR="$DATA_DIR/media"
SERVICE_NAME="englishlearn"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
NGINX_CONF="/etc/nginx/sites-available/${SERVICE_NAME}"
NGINX_LINK="/etc/nginx/sites-enabled/${SERVICE_NAME}"
ENV_FILE="/etc/englishlearn.env"
BACKUP_DIR="/opt/EnglishLearn_Backups"

# 默认配置
DEFAULT_PORT=8000
DEFAULT_DOMAIN="localhost"
DEFAULT_ADMIN_EMAIL="admin@example.com"
DEFAULT_ADMIN_PASSWORD=$(openssl rand -base64 12)

echo "
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║          EnglishLearn 一键安装脚本 v1.0                  ║
║                                                           ║
║   本脚本将自动安装和配置 EnglishLearn 系统                ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
"

# 检测操作系统
detect_os() {
    info "检测操作系统..."
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        OS=$ID
        VER=$VERSION_ID
        info "检测到系统: $OS $VER"
    else
        error "无法检测操作系统"
    fi
}

# 安装依赖
install_dependencies() {
    info "安装系统依赖..."

    case "$OS" in
        ubuntu|debian)
            apt-get update
            apt-get install -y \
                python3 python3-pip python3-venv \
                git curl wget \
                nginx \
                sqlite3 \
                libopencv-dev python3-opencv \
                build-essential
            ;;
        centos|rhel|fedora)
            yum update -y
            yum install -y \
                python3 python3-pip python3-virtualenv \
                git curl wget \
                nginx \
                sqlite \
                opencv opencv-devel python3-opencv \
                gcc gcc-c++ make
            ;;
        *)
            error "不支持的操作系统: $OS"
            ;;
    esac

    success "系统依赖安装完成"
}

# 创建系统用户
create_user() {
    info "创建系统用户..."

    if ! id -u englishlearn >/dev/null 2>&1; then
        useradd -r -s /bin/bash -d "$APP_DIR" -m englishlearn
        success "用户 englishlearn 创建成功"
    else
        info "用户 englishlearn 已存在"
    fi
}

# 克隆代码
clone_repository() {
    info "克隆代码仓库..."

    if [[ -d "$APP_DIR/.git" ]]; then
        warn "代码目录已存在,拉取最新代码..."
        cd "$APP_DIR"
        git pull
    else
        git clone https://github.com/ssl2010/EnglishLearn.git "$APP_DIR"
    fi

    chown -R englishlearn:englishlearn "$APP_DIR"
    success "代码克隆完成"
}

# 设置 Python 虚拟环境
setup_venv() {
    info "创建 Python 虚拟环境..."

    cd "$APP_DIR"
    sudo -u englishlearn python3 -m venv venv

    info "安装 Python 依赖包..."
    sudo -u englishlearn "$APP_DIR/venv/bin/pip" install --upgrade pip
    sudo -u englishlearn "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/backend/requirements.txt"

    success "Python 环境配置完成"
}

# 创建数据目录
setup_data_directory() {
    info "创建数据目录..."

    mkdir -p "$DATA_DIR"
    mkdir -p "$MEDIA_DIR"
    mkdir -p "$BACKUP_DIR"

    chown -R englishlearn:englishlearn "$DATA_DIR"
    chown -R englishlearn:englishlearn "$BACKUP_DIR"
    chmod 755 "$DATA_DIR"
    chmod 755 "$MEDIA_DIR"

    success "数据目录创建完成"
}

# 初始化数据库
init_database() {
    info "初始化数据库..."

    if [[ -f "$DB_PATH" ]]; then
        warn "数据库已存在,跳过初始化"
        info "运行数据库迁移..."
        cd "$APP_DIR/backend"
        sudo -u englishlearn "$APP_DIR/venv/bin/python" migration_manager.py migrate
    else
        cd "$APP_DIR/backend"
        sudo -u englishlearn "$APP_DIR/venv/bin/python" init_db.py

        # 移动数据库到数据目录
        if [[ -f "$APP_DIR/backend/el.db" ]]; then
            mv "$APP_DIR/backend/el.db" "$DB_PATH"
            chown englishlearn:englishlearn "$DB_PATH"
        fi

        success "数据库初始化完成"

        info "运行数据库迁移..."
        sudo -u englishlearn DATABASE_URL="sqlite:///${DB_PATH}" "$APP_DIR/venv/bin/python" migration_manager.py migrate
    fi
}

# 配置环境变量
setup_env() {
    info "配置环境变量..."

    # 生成随机密钥
    SECRET_KEY=$(openssl rand -base64 32)

    cat > "$ENV_FILE" <<EOF
# EnglishLearn 配置文件
# 生成时间: $(date)

# 应用配置
APP_NAME=EnglishLearn
APP_VERSION=1.0.0
DEBUG=false

# 数据库配置
DATABASE_URL=sqlite:///${DB_PATH}

# 媒体文件目录
MEDIA_DIR=${MEDIA_DIR}

# 服务器配置
HOST=0.0.0.0
PORT=${DEFAULT_PORT}

# 安全配置
SECRET_KEY=${SECRET_KEY}
ALLOWED_HOSTS=localhost,127.0.0.1

# OpenAI API 配置 (可选,用于 OCR 功能)
# OPENAI_API_KEY=your_api_key_here
# OPENAI_BASE_URL=https://api.openai.com/v1

# 管理员账号 (首次安装)
ADMIN_EMAIL=${DEFAULT_ADMIN_EMAIL}
ADMIN_PASSWORD=${DEFAULT_ADMIN_PASSWORD}

# 备份配置
BACKUP_DIR=${BACKUP_DIR}
BACKUP_RETENTION_DAYS=30

# 日志配置
LOG_LEVEL=INFO
LOG_FILE=/var/log/englishlearn/app.log
EOF

    chmod 600 "$ENV_FILE"

    # 创建日志目录
    mkdir -p /var/log/englishlearn
    chown -R englishlearn:englishlearn /var/log/englishlearn

    success "环境变量配置完成"
    info "管理员初始密码: ${DEFAULT_ADMIN_PASSWORD}"
    warn "请妥善保存管理员密码!"
}

# 配置 systemd 服务
setup_systemd() {
    info "配置 systemd 服务..."

    cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=EnglishLearn Web Application
After=network.target

[Service]
Type=simple
User=englishlearn
Group=englishlearn
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE

ExecStart=$APP_DIR/venv/bin/uvicorn backend.app.main:app \\
    --host 0.0.0.0 \\
    --port ${DEFAULT_PORT} \\
    --log-level info

Restart=always
RestartSec=10

# 安全配置
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$DATA_DIR $BACKUP_DIR /var/log/englishlearn

# 资源限制
LimitNOFILE=65536
LimitNPROC=4096

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME"

    success "systemd 服务配置完成"
}

# 配置 nginx
setup_nginx() {
    info "配置 Nginx 反向代理..."

    cat > "$NGINX_CONF" <<'EOF'
# EnglishLearn Nginx 配置

upstream englishlearn_backend {
    server 127.0.0.1:8000;
    keepalive 32;
}

server {
    listen 80;
    server_name _;  # 替换为实际域名

    client_max_body_size 50M;

    # 日志
    access_log /var/log/nginx/englishlearn_access.log;
    error_log /var/log/nginx/englishlearn_error.log;

    # 静态文件 (前端)
    location / {
        root /opt/EnglishLearn/frontend;
        try_files $uri $uri/ /index.html;
        index index.html;

        # 缓存静态资源
        location ~* \.(css|js|jpg|jpeg|png|gif|ico|svg|woff|woff2|ttf|eot)$ {
            expires 30d;
            add_header Cache-Control "public, immutable";
        }
    }

    # API 请求
    location /api/ {
        proxy_pass http://englishlearn_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # 超时设置
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    # 媒体文件
    location /media/ {
        alias /opt/EnglishLearn/data/media/;
        expires 7d;
        add_header Cache-Control "public";
    }

    # 安全头
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
}
EOF

    # 创建软链接
    if [[ ! -L "$NGINX_LINK" ]]; then
        ln -s "$NGINX_CONF" "$NGINX_LINK"
    fi

    # 删除默认配置
    if [[ -f /etc/nginx/sites-enabled/default ]]; then
        rm /etc/nginx/sites-enabled/default
    fi

    # 测试配置
    nginx -t

    # 重启 nginx
    systemctl restart nginx
    systemctl enable nginx

    success "Nginx 配置完成"
}

# 配置防火墙
setup_firewall() {
    info "配置防火墙..."

    if command -v ufw >/dev/null 2>&1; then
        ufw allow 80/tcp
        ufw allow 443/tcp
        ufw --force enable
        success "UFW 防火墙配置完成"
    elif command -v firewall-cmd >/dev/null 2>&1; then
        firewall-cmd --permanent --add-service=http
        firewall-cmd --permanent --add-service=https
        firewall-cmd --reload
        success "Firewalld 防火墙配置完成"
    else
        warn "未检测到防火墙,请手动配置"
    fi
}

# 启动服务
start_services() {
    info "启动服务..."

    systemctl start "$SERVICE_NAME"
    systemctl status "$SERVICE_NAME" --no-pager

    success "服务启动成功"
}

# 显示安装信息
show_info() {
    echo ""
    success "════════════════════════════════════════════════════════"
    success "              EnglishLearn 安装完成!                   "
    success "════════════════════════════════════════════════════════"
    echo ""
    info "访问地址: http://$(hostname -I | awk '{print $1}')"
    info "         或 http://localhost"
    echo ""
    info "管理员账号: ${DEFAULT_ADMIN_EMAIL}"
    info "管理员密码: ${DEFAULT_ADMIN_PASSWORD}"
    echo ""
    warn "请立即登录并修改管理员密码!"
    echo ""
    info "常用命令:"
    echo "  启动服务: systemctl start ${SERVICE_NAME}"
    echo "  停止服务: systemctl stop ${SERVICE_NAME}"
    echo "  重启服务: systemctl restart ${SERVICE_NAME}"
    echo "  查看状态: systemctl status ${SERVICE_NAME}"
    echo "  查看日志: journalctl -u ${SERVICE_NAME} -f"
    echo ""
    info "备份命令:"
    echo "  手动备份: cd $APP_DIR && sudo ./deploy.sh backup"
    echo "  查看备份: cd $APP_DIR && sudo ./deploy.sh list"
    echo "  恢复备份: cd $APP_DIR && sudo ./deploy.sh restore latest"
    echo ""
    info "配置文件位置:"
    echo "  环境变量: ${ENV_FILE}"
    echo "  Nginx 配置: ${NGINX_CONF}"
    echo "  systemd 服务: ${SERVICE_FILE}"
    echo ""
    info "数据位置:"
    echo "  应用目录: ${APP_DIR}"
    echo "  数据目录: ${DATA_DIR}"
    echo "  数据库: ${DB_PATH}"
    echo "  媒体文件: ${MEDIA_DIR}"
    echo "  备份目录: ${BACKUP_DIR}"
    echo ""
    success "════════════════════════════════════════════════════════"
}

# 主流程
main() {
    detect_os
    install_dependencies
    create_user
    clone_repository
    setup_venv
    setup_data_directory
    init_database
    setup_env
    setup_systemd
    setup_nginx
    setup_firewall
    start_services
    show_info
}

# 执行安装
main

exit 0
