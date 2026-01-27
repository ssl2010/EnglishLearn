#!/usr/bin/env bash
#
# EnglishLearn 一键安装脚本
# 适用于 Ubuntu 20.04+ / Debian 11+ / CentOS 8+
#
# 使用方法:
#   方法1: 远程执行（需配置 SSH 密钥）
#   curl -fsSL https://raw.githubusercontent.com/ssl2010/EnglishLearn/main/install.sh | sudo bash
#
#   方法2: 本地执行
#   sudo bash install.sh
#
#   方法3: 手动克隆后安装（推荐）
#   git clone git@github.com:ssl2010/EnglishLearn.git /opt/EnglishLearn
#   cd /opt/EnglishLearn
#   SKIP_GIT_CLONE=true sudo -E bash install.sh
#
# 环境变量:
#   SKIP_GIT_CLONE=true  跳过 git 克隆步骤（适用于已手动克隆代码的情况）
#   SKIP_GIT_PULL=true   跳过 git 拉取（保留本地代码）
#   ALLOW_GIT_PULL_FAILURE=true  拉取失败不终止安装
#   ALLOW_DIRTY_PULL=true  工作区有改动也尝试拉取
#   GIT_PULL_RETRIES=3    拉取失败重试次数
#   GIT_PULL_SLEEP=3      拉取失败重试间隔（秒）
#   GIT_CLONE_METHOD=auto|ssh|https  选择克隆方式（默认 auto 优先 HTTPS）
#   GITHUB_PAT=xxxxxxxx  私有仓库使用 HTTPS 克隆时的 GitHub Personal Access Token（PAT）
#   GIT_SSH_KEY=/path/to/key  指定 SSH 私钥路径（用于 root 克隆时复用已有密钥）
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

# 安装选项（可通过环境变量配置）
SKIP_GIT_CLONE="${SKIP_GIT_CLONE:-false}"  # 设置为 true 跳过 git 克隆
SKIP_GIT_PULL="${SKIP_GIT_PULL:-false}"  # 设置为 true 跳过 git 拉取
ALLOW_GIT_PULL_FAILURE="${ALLOW_GIT_PULL_FAILURE:-false}"  # true 时拉取失败不终止安装
ALLOW_DIRTY_PULL="${ALLOW_DIRTY_PULL:-false}"  # true 时即使工作区有改动也尝试拉取
GIT_PULL_RETRIES="${GIT_PULL_RETRIES:-3}"
GIT_PULL_SLEEP="${GIT_PULL_SLEEP:-3}"
GIT_CLONE_METHOD="${GIT_CLONE_METHOD:-auto}"  # auto|ssh|https
GITHUB_PAT="${GITHUB_PAT:-}"  # HTTPS 克隆时使用的 PAT
GIT_SSH_KEY="${GIT_SSH_KEY:-}"  # 指定 SSH 私钥路径

# 默认配置
DEFAULT_PORT=8000
DEFAULT_DOMAIN="localhost"
DEFAULT_ADMIN_USER="admin"

# 生成安全的随机密码（确保至少8位且包含字母数字）
generate_password() {
    local pw=""
    # 尝试使用 openssl
    if command -v openssl >/dev/null 2>&1; then
        pw=$(openssl rand -base64 12 | tr -dc 'a-zA-Z0-9' | head -c 12)
    fi
    # 如果 openssl 失败或密码太短，使用 /dev/urandom
    if [[ ${#pw} -lt 8 ]]; then
        pw=$(tr -dc 'a-zA-Z0-9' < /dev/urandom | head -c 12)
    fi
    # 最后的后备方案
    if [[ ${#pw} -lt 8 ]]; then
        pw="Admin$(date +%s | tail -c 6)"
    fi
    echo "$pw"
}

DEFAULT_ADMIN_PASSWORD=$(generate_password)
FINAL_ADMIN_USER="$DEFAULT_ADMIN_USER"
FINAL_ADMIN_PASSWORD="$DEFAULT_ADMIN_PASSWORD"
ADMIN_PASSWORD_SOURCE="generated"

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

    # 先确保用户组存在
    if ! getent group englishlearn >/dev/null 2>&1; then
        if command -v /usr/sbin/groupadd >/dev/null 2>&1; then
            /usr/sbin/groupadd -r englishlearn
            info "用户组 englishlearn 创建成功"
        elif command -v groupadd >/dev/null 2>&1; then
            groupadd -r englishlearn
            info "用户组 englishlearn 创建成功"
        fi
    else
        info "用户组 englishlearn 已存在"
    fi

    if ! id -u englishlearn >/dev/null 2>&1; then
        # 尝试使用 useradd（需要完整路径）
        if command -v /usr/sbin/useradd >/dev/null 2>&1; then
            /usr/sbin/useradd -r -s /bin/bash -d "$APP_DIR" -g englishlearn englishlearn
        # 如果没有 useradd，使用 adduser（Debian/Ubuntu）
        elif command -v adduser >/dev/null 2>&1; then
            adduser --system --home "$APP_DIR" --shell /bin/bash --ingroup englishlearn englishlearn
        else
            error "无法找到 useradd 或 adduser 命令，请手动创建用户 englishlearn"
        fi
        success "用户 englishlearn 创建成功"
    else
        info "用户 englishlearn 已存在"
        # 确保用户在正确的组中
        usermod -g englishlearn englishlearn 2>/dev/null || true
    fi
}

# 克隆代码
clone_repository() {
    local repo_ssh="git@github.com:ssl2010/EnglishLearn.git"
    local repo_https="https://github.com/ssl2010/EnglishLearn.git"
    local ssh_cmd=""
    local git_env_common=()
    local remote_url=""

    build_ssh_command() {
        local key="$1"
        local cmd="ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new"
        if [[ -n "$key" ]]; then
            cmd="$cmd -i $key -o IdentitiesOnly=yes"
        fi
        echo "$cmd"
    }

    check_repo_access_ssh() {
        GIT_SSH_COMMAND="$ssh_cmd" git ls-remote "$repo_ssh" &>/dev/null
    }

    git_pull_with_retries() {
        local attempt=1
        while true; do
            if "$@"; then
                return 0
            fi
            if [[ "$attempt" -ge "$GIT_PULL_RETRIES" ]]; then
                return 1
            fi
            warn "git pull 失败，${GIT_PULL_SLEEP}s 后重试 (${attempt}/${GIT_PULL_RETRIES})..."
            sleep "$GIT_PULL_SLEEP"
            attempt=$((attempt + 1))
        done
    }

    run_with_https_pat_as_user() {
        local token="$1"
        local user="$2"
        shift 2
        local askpass result
        local sudo_cmd=("sudo" "-u" "$user")
        local extra_env=()

        if [[ "$user" == "englishlearn" ]]; then
            extra_env+=("${git_env_common[@]}")
        fi
        askpass=$(mktemp)
        cat > "$askpass" <<'EOF'
#!/usr/bin/env bash
case "$1" in
  *Username*) echo "x-access-token" ;;
  *) echo "${GITHUB_PAT}" ;;
esac
EOF
        chown "$user":"$user" "$askpass"
        chmod 700 "$askpass"
        set +e
        "${sudo_cmd[@]}" env "${extra_env[@]}" GIT_ASKPASS="$askpass" GITHUB_PAT="$token" GIT_TERMINAL_PROMPT=0 \
            "$@"
        result=$?
        set -e
        rm -f "$askpass"
        return $result
    }

    mkdir -p /root/.ssh
    chmod 700 /root/.ssh
    mkdir -p /var/lib/englishlearn
    chown englishlearn:englishlearn /var/lib/englishlearn
    chmod 755 /var/lib/englishlearn
    git_env_common=("HOME=/var/lib/englishlearn" "GIT_CONFIG_NOSYSTEM=1" "GIT_CONFIG_GLOBAL=/dev/null" "GIT_CONFIG_SYSTEM=/dev/null")
    ssh_cmd=$(build_ssh_command "${GIT_SSH_KEY:-}")

    # 如果设置了跳过标志，检查目录是否存在
    if [[ "$SKIP_GIT_CLONE" == "true" ]]; then
        info "跳过 Git 克隆步骤（SKIP_GIT_CLONE=true）"
        if [[ ! -d "$APP_DIR" ]]; then
            error "目录 $APP_DIR 不存在。请先手动克隆代码或取消 SKIP_GIT_CLONE 选项"
        fi
        info "使用现有代码目录: $APP_DIR"
        chown -R englishlearn:englishlearn "$APP_DIR"
        success "代码目录检查完成"
        return
    fi

    info "克隆代码仓库..."

    # 如果目录存在且是 git 仓库，拉取最新代码
    if [[ -d "$APP_DIR/.git" ]]; then
        warn "代码目录已存在，拉取最新代码..."
        remote_url=$(git -C "$APP_DIR" config --get remote.origin.url 2>/dev/null || true)

        if [[ "$SKIP_GIT_PULL" == "true" ]]; then
            warn "SKIP_GIT_PULL=true，跳过 git 拉取"
            chown -R englishlearn:englishlearn "$APP_DIR"
            success "代码目录检查完成"
            return
        fi

        if [[ -n "$(git -C "$APP_DIR" status --porcelain 2>/dev/null)" && "$ALLOW_DIRTY_PULL" != "true" ]]; then
            warn "检测到本地改动，默认不执行 git pull（如需强制请设置 ALLOW_DIRTY_PULL=true）"
            chown -R englishlearn:englishlearn "$APP_DIR"
            success "代码目录检查完成"
            return
        fi

        if [[ "$remote_url" == git@* || "$remote_url" == ssh://* ]]; then
            if ! check_repo_access_ssh; then
                warn "SSH 不可用，切换为 HTTPS 拉取（仓库已公开）"
                git -C "$APP_DIR" remote set-url origin "$repo_https"
                remote_url="$repo_https"
            fi
        fi

        if [[ "$remote_url" == git@* || "$remote_url" == ssh://* ]]; then
            if ! git_pull_with_retries sudo -u englishlearn env "${git_env_common[@]}" GIT_SSH_COMMAND="$ssh_cmd" \
                git -C "$APP_DIR" -c "safe.directory=$APP_DIR" pull; then
                if [[ "$ALLOW_GIT_PULL_FAILURE" == "true" ]]; then
                    warn "SSH 拉取失败，继续安装（ALLOW_GIT_PULL_FAILURE=true）"
                else
                    error "SSH 拉取失败，请检查网络或 SSH Key"
                fi
            fi
        else
            if ! git_pull_with_retries sudo -u englishlearn env "${git_env_common[@]}" \
                git -C "$APP_DIR" -c "safe.directory=$APP_DIR" pull; then
                if [[ -n "$GITHUB_PAT" ]]; then
                    if ! git_pull_with_retries run_with_https_pat_as_user "$GITHUB_PAT" englishlearn \
                        git -C "$APP_DIR" -c "safe.directory=$APP_DIR" pull; then
                        if [[ "$GIT_CLONE_METHOD" == "auto" && check_repo_access_ssh ]]; then
                            warn "HTTPS 拉取失败，尝试切换为 SSH..."
                            git -C "$APP_DIR" remote set-url origin "$repo_ssh"
                            if ! git_pull_with_retries sudo -u englishlearn env "${git_env_common[@]}" GIT_SSH_COMMAND="$ssh_cmd" \
                                git -C "$APP_DIR" -c "safe.directory=$APP_DIR" pull; then
                                if [[ "$ALLOW_GIT_PULL_FAILURE" == "true" ]]; then
                                    warn "git 拉取失败，继续安装（ALLOW_GIT_PULL_FAILURE=true）"
                                else
                                    error "git 拉取失败，请检查网络"
                                fi
                            fi
                        else
                            if [[ "$ALLOW_GIT_PULL_FAILURE" == "true" ]]; then
                                warn "HTTPS 拉取失败，继续安装（ALLOW_GIT_PULL_FAILURE=true）"
                            else
                                error "HTTPS 拉取失败。如为私有仓库请设置 GITHUB_PAT"
                            fi
                        fi
                    fi
                else
                    if [[ "$GIT_CLONE_METHOD" == "auto" && check_repo_access_ssh ]]; then
                        warn "HTTPS 拉取失败，尝试切换为 SSH..."
                        git -C "$APP_DIR" remote set-url origin "$repo_ssh"
                        if ! git_pull_with_retries sudo -u englishlearn env "${git_env_common[@]}" GIT_SSH_COMMAND="$ssh_cmd" \
                            git -C "$APP_DIR" -c "safe.directory=$APP_DIR" pull; then
                            if [[ "$ALLOW_GIT_PULL_FAILURE" == "true" ]]; then
                                warn "git 拉取失败，继续安装（ALLOW_GIT_PULL_FAILURE=true）"
                            else
                                error "git 拉取失败，请检查网络"
                            fi
                        fi
                    else
                        if [[ "$ALLOW_GIT_PULL_FAILURE" == "true" ]]; then
                            warn "HTTPS 拉取失败，继续安装（ALLOW_GIT_PULL_FAILURE=true）"
                        else
                            error "HTTPS 拉取失败。如为私有仓库请设置 GITHUB_PAT"
                        fi
                    fi
                fi
            fi
        fi

        chown -R englishlearn:englishlearn "$APP_DIR"
        success "代码更新完成"
        return
    fi

    # 如果目录存在但不是 git 仓库，询问是否清除
    if [[ -d "$APP_DIR" ]] && [[ ! -d "$APP_DIR/.git" ]]; then
        warn "目录 $APP_DIR 已存在但不是 Git 仓库"
        echo -n "是否清除该目录并重新克隆？[y/N] "
        read -r response
        if [[ "$response" =~ ^[Yy]$ ]]; then
            info "备份现有目录到 ${APP_DIR}.bak.$(date +%Y%m%d_%H%M%S)"
            mv "$APP_DIR" "${APP_DIR}.bak.$(date +%Y%m%d_%H%M%S)"
        else
            error "目录已存在，安装中止。请手动处理 $APP_DIR 目录"
        fi
    fi

    case "$GIT_CLONE_METHOD" in
        https|auto)
            info "从 GitHub 克隆代码（HTTPS，仓库已公开）..."
            if git clone "$repo_https" "$APP_DIR"; then
                success "使用 HTTPS 克隆成功"
            else
                if [[ "$GIT_CLONE_METHOD" == "auto" && -n "${GIT_SSH_KEY:-}" && check_repo_access_ssh ]]; then
                    warn "HTTPS 克隆失败，尝试使用 SSH..."
                    GIT_SSH_COMMAND="$ssh_cmd" git clone "$repo_ssh" "$APP_DIR"
                    success "使用 SSH 克隆成功"
                else
                    error "HTTPS 克隆失败。如为私有仓库请设置 GITHUB_PAT 或改用 SSH"
                fi
            fi
            ;;
        ssh)
            info "从 GitHub 克隆代码（使用 SSH，GIT_CLONE_METHOD=ssh）..."
            if ! check_repo_access_ssh; then
                error "SSH 不可用，请配置 SSH Key 或使用 HTTPS"
            fi
            if GIT_SSH_COMMAND="$ssh_cmd" git clone "$repo_ssh" "$APP_DIR"; then
                success "使用 SSH 克隆成功"
            else
                error "SSH 克隆失败，请检查 SSH Key 或改用 HTTPS"
            fi
            ;;
        *)
            error "未知的 GIT_CLONE_METHOD=$GIT_CLONE_METHOD（支持 auto|ssh|https）"
            ;;
    esac

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

    # 确保数据目录存在且权限正确
    if [[ ! -d "$DATA_DIR" ]]; then
        mkdir -p "$DATA_DIR"
        chown englishlearn:englishlearn "$DATA_DIR"
        chmod 755 "$DATA_DIR"
    fi

    if [[ -f "$DB_PATH" ]]; then
        warn "数据库已存在,跳过初始化"

        # 确保数据库权限正确
        chown englishlearn:englishlearn "$DB_PATH"
        chmod 644 "$DB_PATH"

        info "运行数据库迁移..."
        cd "$APP_DIR/backend"
        if ! sudo -u englishlearn EL_DB_PATH="$DB_PATH" DATABASE_URL="sqlite:///${DB_PATH}" \
            "$APP_DIR/venv/bin/python" migration_manager.py migrate; then
            warn "数据库迁移失败，但继续安装"
        fi
    else
        cd "$APP_DIR/backend"

        # 检查是否有旧数据库在 backend 目录
        if [[ -f "$APP_DIR/backend/el.db" ]]; then
            warn "发现旧数据库文件 $APP_DIR/backend/el.db，移动到数据目录..."
            mv "$APP_DIR/backend/el.db" "$DB_PATH"
            chown englishlearn:englishlearn "$DB_PATH"
            chmod 644 "$DB_PATH"
        else
            # 创建新数据库
            info "创建新数据库..."
            if ! sudo -u englishlearn EL_DB_PATH="$DB_PATH" "$APP_DIR/venv/bin/python" - <<'PY'
import os
import sys
import sqlite3
from pathlib import Path

db_path = os.environ.get("EL_DB_PATH")
if not db_path:
    print("ERROR: EL_DB_PATH not set", file=sys.stderr)
    sys.exit(1)

schema_path = Path(__file__).parent / "backend" / "schema.sql" if "__file__" in dir() else Path("schema.sql")
if not schema_path.exists():
    schema_path = Path(os.getcwd()) / "schema.sql"

if not schema_path.exists():
    print(f"ERROR: Schema file not found: {schema_path}", file=sys.stderr)
    sys.exit(1)

print(f"Creating database at: {db_path}")
print(f"Using schema: {schema_path}")

with open(schema_path, 'r', encoding='utf-8') as f:
    schema_sql = f.read()

conn = sqlite3.connect(db_path)
try:
    conn.executescript(schema_sql)
    conn.commit()
    print("Database created successfully")
except Exception as e:
    print(f"ERROR: {e}", file=sys.stderr)
    sys.exit(1)
finally:
    conn.close()
PY
            then
                error "数据库创建失败"
            fi
        fi

        # 确保权限正确
        if [[ -f "$DB_PATH" ]]; then
            chown englishlearn:englishlearn "$DB_PATH"
            chmod 644 "$DB_PATH"
            success "数据库初始化完成"
        else
            error "数据库文件创建后不存在: $DB_PATH"
        fi

        info "运行数据库迁移..."
        if ! sudo -u englishlearn EL_DB_PATH="$DB_PATH" DATABASE_URL="sqlite:///${DB_PATH}" \
            "$APP_DIR/venv/bin/python" migration_manager.py migrate; then
            warn "数据库迁移失败，但继续安装"
        fi
    fi

    # 最终验证
    if [[ ! -f "$DB_PATH" ]]; then
        error "数据库文件不存在: $DB_PATH"
    fi

    if ! sudo -u englishlearn test -r "$DB_PATH"; then
        error "englishlearn 用户无法读取数据库: $DB_PATH"
    fi

    if ! sudo -u englishlearn test -w "$DB_PATH"; then
        warn "englishlearn 用户无法写入数据库，尝试修复权限..."
        chown englishlearn:englishlearn "$DB_PATH"
        chmod 644 "$DB_PATH"
        if ! sudo -u englishlearn test -w "$DB_PATH"; then
            error "无法修复数据库写入权限: $DB_PATH"
        fi
    fi

    success "数据库权限验证通过"
}

# 配置环境变量
setup_env() {
    info "配置环境变量..."

    # 若环境文件已存在，尽量复用关键配置，避免重装导致密码/密钥失效
    local existing_admin_user=""
    local existing_admin_pass=""
    local existing_secret_key=""
    if [[ -f "$ENV_FILE" ]]; then
        # shellcheck disable=SC1090
        set +u
        source "$ENV_FILE"
        set -u
        existing_admin_user="${EL_ADMIN_USER:-}"
        existing_admin_pass="${EL_ADMIN_PASS:-}"
        existing_secret_key="${SECRET_KEY:-}"
    fi

    if [[ -n "$existing_admin_user" ]]; then
        FINAL_ADMIN_USER="$existing_admin_user"
    fi
    if [[ -n "$existing_admin_pass" ]]; then
        FINAL_ADMIN_PASSWORD="$existing_admin_pass"
        ADMIN_PASSWORD_SOURCE="existing_env"
    fi

    # 生成或复用密钥
    if [[ -n "$existing_secret_key" ]]; then
        SECRET_KEY="$existing_secret_key"
    else
        SECRET_KEY=$(openssl rand -base64 32)
    fi

    # 保留已有的 API 配置
    local existing_openai_key=""
    local existing_ark_key=""
    local existing_openai_base_url=""
    local existing_openai_model=""
    local existing_baidu_api_key=""
    local existing_baidu_secret_key=""
    local existing_mark_provider=""

    if [[ -f "$ENV_FILE" ]]; then
        existing_openai_key=$(grep -E "^OPENAI_API_KEY=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2- || true)
        existing_ark_key=$(grep -E "^ARK_API_KEY=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2- || true)
        existing_openai_base_url=$(grep -E "^EL_OPENAI_BASE_URL=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2- || true)
        existing_openai_model=$(grep -E "^EL_OPENAI_VISION_MODEL=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2- || true)
        existing_baidu_api_key=$(grep -E "^BAIDU_OCR_API_KEY=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2- || true)
        existing_baidu_secret_key=$(grep -E "^BAIDU_OCR_SECRET_KEY=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2- || true)
        existing_mark_provider=$(grep -E "^EL_MARK_GRADING_PROVIDER=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2- || true)
    fi

    cat > "$ENV_FILE" <<EOF
# EnglishLearn 配置文件
# 生成时间: $(date)

# 应用配置
APP_NAME=EnglishLearn
APP_VERSION=1.0.0
DEBUG=false

# 数据库配置
DATABASE_URL=sqlite:///${DB_PATH}
EL_DB_PATH=${DB_PATH}

# 媒体文件目录
MEDIA_DIR=${MEDIA_DIR}
EL_MEDIA_DIR=${MEDIA_DIR}

# 服务器配置
HOST=0.0.0.0
PORT=${DEFAULT_PORT}

# 安全配置
SECRET_KEY=${SECRET_KEY}
ALLOWED_HOSTS=localhost,127.0.0.1

# 管理员账号 (首次安装)
EL_ADMIN_USER=${FINAL_ADMIN_USER}
EL_ADMIN_PASS=${FINAL_ADMIN_PASSWORD}

# ============================================================
# LLM/AI 批改配置 (必须配置其中一个才能使用 AI 批改功能)
# ============================================================

# 批改服务提供商: auto | openai | baidu
# - auto: 自动选择（优先 OpenAI/ARK，否则 Baidu OCR）
# - openai: 使用 OpenAI 兼容 API（包括火山引擎豆包等）
# - baidu: 使用百度 OCR
EL_MARK_GRADING_PROVIDER=${existing_mark_provider:-auto}

# --- 方式1: OpenAI 兼容 API（推荐，支持豆包/通义千问等） ---
# API 密钥（二选一）
OPENAI_API_KEY=${existing_openai_key:-}
ARK_API_KEY=${existing_ark_key:-}

# API 地址（根据服务商设置）
# - OpenAI 官方: https://api.openai.com/v1
# - 火山引擎豆包: https://ark.cn-beijing.volces.com/api/v3
# - 阿里通义: https://dashscope.aliyuncs.com/compatible-mode/v1
EL_OPENAI_BASE_URL=${existing_openai_base_url:-}

# 模型名称
# - OpenAI: gpt-4o-mini, gpt-4o
# - 豆包: doubao-seed-1-6-251015
# - 通义: qwen-vl-max
EL_OPENAI_VISION_MODEL=${existing_openai_model:-gpt-4o-mini}

# --- 方式2: 百度 OCR ---
BAIDU_OCR_API_KEY=${existing_baidu_api_key:-}
BAIDU_OCR_SECRET_KEY=${existing_baidu_secret_key:-}

# ============================================================
# AI 参数配置（通常无需修改）
# ============================================================
EL_AI_MAX_TOKENS=6000
EL_AI_MAX_TOKENS_RETRY=12000
EL_AI_TIMEOUT_SECONDS=180
EL_AI_HTTP_TIMEOUT_SECONDS=270
EL_OCR_TIMEOUT_SECONDS=30

# 图片处理
EL_AI_MAX_LONG_SIDE=3508
EL_AI_JPEG_QUALITY=85

# 匹配阈值
EL_MATCH_SIM_THRESHOLD=0.88
EL_OCR_MATCH_THRESHOLD=0.6

# ============================================================
# 备份配置
# ============================================================
BACKUP_DIR=${BACKUP_DIR}
BACKUP_RETENTION_DAYS=30

# 自动清理（北京时间）
EL_CLEANUP_TIME=03:00
EL_CLEANUP_INTERVAL_DAYS=1
EL_CLEANUP_UNDOWNLOADED_DAYS=14

# ============================================================
# 日志配置
# ============================================================
LOG_LEVEL=INFO
LOG_FILE=/var/log/englishlearn/app.log

# 调试选项（生产环境建议关闭）
EL_AI_DEBUG_BBOX=0
EL_AI_DEBUG_SAVE=0
EL_DEBUG_BBOX_PROCESSING=0
SAVE_CROP_IMAGES=0
EOF

    chmod 600 "$ENV_FILE"

    # 创建日志目录
    mkdir -p /var/log/englishlearn
    chown -R englishlearn:englishlearn /var/log/englishlearn

    success "环境变量配置完成"
}

# 确保管理员账号存在
ensure_admin_account() {
    info "初始化管理员账号..."

    if [[ ! -f "$DB_PATH" ]]; then
        error "数据库不存在: $DB_PATH"
    fi

    if [[ -z "${FINAL_ADMIN_PASSWORD:-}" ]]; then
        error "管理员密码为空，无法初始化账号"
    fi

    local count_before=""
    local admin_exists=""
    if command -v sqlite3 >/dev/null 2>&1; then
        count_before=$(sqlite3 "$DB_PATH" "SELECT COUNT(1) FROM accounts;" 2>/dev/null || true)
        admin_exists=$(sqlite3 "$DB_PATH" "SELECT COUNT(1) FROM accounts WHERE username='${FINAL_ADMIN_USER}';" 2>/dev/null || true)
    fi

    cd "$APP_DIR"

    # 如果数据库已有账号但管理员不存在或密码来自环境文件，需要特殊处理
    if [[ "$count_before" -gt 0 ]]; then
        if [[ "$admin_exists" == "0" ]]; then
            # 管理员用户不存在，创建新的
            info "数据库已有账号但管理员用户 ${FINAL_ADMIN_USER} 不存在，创建新管理员..."
            if ! sudo -u englishlearn \
                EL_DB_PATH="$DB_PATH" \
                "$APP_DIR/venv/bin/python" - "$FINAL_ADMIN_USER" "$FINAL_ADMIN_PASSWORD" <<'PY'
import os, sys
sys.path.insert(0, os.getcwd())
from backend.app.auth import create_account
username = sys.argv[1]
password = sys.argv[2]
try:
    create_account(username, password, is_super_admin=True)
    print(f"Created admin account: {username}")
except Exception as e:
    print(f"Warning: {e}", file=sys.stderr)
    sys.exit(0)  # 不作为错误，可能用户名已存在
PY
            then
                warn "创建管理员账号时出现警告（可能已存在）"
            fi
            ADMIN_PASSWORD_SOURCE="new_admin_created"
        else
            # 管理员用户存在，保留原密码
            info "管理员账号 ${FINAL_ADMIN_USER} 已存在，保留原有密码"
            ADMIN_PASSWORD_SOURCE="existing_db"
        fi
    else
        # 数据库为空，使用标准流程创建
        if ! sudo -u englishlearn \
            EL_DB_PATH="$DB_PATH" \
            EL_ADMIN_USER="$FINAL_ADMIN_USER" \
            EL_ADMIN_PASS="$FINAL_ADMIN_PASSWORD" \
            "$APP_DIR/venv/bin/python" - <<'PY'
import os, sys
sys.path.insert(0, os.getcwd())
from backend.app.auth import ensure_super_admin
ensure_super_admin()
PY
        then
            error "初始化管理员账号失败"
        fi
    fi

    success "管理员账号初始化完成"
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
# 允许写入数据目录、备份目录、日志目录和应用目录（临时文件等）
ReadWritePaths=$DATA_DIR $BACKUP_DIR /var/log/englishlearn $APP_DIR/backend

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
    local nginx_bin=""

    if command -v nginx >/dev/null 2>&1; then
        nginx_bin="$(command -v nginx)"
    elif [[ -x /usr/sbin/nginx ]]; then
        nginx_bin="/usr/sbin/nginx"
    fi

    if [[ -z "$nginx_bin" ]]; then
        warn "未检测到 Nginx，尝试安装..."
        case "$OS" in
            ubuntu|debian)
                apt-get update
                apt-get install -y nginx
                ;;
            centos|rhel|fedora)
                yum install -y nginx
                ;;
            *)
                error "未检测到 Nginx 且系统不支持自动安装，请手动安装 nginx"
                ;;
        esac

        if command -v nginx >/dev/null 2>&1; then
            nginx_bin="$(command -v nginx)"
        elif [[ -x /usr/sbin/nginx ]]; then
            nginx_bin="/usr/sbin/nginx"
        fi
    fi

    if [[ -z "$nginx_bin" ]]; then
        error "Nginx 安装失败或未在 PATH 中，无法继续配置"
    fi

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
    "$nginx_bin" -t

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

# 安装后自检
post_install_check() {
    info "安装后自检..."

    local check_failed=0

    # 1. 检查环境文件
    if [[ ! -f "$ENV_FILE" ]]; then
        error "环境文件不存在: $ENV_FILE"
    fi
    info "✓ 环境文件存在"

    # 读取环境配置
    local env_db_path=""
    local env_media_dir=""
    local env_port=""
    set +u
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set -u
    env_db_path="${EL_DB_PATH:-}"
    env_media_dir="${EL_MEDIA_DIR:-}"
    env_port="${PORT:-}"

    if [[ -z "$env_db_path" && -n "${DATABASE_URL:-}" ]]; then
        if [[ "${DATABASE_URL}" == sqlite:///* ]]; then
            env_db_path="${DATABASE_URL#sqlite:///}"
        else
            env_db_path="${DATABASE_URL}"
        fi
    fi
    if [[ -z "$env_db_path" ]]; then
        env_db_path="$DB_PATH"
    fi

    if [[ -z "$env_media_dir" ]]; then
        env_media_dir="$MEDIA_DIR"
    fi

    # 2. 检查数据库文件
    if [[ ! -f "$env_db_path" ]]; then
        error "数据库文件不存在: $env_db_path"
    fi
    info "✓ 数据库文件存在"

    # 3. 检查数据库权限
    if ! sudo -u englishlearn test -r "$env_db_path"; then
        warn "数据库不可读，修复中..."
        chown englishlearn:englishlearn "$env_db_path"
        chmod 644 "$env_db_path"
    fi
    if ! sudo -u englishlearn test -w "$env_db_path"; then
        warn "数据库不可写，修复中..."
        chown englishlearn:englishlearn "$env_db_path"
        chmod 644 "$env_db_path"
    fi
    info "✓ 数据库权限正确"

    # 4. 检查管理员账号
    if ! command -v sqlite3 >/dev/null 2>&1; then
        warn "sqlite3 未安装，跳过账号检查"
    else
        local acc_count=""
        acc_count=$(sqlite3 "$env_db_path" "SELECT COUNT(1) FROM accounts;" 2>/dev/null || true)
        if [[ -z "$acc_count" || "$acc_count" -lt 1 ]]; then
            error "管理员账号未初始化（accounts 表为空）"
        fi

        local admin_count=""
        admin_count=$(sqlite3 "$env_db_path" "SELECT COUNT(1) FROM accounts WHERE is_super_admin=1 AND is_active=1;" 2>/dev/null || true)
        if [[ -z "$admin_count" || "$admin_count" -lt 1 ]]; then
            warn "没有活跃的超级管理员账号！"
            check_failed=1
        else
            info "✓ 管理员账号存在 ($admin_count 个)"
        fi
    fi

    # 5. 检查媒体目录
    if [[ ! -d "$env_media_dir" ]]; then
        warn "媒体目录不存在，创建中: $env_media_dir"
        mkdir -p "$env_media_dir"
        chown -R englishlearn:englishlearn "$env_media_dir"
    fi

    if ! sudo -u englishlearn test -w "$env_media_dir"; then
        warn "媒体目录不可写，修复中: $env_media_dir"
        chown -R englishlearn:englishlearn "$env_media_dir"
        chmod 755 "$env_media_dir"
    fi
    info "✓ 媒体目录权限正确"

    # 6. 检查服务状态
    if ! systemctl is-active --quiet "$SERVICE_NAME"; then
        warn "服务未运行，查看状态..."
        systemctl status "$SERVICE_NAME" --no-pager || true

        # 尝试查看日志
        warn "查看最近的日志..."
        journalctl -u "$SERVICE_NAME" -n 20 --no-pager || true

        error "服务 $SERVICE_NAME 未正常运行，请检查上面的日志"
    fi
    info "✓ 服务运行中"

    # 7. 检查 API 接口
    if command -v curl >/dev/null 2>&1; then
        local port="${env_port:-$DEFAULT_PORT}"

        # 等待服务启动
        local retry=0
        local max_retry=10
        while [[ $retry -lt $max_retry ]]; do
            local code=""
            code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 2 "http://127.0.0.1:${port}/api/auth/me" 2>/dev/null || true)
            if [[ "$code" == "401" || "$code" == "200" ]]; then
                info "✓ API 接口响应正常 (状态码: $code)"
                break
            fi
            retry=$((retry + 1))
            if [[ $retry -lt $max_retry ]]; then
                info "等待服务启动... ($retry/$max_retry)"
                sleep 2
            fi
        done

        if [[ $retry -ge $max_retry ]]; then
            warn "API 接口响应异常，最后状态码: ${code:-N/A}"
            check_failed=1
        fi
    else
        warn "curl 未安装，跳过 API 检查"
    fi

    # 8. 检查 Nginx
    if systemctl is-active --quiet nginx; then
        info "✓ Nginx 运行中"
    else
        warn "Nginx 未运行"
        check_failed=1
    fi

    if [[ $check_failed -eq 1 ]]; then
        warn "部分检查未通过，但安装已完成。请检查上述警告信息。"
    else
        success "所有自检通过！"
    fi
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
    warn "【重要】配置 AI 批改功能:"
    echo "  编辑 ${ENV_FILE} 设置以下配置之一："
    echo ""
    echo "  方式1 - OpenAI/豆包/通义（推荐）:"
    echo "    OPENAI_API_KEY=sk-xxx 或 ARK_API_KEY=xxx"
    echo "    EL_OPENAI_BASE_URL=https://ark.cn-beijing.volces.com/api/v3"
    echo "    EL_OPENAI_VISION_MODEL=doubao-seed-1-6-251015"
    echo ""
    echo "  方式2 - 百度 OCR:"
    echo "    BAIDU_OCR_API_KEY=xxx"
    echo "    BAIDU_OCR_SECRET_KEY=xxx"
    echo ""
    echo "  配置后重启服务: systemctl restart ${SERVICE_NAME}"
    echo ""
    info "数据位置:"
    echo "  应用目录: ${APP_DIR}"
    echo "  数据目录: ${DATA_DIR}"
    echo "  数据库: ${DB_PATH}"
    echo "  媒体文件: ${MEDIA_DIR}"
    echo "  备份目录: ${BACKUP_DIR}"
    echo ""

    case "$ADMIN_PASSWORD_SOURCE" in
        existing_db)
            warn "╔═══════════════════════════════════════════════════════╗"
            warn "║  注意：检测到数据库中已存在管理员账号                 ║"
            warn "║  原有密码已保留，以下显示的密码可能不正确             ║"
            warn "╚═══════════════════════════════════════════════════════╝"
            echo ""
            info "管理员账号: ${FINAL_ADMIN_USER}"
            warn "管理员密码: [使用原有密码]"
            echo ""
            info "如忘记密码，可使用以下命令重置："
            echo "  cd $APP_DIR && sudo -u englishlearn \\"
            echo "    EL_DB_PATH=$DB_PATH \\"
            echo "    venv/bin/python -c \\"
            echo "    \"from backend.app.auth import set_account_password; set_account_password(1, 'NewPassword123')\""
            ;;
        existing_env)
            warn "提示：从已有环境文件中读取了管理员配置"
            echo ""
            success "管理员账号: ${FINAL_ADMIN_USER}"
            success "管理员密码: ${FINAL_ADMIN_PASSWORD}"
            warn "【请立即登录并修改管理员密码】"
            ;;
        new_admin_created)
            success "管理员账号: ${FINAL_ADMIN_USER}"
            success "管理员密码: ${FINAL_ADMIN_PASSWORD}"
            warn "【请立即登录并修改管理员密码】"
            ;;
        *)
            warn "【请立即登录并修改管理员密码】"
            echo ""
            success "管理员账号: ${FINAL_ADMIN_USER}"
            success "管理员密码: ${FINAL_ADMIN_PASSWORD}"
            ;;
    esac
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
    ensure_admin_account
    setup_systemd
    setup_nginx
    setup_firewall
    start_services
    post_install_check
    show_info
}

# 执行安装
main

exit 0
