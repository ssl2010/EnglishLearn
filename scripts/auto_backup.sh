#!/usr/bin/env bash
#
# EnglishLearn 自动备份脚本
# 由 systemd timer 定时调用
#
# 配置优先级：
# 1. Web 界面配置 (backup_config.json)
# 2. 环境变量
# 3. 默认值
#

set -euo pipefail

# 基础配置
APP_DIR="${APP_DIR:-/opt/EnglishLearn}"
DATA_DIR="${DATA_DIR:-$APP_DIR/data}"
BACKUP_DIR="${BACKUP_DIR:-/opt/EnglishLearn_Backups}"
DB_PATH="${EL_DB_PATH:-$DATA_DIR/el.db}"
MEDIA_DIR="${EL_MEDIA_DIR:-$DATA_DIR/media}"
LOG_FILE="/var/log/englishlearn/backup.log"

# 默认值
DEFAULT_RETENTION_DAYS=30
DEFAULT_AUTO_BACKUP_ENABLED=true

# 如果存在环境文件，加载它
if [[ -f /etc/englishlearn.env ]]; then
    set -a
    source /etc/englishlearn.env
    set +a
    # 重新设置可能被覆盖的变量
    BACKUP_DIR="${BACKUP_DIR:-/opt/EnglishLearn_Backups}"
    DB_PATH="${EL_DB_PATH:-$DATA_DIR/el.db}"
    MEDIA_DIR="${EL_MEDIA_DIR:-$DATA_DIR/media}"
fi

# Web 配置文件路径
BACKUP_CONFIG_FILE="$DATA_DIR/backup_config.json"

# 读取 Web 配置（JSON）
read_web_config() {
    local key="$1"
    local default="$2"

    if [[ -f "$BACKUP_CONFIG_FILE" ]]; then
        # 使用 Python 解析 JSON（更可靠）
        local value=""
        value=$(python3 -c "
import json
try:
    with open('$BACKUP_CONFIG_FILE', 'r') as f:
        config = json.load(f)
    print(config.get('$key', '$default'))
except:
    print('$default')
" 2>/dev/null || echo "$default")
        echo "$value"
    else
        echo "$default"
    fi
}

# 从 Web 配置读取设置
AUTO_BACKUP_ENABLED=$(read_web_config "auto_backup_enabled" "$DEFAULT_AUTO_BACKUP_ENABLED")
RETENTION_DAYS=$(read_web_config "backup_retention_days" "${BACKUP_RETENTION_DAYS:-$DEFAULT_RETENTION_DAYS}")

# 确保 RETENTION_DAYS 是数字
if ! [[ "$RETENTION_DAYS" =~ ^[0-9]+$ ]]; then
    RETENTION_DAYS=$DEFAULT_RETENTION_DAYS
fi

log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$msg"
    mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true
    echo "$msg" >> "$LOG_FILE" 2>/dev/null || true
}

# 确保目录存在
mkdir -p "$BACKUP_DIR"

log "========== 开始自动备份 =========="
log "配置来源: ${BACKUP_CONFIG_FILE:-环境变量}"
log "自动备份启用: $AUTO_BACKUP_ENABLED"
log "保留天数: $RETENTION_DAYS"
log "数据库: $DB_PATH"
log "媒体目录: $MEDIA_DIR"
log "备份目录: $BACKUP_DIR"

# 检查是否启用自动备份
if [[ "$AUTO_BACKUP_ENABLED" != "true" && "$AUTO_BACKUP_ENABLED" != "True" && "$AUTO_BACKUP_ENABLED" != "1" ]]; then
    log "自动备份已禁用，跳过本次备份"
    log "========== 自动备份跳过 =========="
    exit 0
fi

# 检查数据库是否存在
if [[ ! -f "$DB_PATH" ]]; then
    log "错误: 数据库文件不存在: $DB_PATH"
    exit 1
fi

# 创建备份
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
BACKUP_FILE="$BACKUP_DIR/EnglishLearn_自动备份_${TIMESTAMP}.tar.gz"

log "创建备份: $BACKUP_FILE"

# 创建临时目录存放备份信息
TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

# 创建备份信息文件
cat > "$TEMP_DIR/backup_info.json" <<EOF
{
    "backup_time": "$(date -Iseconds)",
    "description": "系统自动备份 - $TIMESTAMP",
    "version": "1.0",
    "db_included": true,
    "media_included": true,
    "backup_type": "auto",
    "retention_days": $RETENTION_DAYS,
    "restore_note": "此备份由系统自动创建"
}
EOF

# 创建 tar.gz 备份
if [[ -d "$MEDIA_DIR" ]]; then
    tar -czf "$BACKUP_FILE" \
        -C "$TEMP_DIR" backup_info.json \
        -C "$(dirname "$DB_PATH")" "$(basename "$DB_PATH")" \
        -C "$(dirname "$MEDIA_DIR")" "$(basename "$MEDIA_DIR")" \
        2>/dev/null || {
            # 如果失败，只备份数据库
            log "警告: 包含媒体目录失败，仅备份数据库"
            tar -czf "$BACKUP_FILE" \
                -C "$TEMP_DIR" backup_info.json \
                -C "$(dirname "$DB_PATH")" "$(basename "$DB_PATH")"
        }
else
    # 媒体目录不存在，只备份数据库
    tar -czf "$BACKUP_FILE" \
        -C "$TEMP_DIR" backup_info.json \
        -C "$(dirname "$DB_PATH")" "$(basename "$DB_PATH")"
fi

BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
log "备份完成: $BACKUP_FILE ($BACKUP_SIZE)"

# 清理旧备份
log "清理 $RETENTION_DAYS 天前的旧备份..."
DELETED_COUNT=0

while IFS= read -r old_backup; do
    if [[ -n "$old_backup" ]]; then
        log "删除旧备份: $old_backup"
        rm -f "$old_backup"
        DELETED_COUNT=$((DELETED_COUNT + 1))
    fi
done < <(find "$BACKUP_DIR" -name "EnglishLearn_*.tar.gz" -type f -mtime +$RETENTION_DAYS 2>/dev/null)

log "删除了 $DELETED_COUNT 个旧备份"

# 统计当前备份
BACKUP_COUNT=$(find "$BACKUP_DIR" -name "EnglishLearn_*.tar.gz" -type f 2>/dev/null | wc -l)
TOTAL_SIZE=$(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1 || echo "0")

log "当前备份数量: $BACKUP_COUNT"
log "备份目录总大小: $TOTAL_SIZE"
log "========== 自动备份完成 =========="
