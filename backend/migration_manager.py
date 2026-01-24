#!/usr/bin/env python3
"""
数据库迁移管理器

功能：
1. 自动检测并执行待运行的迁移
2. 记录已执行的迁移历史
3. 支持迁移回滚
4. 提供迁移状态查询
"""

import os
import sqlite3
import sys
import importlib.util
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional


class MigrationManager:
    """数据库迁移管理器"""

    def __init__(self, db_path: str, migrations_dir: str = None):
        """
        初始化迁移管理器

        Args:
            db_path: 数据库文件路径
            migrations_dir: 迁移脚本目录，默认为当前目录下的 migrations/
        """
        self.db_path = db_path
        self.migrations_dir = migrations_dir or os.path.join(
            os.path.dirname(__file__), "migrations"
        )

        # 确保迁移目录存在
        os.makedirs(self.migrations_dir, exist_ok=True)

        # 初始化迁移历史表
        self._init_migration_table()

    def _init_migration_table(self):
        """创建迁移历史表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL,
                execution_time_ms INTEGER,
                success INTEGER DEFAULT 1,
                error_message TEXT
            )
        """)

        conn.commit()
        conn.close()

    def get_applied_migrations(self) -> List[str]:
        """获取已应用的迁移版本列表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT version FROM schema_migrations
            WHERE success = 1
            ORDER BY version
        """)

        versions = [row[0] for row in cursor.fetchall()]
        conn.close()

        return versions

    def get_pending_migrations(self) -> List[Dict]:
        """获取待执行的迁移列表"""
        applied = set(self.get_applied_migrations())
        pending = []

        # 扫描迁移目录
        migration_files = sorted([
            f for f in os.listdir(self.migrations_dir)
            if f.endswith('.py') and not f.startswith('__')
        ])

        for filename in migration_files:
            # 从文件名提取版本号：YYYYMMDD_HHMMSS_description.py
            version = filename.split('_')[0] + '_' + filename.split('_')[1]

            if version not in applied:
                pending.append({
                    'version': version,
                    'filename': filename,
                    'path': os.path.join(self.migrations_dir, filename)
                })

        return pending

    def run_migration(self, migration: Dict) -> bool:
        """
        执行单个迁移

        Args:
            migration: 迁移信息字典

        Returns:
            是否成功
        """
        version = migration['version']
        filename = migration['filename']
        path = migration['path']

        print(f"📦 运行迁移: {filename}")

        # 动态加载迁移模块
        spec = importlib.util.spec_from_file_location(
            f"migration_{version}", path
        )
        module = importlib.util.module_from_spec(spec)

        start_time = datetime.now()

        try:
            spec.loader.exec_module(module)

            # 执行迁移（假设迁移脚本有 migrate() 函数）
            if hasattr(module, 'migrate'):
                conn = sqlite3.connect(self.db_path)
                module.migrate(conn)
                conn.close()
            else:
                raise Exception("迁移脚本缺少 migrate() 函数")

            # 记录成功
            execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
            self._record_migration(version, filename, execution_time, True, None)

            print(f"✅ 迁移完成: {filename} ({execution_time}ms)")
            return True

        except Exception as e:
            # 记录失败
            error_msg = str(e)
            self._record_migration(version, filename, 0, False, error_msg)

            print(f"❌ 迁移失败: {filename}")
            print(f"   错误: {error_msg}")
            return False

    def _record_migration(self, version: str, name: str,
                         execution_time: int, success: bool,
                         error_message: Optional[str]):
        """记录迁移执行结果"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT OR REPLACE INTO schema_migrations
            (version, name, applied_at, execution_time_ms, success, error_message)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            version,
            name,
            datetime.now().isoformat(),
            execution_time,
            1 if success else 0,
            error_message
        ))

        conn.commit()
        conn.close()

    def migrate_all(self, stop_on_error: bool = True) -> Dict:
        """
        执行所有待运行的迁移

        Args:
            stop_on_error: 遇到错误是否停止

        Returns:
            执行结果统计
        """
        pending = self.get_pending_migrations()

        if not pending:
            print("✅ 数据库已是最新版本，无需迁移")
            return {
                'total': 0,
                'success': 0,
                'failed': 0,
                'skipped': 0
            }

        print(f"📋 发现 {len(pending)} 个待执行的迁移")
        print()

        results = {
            'total': len(pending),
            'success': 0,
            'failed': 0,
            'skipped': 0
        }

        for migration in pending:
            success = self.run_migration(migration)

            if success:
                results['success'] += 1
            else:
                results['failed'] += 1

                if stop_on_error:
                    print()
                    print(f"⚠️  遇到错误，停止迁移")
                    results['skipped'] = len(pending) - results['success'] - results['failed']
                    break

        print()
        print("=" * 60)
        print(f"迁移完成: 总计 {results['total']}, "
              f"成功 {results['success']}, "
              f"失败 {results['failed']}, "
              f"跳过 {results['skipped']}")
        print("=" * 60)

        return results

    def get_migration_status(self) -> Dict:
        """获取迁移状态信息"""
        applied = self.get_applied_migrations()
        pending = self.get_pending_migrations()

        # 获取最后一次迁移信息
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT version, name, applied_at, execution_time_ms
            FROM schema_migrations
            WHERE success = 1
            ORDER BY applied_at DESC
            LIMIT 1
        """)

        last_migration = cursor.fetchone()
        conn.close()

        return {
            'database': self.db_path,
            'current_version': applied[-1] if applied else None,
            'applied_count': len(applied),
            'pending_count': len(pending),
            'last_migration': {
                'version': last_migration[0],
                'name': last_migration[1],
                'applied_at': last_migration[2],
                'execution_time_ms': last_migration[3]
            } if last_migration else None,
            'is_up_to_date': len(pending) == 0
        }

    def check_migration_needed(self) -> bool:
        """检查是否需要迁移"""
        return len(self.get_pending_migrations()) > 0


def main():
    """命令行入口"""
    # 默认数据库路径 - 修正路径
    db_path = os.path.join(os.path.dirname(__file__), "el.db")

    # 从环境变量读取
    if 'DATABASE_URL' in os.environ:
        db_url = os.environ['DATABASE_URL']
        if db_url.startswith('sqlite:///'):
            db_path = db_url.replace('sqlite:///', '')
        else:
            db_path = db_url

    # 如果数据库不存在，检查 data 目录
    if not os.path.exists(db_path):
        data_db_path = os.path.join(os.path.dirname(__file__), "data", "el.db")
        if os.path.exists(data_db_path):
            db_path = data_db_path

    if not os.path.exists(db_path):
        print(f"❌ 数据库文件不存在: {db_path}")
        print(f"   请确认数据库路径或设置 DATABASE_URL 环境变量")
        sys.exit(1)

    manager = MigrationManager(db_path)

    # 解析命令行参数
    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == 'status':
            # 显示迁移状态
            status = manager.get_migration_status()
            print("数据库迁移状态:")
            print(f"  数据库: {status['database']}")
            print(f"  当前版本: {status['current_version'] or '未迁移'}")
            print(f"  已应用: {status['applied_count']} 个迁移")
            print(f"  待执行: {status['pending_count']} 个迁移")

            if status['last_migration']:
                print(f"  最后迁移: {status['last_migration']['name']}")
                print(f"           于 {status['last_migration']['applied_at']}")

            if status['is_up_to_date']:
                print("\n✅ 数据库已是最新版本")
            else:
                print(f"\n⚠️  需要执行 {status['pending_count']} 个迁移")

        elif command == 'migrate':
            # 执行迁移
            results = manager.migrate_all()
            sys.exit(0 if results['failed'] == 0 else 1)

        elif command == 'check':
            # 检查是否需要迁移
            if manager.check_migration_needed():
                print("需要迁移")
                sys.exit(1)
            else:
                print("无需迁移")
                sys.exit(0)

        else:
            print(f"未知命令: {command}")
            print("可用命令: status, migrate, check")
            sys.exit(1)
    else:
        # 默认执行迁移
        results = manager.migrate_all()
        sys.exit(0 if results['failed'] == 0 else 1)


if __name__ == '__main__':
    main()
