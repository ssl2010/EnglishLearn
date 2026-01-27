#!/usr/bin/env bash
#
# EnglishLearn 自动备份脚本
# 由 systemd timer 定时调用
#

set -euo pipefail

# 配置
APP_DIR="${APP_DIR:-/opt/EnglishLearn}"
DATA_DIR="${DATA_DIR:-$APP_DIR/data}"
BACKUP_DIR="${BACKUP_DIR:-/opt/EnglishLearn_Backups}"
DB_PATH="${EL_DB_PATH:-$DATA_DIR/el.db}"
MEDIA_DIR="${EL_MEDIA_DIR:-$DATA_DIR/media}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
LOG_FILE="/var/log/englishlearn/backup.log"

# 如果存在环境文件，加载它
if [[ -f /etc/englishlearn.env ]]; then
    set -a
    source /etc/englishlearn.env
    set +a
    # 重新设置可能被覆盖的变量
    BACKUP_DIR="${BACKUP_DIR:-/opt/EnglishLearn_Backups}"
    DB_PATH="${EL_DB_PATH:-$DATA_DIR/el.db}"
    MEDIA_DIR="${EL_MEDIA_DIR:-$DATA_DIR/media}"
    RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
fi

log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$msg"
    echo "$msg" >> "$LOG_FILE" 2>/dev/null || true
}

# 确保目录存在
mkdir -p "$BACKUP_DIR"
mkdir -p "$(dirname "$LOG_FILE")"

log "========== 开始自动备份 =========="
log "数据库: $DB_PATH"
log "媒体目录: $MEDIA_DIR"
log "备份目录: $BACKUP_DIR"

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
    "restore_note": "此备份由系统自动创建"
}
EOF

# 创建 tar.gz 备份
tar -czf "$BACKUP_FILE" \
    -C "$TEMP_DIR" backup_info.json \
    -C "$(dirname "$DB_PATH")" "$(basename "$DB_PATH")" \
    ${MEDIA_DIR:+-C "$(dirname "$MEDIA_DIR")" "$(basename "$MEDIA_DIR")"} \
    2>/dev/null || {
        # 如果媒体目录不存在，只备份数据库
        tar -czf "$BACKUP_FILE" \
            -C "$TEMP_DIR" backup_info.json \
            -C "$(dirname "$DB_PATH")" "$(basename "$DB_PATH")"
    }

BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
log "备份完成: $BACKUP_FILE ($BACKUP_SIZE)"

# 清理旧备份
log "清理 $RETENTION_DAYS 天前的旧备份..."
DELETED_COUNT=0

find "$BACKUP_DIR" -name "EnglishLearn_*.tar.gz" -type f -mtime +$RETENTION_DAYS | while read -r old_backup; do
    log "删除旧备份: $old_backup"
    rm -f "$old_backup"
    DELETED_COUNT=$((DELETED_COUNT + 1))
done

# 统计当前备份
BACKUP_COUNT=$(find "$BACKUP_DIR" -name "EnglishLearn_*.tar.gz" -type f | wc -l)
TOTAL_SIZE=$(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1 || echo "0")

log "当前备份数量: $BACKUP_COUNT"
log "备份目录总大小: $TOTAL_SIZE"
log "========== 自动备份完成 =========="
