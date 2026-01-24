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
BACKUP_DIR="${BACKUP_DIR:-$SCRIPT_DIR/EL_Backup}"
PYTHON_BIN="${PYTHON_BIN:-$APP_DIR/venv/bin/python}"

if [[ "$(id -u)" -eq 0 ]]; then
  SUDO=""
else
  SUDO="sudo"
fi

usage() {
  cat <<EOF
Usage: $0 {start|stop|restart|status|logs|update|backup|restore|list|help}

Commands:
  start     Start systemd service
  stop      Stop systemd service
  restart   Restart systemd service
  status    Show systemd status
  logs      Tail service logs (journalctl)
  update    Pull latest code + pip install + restart (no DB migration)
  backup    Backup DB + media into ./EL_Backup
  restore   Restore from a backup file (or "latest")
  list      List backups in ./EL_Backup
  help      Show this help message

Env overrides:
  APP_DIR=/opt/EnglishLearn
  SERVICE_NAME=englishlearn
  DATA_DIR=\$APP_DIR/data
  DB_PATH=\$DATA_DIR/el.db
  MEDIA_DIR=\$DATA_DIR/media
  ENV_FILE=/etc/englishlearn.env
  BACKUP_DIR=\$SCRIPT_DIR/EL_Backup
  PYTHON_BIN=\$APP_DIR/venv/bin/python
  SKIP_PIP=1           (skip pip install on update)
  SKIP_MIGRATION=1     (skip database migrations on update)
  SKIP_ENV=1           (skip copying .env to /etc)
  BACKUP_NO_STOP=1     (backup without stopping service)
  FORCE=1              (restore without confirmation)
EOF
}

ensure_backup_dir() {
  mkdir -p "$BACKUP_DIR"
}

is_running() {
  $SUDO systemctl is-active --quiet "$SERVICE_NAME"
}

start_service() {
  echo "Starting $SERVICE_NAME..."
  $SUDO systemctl start "$SERVICE_NAME"
  $SUDO systemctl status "$SERVICE_NAME" --no-pager
}

stop_service() {
  echo "Stopping $SERVICE_NAME..."
  $SUDO systemctl stop "$SERVICE_NAME"
}

restart_service() {
  echo "Restarting $SERVICE_NAME..."
  $SUDO systemctl restart "$SERVICE_NAME"
  $SUDO systemctl status "$SERVICE_NAME" --no-pager
}

status_service() {
  $SUDO systemctl status "$SERVICE_NAME" --no-pager
}

logs_service() {
  $SUDO journalctl -u "$SERVICE_NAME" --no-pager -n 200
}

update_code() {
  stop_service

  if [[ ! -d "$APP_DIR/.git" ]]; then
    echo "Update failed: no .git directory found in $APP_DIR"
    return 1
  fi

  echo "Updating code from GitHub..."
  git -C "$APP_DIR" pull --rebase

  if [[ "${SKIP_PIP:-}" != "1" ]]; then
    echo "Installing Python dependencies..."
    "$PYTHON_BIN" -m pip install -r "$APP_DIR/backend/requirements.txt"
  else
    echo "SKIP_PIP=1 set, skipping pip install."
  fi

  # 执行数据库迁移
  if [[ "${SKIP_MIGRATION:-}" != "1" ]]; then
    echo "Running database migrations..."
    if [[ -f "$APP_DIR/backend/migration_manager.py" ]]; then
      "$PYTHON_BIN" "$APP_DIR/backend/migration_manager.py" migrate
      if [[ $? -ne 0 ]]; then
        echo "⚠️  Database migration failed, but continuing..."
      fi
    else
      echo "⚠️  Migration manager not found, skipping migrations"
    fi
  else
    echo "SKIP_MIGRATION=1 set, skipping database migrations."
  fi

  if [[ "${FORCE_ENV_SYNC:-}" == "1" ]] && [[ -f "$APP_DIR/.env" ]]; then
    echo "Syncing .env to $ENV_FILE (FORCE_ENV_SYNC=1)"
    $SUDO cp "$APP_DIR/.env" "$ENV_FILE"
  else
    echo "Skip syncing .env (set FORCE_ENV_SYNC=1 to copy)"
  fi

  if [[ -x /usr/sbin/nginx ]]; then
    $SUDO /usr/sbin/nginx -t && $SUDO systemctl reload nginx || true
  fi

  start_service
}

backup_data() {
  ensure_backup_dir
  local ts
  ts="$(date +"%Y%m%d_%H%M%S")"
  local backup_file="$BACKUP_DIR/EL_backup_${ts}.tar.gz"

  local was_running="0"
  if is_running; then
    was_running="1"
  fi

  if [[ "${BACKUP_NO_STOP:-}" != "1" ]] && [[ "$was_running" == "1" ]]; then
    stop_service
  fi

  echo "Creating backup: $backup_file"
  $SUDO tar -czf "$backup_file" -C "$DATA_DIR" "$(basename "$DB_PATH")" "$(basename "$MEDIA_DIR")"

  if [[ "${BACKUP_NO_STOP:-}" != "1" ]] && [[ "$was_running" == "1" ]]; then
    start_service
  fi

  echo "Backup complete."
}

restore_data() {
  ensure_backup_dir
  local target="${1:-}"
  if [[ -z "$target" ]]; then
    echo "Restore requires a backup file path or 'latest'."
    return 1
  fi

  if [[ "$target" == "latest" ]]; then
    target="$(ls -1t "$BACKUP_DIR"/EL_backup_*.tar.gz 2>/dev/null | head -n 1 || true)"
  fi

  if [[ -z "$target" || ! -f "$target" ]]; then
    echo "Backup file not found: $target"
    return 1
  fi

  if [[ "${FORCE:-}" != "1" ]]; then
    read -r -p "This will overwrite DB and media. Continue? [y/N] " ans
    if [[ "${ans}" != "y" && "${ans}" != "Y" ]]; then
      echo "Restore cancelled."
      return 0
    fi
  fi

  stop_service

  echo "Restoring from $target"
  $SUDO tar -xzf "$target" -C "$DATA_DIR"

  start_service
  echo "Restore complete."
}

list_backups() {
  ensure_backup_dir
  ls -lh "$BACKUP_DIR"
}

case "${1:-}" in
  help|-h|--help) usage ;;
  start) start_service ;;
  stop) stop_service ;;
  restart) restart_service ;;
  status) status_service ;;
  logs) logs_service ;;
  update) update_code ;;
  backup) backup_data ;;
  restore) restore_data "${2:-}" ;;
  list) list_backups ;;
  *) usage; exit 1 ;;
esac
