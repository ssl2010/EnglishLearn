"""
备份管理 API
提供完整的系统备份、恢复、下载功能
所有操作通过 Web 界面完成,无需 SSH 登录服务器
"""
from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional
import os
import datetime
import shutil
import tarfile
import json
from pathlib import Path

router = APIRouter(tags=["备份管理"])

# 配置 - 从环境变量读取
# 获取项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

BACKUP_DIR = os.getenv("BACKUP_DIR", os.path.join(PROJECT_ROOT, "backups"))
DATA_DIR = os.getenv("DATA_DIR", os.path.join(PROJECT_ROOT, "backend", "data"))
DB_PATH = os.getenv("DATABASE_URL", f"{DATA_DIR}/el.db").replace("sqlite:///", "")
MEDIA_DIR = os.getenv("MEDIA_DIR", f"{DATA_DIR}/media")
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
        # 创建备份信息
        backup_info = {
            "backup_time": datetime.datetime.now().isoformat(),
            "description": request.description or f"系统备份 - {timestamp}",
            "version": "1.0",
            "db_included": True,
            "media_included": True,
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

        # 清理临时目录
        shutil.rmtree(temp_dir)

        # 读取备份信息
        backup_info = None
        try:
            with tarfile.open(filepath, 'r:gz') as tar:
                if 'backup_info.json' in tar.getnames():
                    info_file = tar.extractfile('backup_info.json')
                    if info_file:
                        backup_info = json.loads(info_file.read().decode('utf-8'))
        except:
            pass

        return {
            "success": True,
            "message": "系统恢复成功!",
            "restored_from": request.filename,
            "backup_time": backup_info.get('backup_time') if backup_info else None,
            "note": "数据已恢复,建议刷新页面以加载最新数据",
            "rollback_files": {
                "db": f"{DB_PATH}.before_restore_{timestamp}",
                "media": f"{MEDIA_DIR}_before_restore_{timestamp}"
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
