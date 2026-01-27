#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Config (override via env) ---
APP_DIR="${APP_DIR:-/opt/EnglishLearn}"
SERVICE_NAME="${SERVICE_NAME:-englishlearn}"
DATA_DIR="${DATA_DIR:-$APP_DIR/data}"
DB_PATH="${DB_PATH:-$DATA_DIR/el.db}"
MEDIA_DIR="${MEDIA_DIR:-$DATA_DIR/media}"
ENV_FILE="${ENV_FILE:-/etc/englishlearn.env}"
BACKUP_DIR="${BACKUP_DIR:-/opt/EnglishLearn_Backups}"
PYTHON_BIN="${PYTHON_BIN:-$APP_DIR/venv/bin/python}"
BACKUP_CONFIG_FILE="${DATA_DIR}/backup_config.json"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

if [[ "$(id -u)" -eq 0 ]]; then
  SUDO=""
else
  SUDO="sudo"
fi

log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[OK]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

usage() {
  cat <<EOF
Usage: $0 {command} [options]

服务管理:
  start       启动服务
  stop        停止服务
  restart     重启服务
  status      查看服务状态
  logs        查看服务日志 (最近 200 行)
  logs-f      实时跟踪日志

升级与更新:
  check       检查是否有新版本可用
  update      快速更新 (git pull + pip + 重启)
  upgrade     完整升级 (备份 + 更新 + 迁移 + 环境合并)

备份与恢复:
  backup      创建备份 (数据库 + 媒体文件)
  restore     恢复备份 (指定文件或 "latest")
  list        列出所有备份

定时任务:
  timer-status  查看自动备份定时器状态
  timer-enable  启用自动备份定时器
  timer-disable 禁用自动备份定时器
  timer-install 安装/更新 systemd timer 文件
  timer-set     设置备份时间 (如: timer-set 03:30)

账号管理:
  reset-password  重置管理员密码 (如: reset-password admin)

其他:
  help        显示此帮助信息

环境变量:
  APP_DIR=/opt/EnglishLearn
  SERVICE_NAME=englishlearn
  BACKUP_DIR=/opt/EnglishLearn_Backups
  SKIP_PIP=1           跳过 pip install
  SKIP_MIGRATION=1     跳过数据库迁移
  SKIP_BACKUP=1        升级时跳过自动备份
  BACKUP_NO_STOP=1     备份时不停止服务
  FORCE=1              恢复时跳过确认

示例:
  $0 upgrade                   # 完整升级流程
  $0 check                     # 检查新版本
  $0 backup                    # 手动创建备份
  $0 restore latest            # 恢复最新备份
  $0 timer-set 03:30           # 设置备份时间为凌晨 3:30
  $0 reset-password admin      # 重置 admin 账号密码
  SKIP_BACKUP=1 $0 upgrade     # 升级但跳过备份
EOF
}


ensure_backup_dir() {
  mkdir -p "$BACKUP_DIR"
}

ensure_git_safe_directory() {
  # 配置 git safe.directory 避免 dubious ownership 错误
  if [[ -d "$APP_DIR/.git" ]]; then
    git config --global --add safe.directory "$APP_DIR" 2>/dev/null || true
  fi
}

is_running() {
  $SUDO systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null
}

start_service() {
  log_info "启动服务 $SERVICE_NAME..."
  $SUDO systemctl start "$SERVICE_NAME"
  $SUDO systemctl status "$SERVICE_NAME" --no-pager
}

stop_service() {
  log_info "停止服务 $SERVICE_NAME..."
  $SUDO systemctl stop "$SERVICE_NAME"
}

restart_service() {
  log_info "重启服务 $SERVICE_NAME..."
  $SUDO systemctl restart "$SERVICE_NAME"
  $SUDO systemctl status "$SERVICE_NAME" --no-pager
}

status_service() {
  $SUDO systemctl status "$SERVICE_NAME" --no-pager
}

logs_service() {
  $SUDO journalctl -u "$SERVICE_NAME" --no-pager -n 200
}

logs_follow() {
  $SUDO journalctl -u "$SERVICE_NAME" -f
}

# 检查新版本
check_update() {
  ensure_git_safe_directory

  if [[ ! -d "$APP_DIR/.git" ]]; then
    log_error "不是 Git 仓库: $APP_DIR"
    return 1
  fi

  log_info "检查远程更新..."

  cd "$APP_DIR"
  local current_branch
  current_branch=$(git branch --show-current)
  local current_commit
  current_commit=$(git rev-parse --short HEAD)

  # Fetch 远程更新
  if ! git fetch origin "$current_branch" 2>/dev/null; then
    log_error "无法连接远程仓库，请检查网络"
    return 1
  fi

  local commits_behind
  commits_behind=$(git rev-list --count "HEAD..origin/$current_branch")
  local remote_commit
  remote_commit=$(git rev-parse --short "origin/$current_branch")

  echo ""
  echo "当前分支: $current_branch"
  echo "本地版本: $current_commit"
  echo "远程版本: $remote_commit"
  echo ""

  if [[ "$commits_behind" -gt 0 ]]; then
    log_warn "发现 $commits_behind 个新提交可更新"
    echo ""
    echo "最近更新内容:"
    git log --oneline "HEAD..origin/$current_branch" | head -10
    echo ""
    echo "运行 '$0 upgrade' 进行完整升级"
    echo "运行 '$0 update' 进行快速更新"
  else
    log_success "已是最新版本"
  fi
}

# 合并环境配置
merge_env_config() {
  local example_file="$APP_DIR/.env.example"
  local user_env_file="$ENV_FILE"

  if [[ ! -f "$example_file" ]]; then
    return 0
  fi

  if [[ ! -f "$user_env_file" ]]; then
    log_warn "未找到用户配置文件: $user_env_file"
    return 0
  fi

  log_info "检查环境配置..."

  # 使用 Python 进行配置合并
  if [[ -x "$PYTHON_BIN" ]]; then
    "$PYTHON_BIN" - "$example_file" "$user_env_file" <<'PYTHON_SCRIPT'
import sys

def parse_env(filepath):
    result = {}
    try:
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, _, value = line.partition('=')
                    result[key.strip()] = value.strip()
    except:
        pass
    return result

example_file = sys.argv[1]
user_file = sys.argv[2]

example_config = parse_env(example_file)
user_config = parse_env(user_file)

missing = [k for k in example_config if k not in user_config]

if missing:
    print(f"发现 {len(missing)} 个新配置项需要添加")

    # 读取 example 文件保留注释
    with open(example_file, 'r') as f:
        example_lines = f.readlines()

    lines_to_add = []
    current_comments = []
    added = set()

    for line in example_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            current_comments.append(line)
        elif '=' in stripped:
            key = stripped.partition('=')[0].strip()
            if key in missing and key not in added:
                if current_comments:
                    lines_to_add.extend(current_comments)
                lines_to_add.append(line)
                added.add(key)
            current_comments = []
        else:
            current_comments = []

    if lines_to_add:
        import datetime
        with open(user_file, 'a') as f:
            f.write(f"\n\n# ============================================================\n")
            f.write(f"# 以下配置由 deploy.sh 升级自动添加 ({datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')})\n")
            f.write(f"# ============================================================\n")
            f.writelines(lines_to_add)

        for key in added:
            print(f"  + {key}")
else:
    print("环境配置已是最新")
PYTHON_SCRIPT
  else
    log_warn "Python 不可用，跳过配置合并"
  fi
}

# 快速更新
update_code() {
  ensure_git_safe_directory

  if [[ ! -d "$APP_DIR/.git" ]]; then
    log_error "更新失败: $APP_DIR 不是 Git 仓库"
    return 1
  fi

  log_info "停止服务..."
  stop_service || true

  log_info "拉取最新代码..."
  cd "$APP_DIR"
  git pull --rebase origin "$(git branch --show-current)"

  if [[ "${SKIP_PIP:-}" != "1" ]]; then
    log_info "安装 Python 依赖..."
    "$PYTHON_BIN" -m pip install -q -r "$APP_DIR/backend/requirements.txt"
  else
    log_info "跳过 pip install (SKIP_PIP=1)"
  fi

  log_info "启动服务..."
  start_service

  log_success "更新完成"
}

# 完整升级
upgrade_system() {
  ensure_git_safe_directory

  if [[ ! -d "$APP_DIR/.git" ]]; then
    log_error "升级失败: $APP_DIR 不是 Git 仓库"
    return 1
  fi

  echo ""
  echo "=========================================="
  echo "  EnglishLearn 系统升级"
  echo "=========================================="
  echo ""

  # 步骤 1: 检查更新
  log_info "步骤 1/6: 检查远程更新..."
  cd "$APP_DIR"
  local current_branch
  current_branch=$(git branch --show-current)

  if ! git fetch origin "$current_branch" 2>/dev/null; then
    log_error "无法连接远程仓库"
    return 1
  fi

  local commits_behind
  commits_behind=$(git rev-list --count "HEAD..origin/$current_branch")

  if [[ "$commits_behind" -eq 0 ]]; then
    log_success "已是最新版本，无需升级"
    return 0
  fi

  log_info "发现 $commits_behind 个新提交"

  # 步骤 2: 升级前备份
  if [[ "${SKIP_BACKUP:-}" != "1" ]]; then
    log_info "步骤 2/6: 创建升级前备份..."
    backup_data "upgrade"
  else
    log_info "步骤 2/6: 跳过备份 (SKIP_BACKUP=1)"
  fi

  # 步骤 3: 停止服务
  log_info "步骤 3/6: 停止服务..."
  stop_service || true

  # 步骤 4: 拉取代码
  log_info "步骤 4/6: 拉取最新代码..."
  git pull --rebase origin "$current_branch"

  # 步骤 5: 安装依赖 + 迁移
  if [[ "${SKIP_PIP:-}" != "1" ]]; then
    log_info "步骤 5/6: 安装 Python 依赖..."
    "$PYTHON_BIN" -m pip install -q -r "$APP_DIR/backend/requirements.txt"
  fi

  if [[ "${SKIP_MIGRATION:-}" != "1" ]]; then
    log_info "执行数据库迁移..."
    if [[ -f "$APP_DIR/backend/migration_manager.py" ]]; then
      "$PYTHON_BIN" "$APP_DIR/backend/migration_manager.py" migrate || log_warn "迁移失败，继续..."
    fi
  fi

  # 步骤 6: 合并环境配置
  log_info "步骤 6/6: 检查环境配置..."
  merge_env_config

  # 检查并更新 systemd timer
  if [[ -f "$APP_DIR/scripts/englishlearn-backup.timer" ]]; then
    local timer_installed=false
    if [[ -f "/etc/systemd/system/englishlearn-backup.timer" ]]; then
      timer_installed=true
    fi
    if [[ "$timer_installed" == "false" ]]; then
      log_info "发现新的自动备份定时器，安装中..."
      install_timer || true
    fi
  fi

  # 重载 nginx（如果存在）
  if [[ -x /usr/sbin/nginx ]]; then
    $SUDO /usr/sbin/nginx -t 2>/dev/null && $SUDO systemctl reload nginx 2>/dev/null || true
  fi

  # 启动服务
  log_info "启动服务..."
  start_service

  echo ""
  log_success "=========================================="
  log_success "  升级完成!"
  log_success "=========================================="
  echo ""

  # 显示新版本信息
  echo "当前版本: $(git rev-parse --short HEAD)"
  echo ""
}

# 创建备份
backup_data() {
  local backup_type="${1:-manual}"
  ensure_backup_dir

  local ts
  ts="$(date +"%Y%m%d_%H%M%S")"

  local backup_name
  case "$backup_type" in
    upgrade) backup_name="EnglishLearn_升级前备份_${ts}.tar.gz" ;;
    auto)    backup_name="EnglishLearn_自动备份_${ts}.tar.gz" ;;
    *)       backup_name="EnglishLearn_手动备份_${ts}.tar.gz" ;;
  esac

  local backup_file="$BACKUP_DIR/$backup_name"

  local was_running="0"
  if is_running; then
    was_running="1"
  fi

  if [[ "${BACKUP_NO_STOP:-}" != "1" ]] && [[ "$was_running" == "1" ]]; then
    log_info "暂停服务以确保数据一致性..."
    stop_service
  fi

  log_info "创建备份: $backup_name"

  # 创建临时目录存放备份信息
  local temp_dir
  temp_dir=$(mktemp -d)
  trap "rm -rf $temp_dir" EXIT

  # 创建备份信息文件
  cat > "$temp_dir/backup_info.json" <<EOF
{
    "backup_time": "$(date -Iseconds)",
    "description": "${backup_type} 备份 - $ts",
    "version": "1.0",
    "db_included": true,
    "media_included": true,
    "backup_type": "$backup_type",
    "restore_note": "使用 deploy.sh restore 恢复此备份"
}
EOF

  # 创建备份
  $SUDO tar -czf "$backup_file" \
    -C "$temp_dir" backup_info.json \
    -C "$(dirname "$DB_PATH")" "$(basename "$DB_PATH")" \
    -C "$(dirname "$MEDIA_DIR")" "$(basename "$MEDIA_DIR")" 2>/dev/null || {
      # 如果媒体目录不存在，只备份数据库
      $SUDO tar -czf "$backup_file" \
        -C "$temp_dir" backup_info.json \
        -C "$(dirname "$DB_PATH")" "$(basename "$DB_PATH")"
    }

  if [[ "${BACKUP_NO_STOP:-}" != "1" ]] && [[ "$was_running" == "1" ]]; then
    start_service
  fi

  local size
  size=$(du -h "$backup_file" | cut -f1)
  log_success "备份完成: $backup_name ($size)"
}

# 恢复备份
restore_data() {
  ensure_backup_dir
  local target="${1:-}"

  if [[ -z "$target" ]]; then
    log_error "请指定备份文件路径或使用 'latest'"
    echo "用法: $0 restore <备份文件|latest>"
    return 1
  fi

  if [[ "$target" == "latest" ]]; then
    target="$(ls -1t "$BACKUP_DIR"/EnglishLearn_*.tar.gz 2>/dev/null | head -n 1 || true)"
    if [[ -z "$target" ]]; then
      # 兼容旧格式
      target="$(ls -1t "$BACKUP_DIR"/EL_backup_*.tar.gz 2>/dev/null | head -n 1 || true)"
    fi
  fi

  if [[ -z "$target" || ! -f "$target" ]]; then
    log_error "备份文件不存在: $target"
    return 1
  fi

  if [[ "${FORCE:-}" != "1" ]]; then
    echo ""
    log_warn "警告: 此操作将覆盖当前数据库和媒体文件!"
    echo "备份文件: $target"
    echo ""
    read -r -p "确定要继续吗? [y/N] " ans
    if [[ "${ans}" != "y" && "${ans}" != "Y" ]]; then
      echo "已取消恢复操作"
      return 0
    fi
  fi

  log_info "停止服务..."
  stop_service

  log_info "恢复数据: $(basename "$target")"
  $SUDO tar -xzf "$target" -C "$DATA_DIR"

  # 运行数据库迁移（支持从旧版本恢复）
  if [[ -f "$APP_DIR/backend/migration_manager.py" ]]; then
    log_info "检查数据库迁移..."
    "$PYTHON_BIN" "$APP_DIR/backend/migration_manager.py" migrate || log_warn "迁移失败"
  fi

  start_service
  log_success "恢复完成"
}

# 列出备份
list_backups() {
  ensure_backup_dir
  echo ""
  echo "备份目录: $BACKUP_DIR"
  echo ""

  local count
  count=$(ls -1 "$BACKUP_DIR"/EnglishLearn_*.tar.gz "$BACKUP_DIR"/EL_backup_*.tar.gz 2>/dev/null | wc -l || echo 0)

  if [[ "$count" -eq 0 ]]; then
    echo "暂无备份文件"
    return 0
  fi

  echo "共 $count 个备份文件:"
  echo ""
  ls -lht "$BACKUP_DIR"/*.tar.gz 2>/dev/null | head -20

  local total_size
  total_size=$(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1)
  echo ""
  echo "备份目录总大小: $total_size"
}

# Timer 管理
timer_status() {
  echo "自动备份定时器状态:"
  echo ""
  $SUDO systemctl status englishlearn-backup.timer --no-pager 2>/dev/null || echo "定时器未安装"
  echo ""
  echo "下次执行时间:"
  $SUDO systemctl list-timers englishlearn-backup.timer --no-pager 2>/dev/null || echo "无"
}

timer_enable() {
  log_info "启用自动备份定时器..."
  $SUDO systemctl enable englishlearn-backup.timer
  $SUDO systemctl start englishlearn-backup.timer
  log_success "定时器已启用"
  timer_status
}

timer_disable() {
  log_info "禁用自动备份定时器..."
  $SUDO systemctl stop englishlearn-backup.timer
  $SUDO systemctl disable englishlearn-backup.timer
  log_success "定时器已禁用"
}

install_timer() {
  local timer_file="$APP_DIR/scripts/englishlearn-backup.timer"
  local service_file="$APP_DIR/scripts/englishlearn-backup.service"

  if [[ ! -f "$timer_file" ]] || [[ ! -f "$service_file" ]]; then
    log_error "Timer 文件不存在: $timer_file 或 $service_file"
    return 1
  fi

  log_info "安装 systemd timer 文件..."
  $SUDO cp "$service_file" /etc/systemd/system/
  $SUDO cp "$timer_file" /etc/systemd/system/

  $SUDO systemctl daemon-reload
  $SUDO systemctl enable englishlearn-backup.timer
  $SUDO systemctl start englishlearn-backup.timer

  log_success "自动备份定时器已安装并启用"
  timer_status
}

# 设置备份时间
timer_set_time() {
  local new_time="${1:-}"

  if [[ -z "$new_time" ]]; then
    log_error "请指定备份时间，格式: HH:MM"
    echo "用法: $0 timer-set 03:30"
    return 1
  fi

  # 验证时间格式
  if ! [[ "$new_time" =~ ^([01]?[0-9]|2[0-3]):[0-5][0-9]$ ]]; then
    log_error "无效的时间格式: $new_time"
    echo "请使用 24 小时制，如: 02:00, 14:30"
    return 1
  fi

  # 检查定时器是否已安装
  if [[ ! -f "/etc/systemd/system/englishlearn-backup.timer" ]]; then
    log_error "定时器未安装，请先运行: $0 timer-install"
    return 1
  fi

  log_info "设置备份时间为 $new_time..."

  # 创建 override 目录
  local override_dir="/etc/systemd/system/englishlearn-backup.timer.d"
  $SUDO mkdir -p "$override_dir"

  # 写入 override 配置
  $SUDO tee "$override_dir/override.conf" > /dev/null <<EOF
[Timer]
# 覆盖默认备份时间
OnCalendar=
OnCalendar=*-*-* ${new_time}:00
EOF

  # 重载配置
  $SUDO systemctl daemon-reload
  $SUDO systemctl restart englishlearn-backup.timer

  log_success "备份时间已设置为每天 $new_time"
  echo ""
  echo "下次执行时间:"
  $SUDO systemctl list-timers englishlearn-backup.timer --no-pager 2>/dev/null | grep -v "^$" | head -3
}

# 重置管理员密码
reset_admin_password() {
  local username="${1:-}"

  if [[ -z "$username" ]]; then
    echo "用法: $0 reset-password <用户名>"
    echo ""
    echo "现有账号列表:"
    # 查询数据库中的账号
    if [[ -f "$DB_PATH" ]]; then
      sqlite3 "$DB_PATH" "SELECT id, username, CASE WHEN is_super_admin=1 THEN '管理员' ELSE '普通用户' END as role, CASE WHEN is_active=1 THEN '启用' ELSE '停用' END as status FROM accounts;" 2>/dev/null | \
        awk -F'|' 'BEGIN{printf "%-4s %-20s %-10s %-6s\n", "ID", "用户名", "角色", "状态"; print "----------------------------------------"} {printf "%-4s %-20s %-10s %-6s\n", $1, $2, $3, $4}'
    else
      log_warn "数据库文件不存在: $DB_PATH"
    fi
    return 1
  fi

  # 检查账号是否存在
  if [[ -f "$DB_PATH" ]]; then
    local account_exists
    account_exists=$(sqlite3 "$DB_PATH" "SELECT COUNT(1) FROM accounts WHERE username='$username';" 2>/dev/null || echo "0")
    if [[ "$account_exists" -eq 0 ]]; then
      log_error "账号不存在: $username"
      return 1
    fi
  fi

  echo ""
  log_info "重置账号密码: $username"
  echo ""

  # 读取新密码
  local password1 password2

  while true; do
    read -r -s -p "请输入新密码 (至少 8 位): " password1
    echo ""

    if [[ ${#password1} -lt 8 ]]; then
      log_error "密码太短，至少需要 8 位"
      continue
    fi

    read -r -s -p "请再次输入密码确认: " password2
    echo ""

    if [[ "$password1" != "$password2" ]]; then
      log_error "两次输入的密码不一致，请重试"
      continue
    fi

    break
  done

  # 使用 Python 重置密码
  log_info "正在重置密码..."

  if [[ -x "$PYTHON_BIN" ]]; then
    # 设置环境变量
    export EL_DB_PATH="$DB_PATH"

    "$PYTHON_BIN" - "$username" "$password1" <<'PYTHON_SCRIPT'
import sys
import os

# 添加 backend 路径
backend_path = os.path.join(os.path.dirname(os.environ.get('EL_DB_PATH', '')), '..', '..')
sys.path.insert(0, os.path.abspath(backend_path))

try:
    from backend.app.auth import set_account_password
    from backend.app.db import db, qone

    username = sys.argv[1]
    new_password = sys.argv[2]

    # 获取账号 ID
    with db() as conn:
        row = qone(conn, "SELECT id FROM accounts WHERE username = ?", (username,))
        if not row:
            print(f"ERROR: 账号不存在: {username}")
            sys.exit(1)
        account_id = row['id']

    # 重置密码
    set_account_password(account_id, new_password)
    print(f"OK: 密码已重置")
except Exception as e:
    print(f"ERROR: {e}")
    sys.exit(1)
PYTHON_SCRIPT

    local result=$?
    if [[ $result -eq 0 ]]; then
      log_success "密码重置成功!"
      echo ""
      echo "用户 $username 现在可以使用新密码登录"

      # 提示重启服务使会话失效
      echo ""
      read -r -p "是否重启服务以强制该用户重新登录? [y/N] " ans
      if [[ "${ans}" == "y" || "${ans}" == "Y" ]]; then
        restart_service
      fi
    else
      log_error "密码重置失败"
      return 1
    fi
  else
    log_error "Python 不可用: $PYTHON_BIN"
    return 1
  fi
}

case "${1:-}" in
  help|-h|--help) usage ;;
  start) start_service ;;
  stop) stop_service ;;
  restart) restart_service ;;
  status) status_service ;;
  logs) logs_service ;;
  logs-f) logs_follow ;;
  check) check_update ;;
  update) update_code ;;
  upgrade) upgrade_system ;;
  backup) backup_data "${2:-manual}" ;;
  restore) restore_data "${2:-}" ;;
  list) list_backups ;;
  timer-status) timer_status ;;
  timer-enable) timer_enable ;;
  timer-disable) timer_disable ;;
  timer-install) install_timer ;;
  timer-set) timer_set_time "${2:-}" ;;
  reset-password) reset_admin_password "${2:-}" ;;
  *) usage; exit 1 ;;
esac
