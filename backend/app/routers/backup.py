"""
备份管理 API
提供完整的系统备份、恢复、下载、升级功能
所有操作通过 Web 界面完成,无需 SSH 登录服务器
"""
from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional
import os
import sys
import datetime
import shutil
import tarfile
import json
import subprocess
from pathlib import Path

router = APIRouter(tags=["备份管理"])

# 配置 - 从环境变量读取
# 获取项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

BACKUP_DIR = os.getenv("BACKUP_DIR", os.path.join(PROJECT_ROOT, "backups"))
DATA_DIR = os.getenv("DATA_DIR", os.path.join(PROJECT_ROOT, "backend", "data"))

# 数据库路径自动检测
db_path_env = os.getenv("DATABASE_URL", f"{DATA_DIR}/el.db").replace("sqlite:///", "")
if not os.path.exists(db_path_env):
    # 尝试 backend/el.db
    alt_db_path = os.path.join(PROJECT_ROOT, "backend", "el.db")
    if os.path.exists(alt_db_path):
        DB_PATH = alt_db_path
        DATA_DIR = os.path.join(PROJECT_ROOT, "backend")
    else:
        DB_PATH = db_path_env
else:
    DB_PATH = db_path_env

# 媒体文件路径自动检测
media_dir_env = os.getenv("MEDIA_DIR", f"{DATA_DIR}/media")
if not os.path.exists(media_dir_env):
    # 尝试 backend/media
    alt_media_dir = os.path.join(PROJECT_ROOT, "backend", "media")
    if os.path.exists(alt_media_dir):
        MEDIA_DIR = alt_media_dir
    else:
        MEDIA_DIR = media_dir_env
else:
    MEDIA_DIR = media_dir_env

APP_DIR = os.getenv("APP_DIR", PROJECT_ROOT)

# 备份配置文件路径
BACKUP_CONFIG_FILE = os.path.join(DATA_DIR, "backup_config.json")


class BackupInfo(BaseModel):
    """备份信息"""
    filename: str
    size: int
    size_human: str
    created_at: str
    description: Optional[str] = None


class BackupCreateRequest(BaseModel):
    """创建备份请求 - 简化版,统一打包"""
    description: Optional[str] = None


class RestoreRequest(BaseModel):
    """恢复备份请求 - 简化版,完整恢复"""
    filename: str


class BackupConfig(BaseModel):
    """备份配置"""
    auto_backup_enabled: bool = True
    auto_backup_time: str = "02:00"  # 每天凌晨2点
    backup_retention_days: int = 30  # 保留30天
    auto_cleanup_enabled: bool = True


class SystemSettings(BaseModel):
    """系统设置"""
    backup_config: BackupConfig
    system_info: dict


def get_human_size(size_bytes: int) -> str:
    """转换文件大小为人类可读格式"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"


def ensure_backup_dir():
    """确保备份目录存在"""
    os.makedirs(BACKUP_DIR, exist_ok=True)


def load_backup_config() -> BackupConfig:
    """加载备份配置"""
    if os.path.exists(BACKUP_CONFIG_FILE):
        try:
            with open(BACKUP_CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return BackupConfig(**data)
        except:
            pass
    return BackupConfig()


def save_backup_config(config: BackupConfig):
    """保存备份配置"""
    os.makedirs(os.path.dirname(BACKUP_CONFIG_FILE), exist_ok=True)
    with open(BACKUP_CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config.dict(), f, indent=2, ensure_ascii=False)


def parse_env_file(filepath: str) -> dict:
    """解析 .env 文件，返回 {key: value} 字典"""
    result = {}
    if not os.path.exists(filepath):
        return result
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                # 跳过空行和注释
                if not line or line.startswith('#'):
                    continue
                # 解析 KEY=VALUE
                if '=' in line:
                    key, _, value = line.partition('=')
                    key = key.strip()
                    value = value.strip()
                    # 移除引号
                    if value and value[0] in ('"', "'") and value[-1] == value[0]:
                        value = value[1:-1]
                    result[key] = value
    except Exception:
        pass
    return result


def check_and_merge_env_config(app_dir: str) -> dict:
    """
    检查并合并环境配置

    比较 .env.example 和当前 .env（或 /etc/englishlearn.env），
    将缺失的配置项添加到用户的 .env 文件中。

    返回: {"new_keys": [...], "env_file": "..."}
    """
    result = {"new_keys": [], "env_file": None}

    # 查找 .env.example
    example_path = os.path.join(app_dir, ".env.example")
    if not os.path.exists(example_path):
        return result

    # 查找用户的 .env 文件
    # 优先使用 /etc/englishlearn.env（生产环境）
    env_paths = [
        "/etc/englishlearn.env",
        os.path.join(app_dir, ".env"),
    ]

    user_env_path = None
    for path in env_paths:
        if os.path.exists(path):
            user_env_path = path
            break

    if not user_env_path:
        # 没有现有配置文件，不做处理
        return result

    result["env_file"] = user_env_path

    # 解析配置文件
    example_config = parse_env_file(example_path)
    user_config = parse_env_file(user_env_path)

    # 找出缺失的配置项
    missing_keys = []
    for key in example_config:
        if key not in user_config:
            missing_keys.append(key)

    if not missing_keys:
        return result

    # 读取原始 .env.example 文件内容，保留注释结构
    try:
        with open(example_path, 'r', encoding='utf-8') as f:
            example_lines = f.readlines()
    except Exception:
        return result

    # 构建要添加的内容块
    # 按照 .env.example 的顺序，提取缺失配置项及其前面的注释
    lines_to_add = []
    current_comments = []
    added_keys = set()

    for line in example_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            current_comments.append(line)
        elif '=' in stripped:
            key = stripped.partition('=')[0].strip()
            if key in missing_keys and key not in added_keys:
                # 添加注释和配置行
                if current_comments:
                    lines_to_add.extend(current_comments)
                lines_to_add.append(line)
                added_keys.add(key)
            current_comments = []
        else:
            current_comments = []

    if not lines_to_add:
        return result

    # 追加到用户的 .env 文件
    try:
        with open(user_env_path, 'a', encoding='utf-8') as f:
            f.write("\n\n# ============================================================\n")
            f.write(f"# 以下配置由系统升级自动添加 ({datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')})\n")
            f.write("# ============================================================\n")
            f.writelines(lines_to_add)

        result["new_keys"] = list(added_keys)
    except Exception as e:
        # 写入失败，记录但不中断升级
        pass

    return result


@router.get("/list", response_model=List[BackupInfo])
async def list_backups():
    """列出所有备份"""
    ensure_backup_dir()

    backups = []
    for filename in sorted(os.listdir(BACKUP_DIR), reverse=True):
        if not filename.endswith('.tar.gz'):
            continue

        filepath = os.path.join(BACKUP_DIR, filename)
        stat = os.stat(filepath)

        # 尝试读取备份描述
        description = None
        try:
            with tarfile.open(filepath, 'r:gz') as tar:
                if 'backup_info.json' in tar.getnames():
                    info_file = tar.extractfile('backup_info.json')
                    if info_file:
                        info_data = json.loads(info_file.read().decode('utf-8'))
                        description = info_data.get('description')
        except:
            pass

        backups.append(BackupInfo(
            filename=filename,
            size=stat.st_size,
            size_human=get_human_size(stat.st_size),
            created_at=datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
            description=description
        ))

    return backups


@router.post("/create")
async def create_backup(request: BackupCreateRequest):
    """
    创建系统备份

    备份内容包括:
    - 数据库文件 (el.db)
    - 所有媒体文件 (media/)
    - 备份信息 (backup_info.json)

    用户无需关心具体包含什么,这个备份包可以恢复系统到备份时刻的状态
    """
    ensure_backup_dir()

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"EnglishLearn_备份_{timestamp}.tar.gz"
    filepath = os.path.join(BACKUP_DIR, filename)

    try:
        # 检查 .env 文件是否存在
        env_path = os.path.join(PROJECT_ROOT, ".env")
        env_exists = os.path.exists(env_path)

        # 创建备份信息
        backup_info = {
            "backup_time": datetime.datetime.now().isoformat(),
            "description": request.description or f"系统备份 - {timestamp}",
            "version": "1.0",
            "db_included": True,
            "media_included": True,
            "env_included": env_exists,  # 根据实际情况设置
            "restore_note": "此备份包含所有系统数据，可恢复到备份时刻的状态"
        }

        # 直接创建 tar.gz 压缩包
        with tarfile.open(filepath, "w:gz") as tar:
            # 添加备份信息文件
            info_json = json.dumps(backup_info, indent=2, ensure_ascii=False)
            info_bytes = info_json.encode('utf-8')

            import io
            info_tarinfo = tarfile.TarInfo(name='backup_info.json')
            info_tarinfo.size = len(info_bytes)
            info_tarinfo.mtime = datetime.datetime.now().timestamp()
            tar.addfile(info_tarinfo, io.BytesIO(info_bytes))

            # 添加数据库文件
            if os.path.exists(DB_PATH):
                tar.add(DB_PATH, arcname='el.db')

            # 添加媒体文件目录
            if os.path.exists(MEDIA_DIR):
                tar.add(MEDIA_DIR, arcname='media')

            # 添加 .env 文件（如果存在）
            if env_exists:
                tar.add(env_path, arcname='.env')

        # 获取文件大小
        size = os.path.getsize(filepath)

        return {
            "success": True,
            "message": "备份创建成功!",
            "filename": filename,
            "size": size,
            "size_human": get_human_size(size),
            "note": "此备份包含完整的系统数据,可用于恢复到备份时刻的完整状态"
        }

    except Exception as e:
        # 清理失败的备份文件
        if os.path.exists(filepath):
            os.remove(filepath)
        raise HTTPException(status_code=500, detail=f"备份失败: {str(e)}")


@router.get("/download/{filename}")
async def download_backup(filename: str):
    """下载备份文件到本地"""
    filepath = os.path.join(BACKUP_DIR, filename)

    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="备份文件不存在")

    if not filename.endswith('.tar.gz'):
        raise HTTPException(status_code=400, detail="无效的备份文件")

    return FileResponse(
        filepath,
        media_type='application/gzip',
        filename=filename,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )


@router.post("/restore")
async def restore_backup(request: RestoreRequest):
    """
    恢复系统备份

    警告: 此操作将覆盖当前所有数据!
    建议在恢复前先创建当前状态的备份

    恢复过程:
    1. 解压备份包
    2. 恢复数据库
    3. 恢复媒体文件
    4. 系统将自动重启以加载新数据
    """
    filepath = os.path.join(BACKUP_DIR, request.filename)

    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="备份文件不存在")

    try:
        # 创建临时解压目录
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        temp_dir = os.path.join(BACKUP_DIR, f"restore_temp_{timestamp}")
        os.makedirs(temp_dir, exist_ok=True)

        # 解压备份文件
        with tarfile.open(filepath, "r:gz") as tar:
            tar.extractall(temp_dir)

        # 备份当前数据 (以防恢复失败)
        if os.path.exists(DB_PATH):
            backup_current_db = f"{DB_PATH}.before_restore_{timestamp}"
            shutil.copy2(DB_PATH, backup_current_db)

        if os.path.exists(MEDIA_DIR):
            backup_current_media = f"{MEDIA_DIR}_before_restore_{timestamp}"
            shutil.copytree(MEDIA_DIR, backup_current_media, dirs_exist_ok=True)

        # 恢复数据库
        db_file = os.path.join(temp_dir, "el.db")
        if os.path.exists(db_file):
            shutil.copy2(db_file, DB_PATH)
        else:
            raise Exception("备份文件中未找到数据库")

        # 恢复媒体文件
        media_dir = os.path.join(temp_dir, "media")
        if os.path.exists(media_dir):
            # 删除旧媒体目录
            if os.path.exists(MEDIA_DIR):
                shutil.rmtree(MEDIA_DIR)
            # 复制新媒体目录
            shutil.copytree(media_dir, MEDIA_DIR)

        # 恢复 .env 文件（如果备份中包含）
        env_file = os.path.join(temp_dir, ".env")
        if os.path.exists(env_file):
            env_dest = os.path.join(PROJECT_ROOT, ".env")
            # 备份当前 .env（如果存在）
            if os.path.exists(env_dest):
                env_backup = f"{env_dest}.before_restore_{timestamp}"
                shutil.copy2(env_dest, env_backup)
            # 恢复 .env
            shutil.copy2(env_file, env_dest)

        # 清理临时目录
        shutil.rmtree(temp_dir)

        # 检查并运行数据库迁移（支持从老版本恢复）
        migration_result = None
        try:
            # 导入迁移管理器
            migration_manager_path = os.path.join(PROJECT_ROOT, "backend", "migration_manager.py")
            if os.path.exists(migration_manager_path):
                # 使用 subprocess 运行迁移，避免导入问题
                result = subprocess.run(
                    [sys.executable, migration_manager_path, "migrate"],
                    cwd=PROJECT_ROOT,
                    capture_output=True,
                    text=True,
                    timeout=60
                )

                if result.returncode == 0:
                    migration_result = {
                        "success": True,
                        "message": "数据库迁移成功",
                        "output": result.stdout
                    }
                else:
                    migration_result = {
                        "success": False,
                        "message": "数据库迁移失败，但数据已恢复",
                        "error": result.stderr
                    }
        except Exception as e:
            migration_result = {
                "success": False,
                "message": f"无法运行数据库迁移: {str(e)}"
            }

        # 读取备份信息
        backup_info = None
        env_restored = False
        try:
            with tarfile.open(filepath, 'r:gz') as tar:
                members = tar.getnames()
                if 'backup_info.json' in members:
                    info_file = tar.extractfile('backup_info.json')
                    if info_file:
                        backup_info = json.loads(info_file.read().decode('utf-8'))
                if '.env' in members:
                    env_restored = True
        except:
            pass

        return {
            "success": True,
            "message": "系统恢复成功!",
            "restored_from": request.filename,
            "backup_time": backup_info.get('backup_time') if backup_info else None,
            "env_restored": env_restored,
            "migration_result": migration_result,
            "note": ("数据已恢复,建议刷新页面以加载最新数据。" +
                    ("如果恢复了 .env 文件,请重启服务以使配置生效。" if env_restored else "") +
                    (" 数据库迁移已自动运行。" if migration_result and migration_result.get("success") else "")),
            "rollback_files": {
                "db": f"{DB_PATH}.before_restore_{timestamp}",
                "media": f"{MEDIA_DIR}_before_restore_{timestamp}",
                "env": f"{os.path.join(PROJECT_ROOT, '.env')}.before_restore_{timestamp}" if env_restored else None
            }
        }

    except Exception as e:
        # 清理临时目录
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        raise HTTPException(status_code=500, detail=f"恢复失败: {str(e)}")


@router.delete("/delete/{filename}")
async def delete_backup(filename: str):
    """删除备份文件"""
    filepath = os.path.join(BACKUP_DIR, filename)

    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="备份文件不存在")

    if not filename.endswith('.tar.gz'):
        raise HTTPException(status_code=400, detail="无效的备份文件")

    try:
        os.remove(filepath)
        return {
            "success": True,
            "message": "备份文件已删除",
            "filename": filename
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


@router.post("/cleanup")
async def cleanup_old_backups(keep_days: int = 30):
    """
    清理旧备份

    默认保留最近 30 天的备份,可以在系统设置中配置
    """
    ensure_backup_dir()

    cutoff_time = datetime.datetime.now() - datetime.timedelta(days=keep_days)
    deleted_count = 0
    freed_space = 0

    for filename in os.listdir(BACKUP_DIR):
        if not filename.endswith('.tar.gz'):
            continue

        filepath = os.path.join(BACKUP_DIR, filename)
        stat = os.stat(filepath)
        mtime = datetime.datetime.fromtimestamp(stat.st_mtime)

        if mtime < cutoff_time:
            freed_space += stat.st_size
            os.remove(filepath)
            deleted_count += 1

    return {
        "success": True,
        "message": f"清理完成,删除了 {deleted_count} 个旧备份",
        "deleted_count": deleted_count,
        "freed_space": freed_space,
        "freed_space_human": get_human_size(freed_space),
        "keep_days": keep_days
    }


@router.get("/space")
async def get_backup_space():
    """获取备份空间使用情况"""
    ensure_backup_dir()

    total_size = 0
    backup_count = 0

    for filename in os.listdir(BACKUP_DIR):
        if filename.endswith('.tar.gz'):
            filepath = os.path.join(BACKUP_DIR, filename)
            total_size += os.path.getsize(filepath)
            backup_count += 1

    # 获取磁盘空间
    stat = os.statvfs(BACKUP_DIR)
    disk_total = stat.f_blocks * stat.f_frsize
    disk_free = stat.f_bavail * stat.f_frsize
    disk_used = disk_total - disk_free

    return {
        "backup_count": backup_count,
        "backup_total_size": total_size,
        "backup_total_size_human": get_human_size(total_size),
        "disk_total": disk_total,
        "disk_total_human": get_human_size(disk_total),
        "disk_used": disk_used,
        "disk_used_human": get_human_size(disk_used),
        "disk_free": disk_free,
        "disk_free_human": get_human_size(disk_free),
        "disk_usage_percent": round(disk_used / disk_total * 100, 2)
    }


@router.get("/config", response_model=BackupConfig)
async def get_backup_config():
    """获取备份配置"""
    return load_backup_config()


@router.post("/config")
async def update_backup_config(config: BackupConfig):
    """
    更新备份配置

    配置项:
    - auto_backup_enabled: 是否启用自动备份
    - auto_backup_time: 自动备份时间 (24小时制,如 "02:00")
    - backup_retention_days: 备份保留天数
    - auto_cleanup_enabled: 是否自动清理旧备份
    """
    try:
        save_backup_config(config)

        # 这里应该更新 crontab 或 systemd timer
        # 简化版本:保存配置文件,由外部脚本读取

        return {
            "success": True,
            "message": "备份配置已更新",
            "config": config.dict(),
            "note": "配置已保存,自动备份任务将在下次执行时生效"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"配置更新失败: {str(e)}")


@router.get("/system-info")
async def get_system_info():
    """
    获取系统信息

    用于在 Web 界面显示系统状态
    """
    import platform
    import psutil

    # CPU 信息
    cpu_percent = psutil.cpu_percent(interval=1)
    cpu_count = psutil.cpu_count()

    # 内存信息
    memory = psutil.virtual_memory()

    # 磁盘信息
    disk = psutil.disk_usage('/')

    # 数据库大小
    db_size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0

    # 媒体文件大小
    media_size = 0
    if os.path.exists(MEDIA_DIR):
        for dirpath, dirnames, filenames in os.walk(MEDIA_DIR):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                media_size += os.path.getsize(filepath)

    return {
        "system": {
            "os": platform.system(),
            "os_version": platform.release(),
            "python_version": platform.python_version(),
            "hostname": platform.node()
        },
        "cpu": {
            "count": cpu_count,
            "usage_percent": cpu_percent
        },
        "memory": {
            "total": memory.total,
            "total_human": get_human_size(memory.total),
            "used": memory.used,
            "used_human": get_human_size(memory.used),
            "usage_percent": memory.percent
        },
        "disk": {
            "total": disk.total,
            "total_human": get_human_size(disk.total),
            "used": disk.used,
            "used_human": get_human_size(disk.used),
            "free": disk.free,
            "free_human": get_human_size(disk.free),
            "usage_percent": disk.percent
        },
        "data": {
            "database_size": db_size,
            "database_size_human": get_human_size(db_size),
            "media_size": media_size,
            "media_size_human": get_human_size(media_size),
            "total_data_size": db_size + media_size,
            "total_data_size_human": get_human_size(db_size + media_size)
        }
    }


@router.get("/git-status")
async def get_git_status():
    """
    获取 Git 仓库状态

    检查当前分支、是否有新版本可用等
    """
    import subprocess

    try:
        # 检查是否是 Git 仓库
        if not os.path.exists(os.path.join(APP_DIR, ".git")):
            return {
                "is_git_repo": False,
                "message": "当前不是 Git 仓库，无法使用自动升级功能"
            }

        # 配置 git safe.directory（避免 dubious ownership 错误）
        subprocess.run(
            ["git", "config", "--global", "--add", "safe.directory", APP_DIR],
            capture_output=True,
            timeout=10
        )

        # 获取当前分支
        branch_result = subprocess.run(
            ["git", "-C", APP_DIR, "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=10
        )
        current_branch = branch_result.stdout.strip()

        # 获取当前 commit
        commit_result = subprocess.run(
            ["git", "-C", APP_DIR, "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10
        )
        current_commit = commit_result.stdout.strip()

        # 获取远程更新（不拉取）
        fetch_result = subprocess.run(
            ["git", "-C", APP_DIR, "fetch", "origin", current_branch],
            capture_output=True,
            text=True,
            timeout=30
        )

        # 检查是否有新版本
        status_result = subprocess.run(
            ["git", "-C", APP_DIR, "rev-list", "--count", f"HEAD..origin/{current_branch}"],
            capture_output=True,
            text=True,
            timeout=10
        )
        commits_behind = int(status_result.stdout.strip() or "0")

        # 获取最新的远程 commit
        remote_commit_result = subprocess.run(
            ["git", "-C", APP_DIR, "rev-parse", "--short", f"origin/{current_branch}"],
            capture_output=True,
            text=True,
            timeout=10
        )
        remote_commit = remote_commit_result.stdout.strip()

        return {
            "is_git_repo": True,
            "current_branch": current_branch,
            "current_commit": current_commit,
            "remote_commit": remote_commit,
            "commits_behind": commits_behind,
            "update_available": commits_behind > 0,
            "message": f"发现 {commits_behind} 个新版本" if commits_behind > 0 else "已是最新版本"
        }

    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="Git 操作超时")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取 Git 状态失败: {str(e)}")


class UpgradeRequest(BaseModel):
    """升级请求"""
    auto_backup: bool = True  # 升级前是否自动备份
    skip_pip: bool = False    # 是否跳过 pip install


@router.post("/upgrade")
async def upgrade_system(request: UpgradeRequest, background_tasks: BackgroundTasks):
    """
    一键升级系统

    执行步骤:
    1. 检查 Git 仓库状态
    2. 创建自动备份（如果启用）
    3. 拉取最新代码 (git pull)
    4. 安装依赖 (pip install)
    5. 重启服务

    注意: 此操作会重启服务,导致短暂不可用
    """
    import subprocess

    try:
        # 检查是否是 Git 仓库
        if not os.path.exists(os.path.join(APP_DIR, ".git")):
            raise HTTPException(
                status_code=400,
                detail="当前不是 Git 仓库，无法使用自动升级功能。请使用手动部署方式。"
            )

        # 配置 git safe.directory（避免 dubious ownership 错误）
        subprocess.run(
            ["git", "config", "--global", "--add", "safe.directory", APP_DIR],
            capture_output=True,
            timeout=10
        )

        # 获取当前分支
        branch_result = subprocess.run(
            ["git", "-C", APP_DIR, "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=10
        )
        current_branch = branch_result.stdout.strip()

        # 检查是否有本地未提交的更改
        status_result = subprocess.run(
            ["git", "-C", APP_DIR, "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10
        )

        if status_result.stdout.strip():
            raise HTTPException(
                status_code=400,
                detail="检测到本地有未提交的更改，请先处理这些更改后再升级"
            )

        upgrade_log = []

        # 步骤 1: 自动备份
        if request.auto_backup:
            upgrade_log.append("📦 正在创建升级前备份...")
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"EnglishLearn_升级前备份_{timestamp}.tar.gz"
            filepath = os.path.join(BACKUP_DIR, filename)

            ensure_backup_dir()

            # 创建备份信息
            backup_info = {
                "backup_time": datetime.datetime.now().isoformat(),
                "description": f"升级前自动备份 - {timestamp}",
                "version": "1.0",
                "db_included": True,
                "media_included": os.path.exists(MEDIA_DIR),
                "backup_type": "pre_upgrade",
                "restore_note": "此备份在系统升级前自动创建"
            }

            with tarfile.open(filepath, "w:gz") as tar:
                # 添加备份信息
                import io
                info_json = json.dumps(backup_info, indent=2, ensure_ascii=False)
                info_bytes = info_json.encode('utf-8')
                info_tarinfo = tarfile.TarInfo(name='backup_info.json')
                info_tarinfo.size = len(info_bytes)
                info_tarinfo.mtime = datetime.datetime.now().timestamp()
                tar.addfile(info_tarinfo, io.BytesIO(info_bytes))

                if os.path.exists(DB_PATH):
                    tar.add(DB_PATH, arcname='el.db')
                if os.path.exists(MEDIA_DIR):
                    tar.add(MEDIA_DIR, arcname='media')

            upgrade_log.append(f"✅ 备份已创建: {filename}")

        # 步骤 2: 拉取最新代码
        upgrade_log.append("📥 正在拉取最新代码...")
        pull_result = subprocess.run(
            ["git", "-C", APP_DIR, "pull", "--rebase", "origin", current_branch],
            capture_output=True,
            text=True,
            timeout=60
        )

        if pull_result.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"Git pull 失败: {pull_result.stderr}"
            )

        upgrade_log.append("✅ 代码已更新")
        upgrade_log.append(pull_result.stdout)

        # 步骤 3: 安装依赖
        if not request.skip_pip:
            upgrade_log.append("📦 正在安装 Python 依赖...")

            # 获取 Python 路径
            python_bin = os.path.join(APP_DIR, "venv", "bin", "python")
            if not os.path.exists(python_bin):
                python_bin = "python3"  # 开发环境 fallback

            pip_result = subprocess.run(
                [python_bin, "-m", "pip", "install", "-r",
                 os.path.join(APP_DIR, "backend", "requirements.txt")],
                capture_output=True,
                text=True,
                timeout=300
            )

            if pip_result.returncode != 0:
                upgrade_log.append(f"⚠️  依赖安装警告: {pip_result.stderr}")
            else:
                upgrade_log.append("✅ 依赖已更新")

        # 步骤 4: 检查并合并环境配置
        upgrade_log.append("⚙️  检查环境配置...")
        env_update_result = check_and_merge_env_config(APP_DIR)
        if env_update_result.get("new_keys"):
            upgrade_log.append(f"✅ 已添加 {len(env_update_result['new_keys'])} 个新配置项")
            for key in env_update_result['new_keys'][:5]:  # 最多显示5个
                upgrade_log.append(f"   + {key}")
            if len(env_update_result['new_keys']) > 5:
                upgrade_log.append(f"   ... 等 {len(env_update_result['new_keys']) - 5} 个")
        else:
            upgrade_log.append("✅ 环境配置已是最新")

        # 步骤 5: 执行数据库迁移
        upgrade_log.append("🗄️  检查数据库迁移...")

        try:
            # 导入迁移管理器
            sys.path.insert(0, os.path.join(APP_DIR, "backend"))
            from migration_manager import MigrationManager

            # 创建迁移管理器实例
            manager = MigrationManager(DB_PATH)

            # 检查是否需要迁移
            if manager.check_migration_needed():
                upgrade_log.append("📋 发现待执行的数据库迁移")

                # 执行迁移
                migration_results = manager.migrate_all(stop_on_error=True)

                if migration_results['failed'] > 0:
                    raise Exception(
                        f"数据库迁移失败: {migration_results['failed']} 个迁移失败"
                    )

                upgrade_log.append(
                    f"✅ 数据库迁移完成: "
                    f"成功 {migration_results['success']} 个"
                )
            else:
                upgrade_log.append("✅ 数据库已是最新版本，无需迁移")

        except ImportError:
            upgrade_log.append("⚠️  未找到迁移管理器，跳过数据库迁移")
        except Exception as e:
            upgrade_log.append(f"❌ 数据库迁移失败: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"数据库迁移失败: {str(e)}"
            )

        # 步骤 6: 重启服务
        upgrade_log.append("🔄 准备重启服务...")

        # 检查是否是 systemd 服务
        service_check = subprocess.run(
            ["systemctl", "is-active", "englishlearn"],
            capture_output=True,
            text=True
        )

        if service_check.returncode == 0:
            # 生产环境 - 使用 systemd
            subprocess.run(["systemctl", "restart", "englishlearn"], timeout=30)
            upgrade_log.append("✅ 服务已重启 (systemd)")
        else:
            # 开发环境 - 提示手动重启
            upgrade_log.append("⚠️  请手动重启开发服务器")

        upgrade_log.append("🎉 升级完成！")

        return {
            "success": True,
            "message": "系统升级成功",
            "log": upgrade_log,
            "note": "如果使用开发服务器，请手动重启"
        }

    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="升级操作超时")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"升级失败: {str(e)}")
