"""
数据库备份定时任务
使用 JSON 格式导出数据，支持跨数据库（MySQL/PostgreSQL）兼容
"""
import gzip
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Dict, Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, inspect
from sqlalchemy.orm import selectinload

from .. import crud, orm_models
from ..config import settings
from ..timezone import get_now
from .base import BaseJob
from ..task_manager import TaskSuccess

logger = logging.getLogger(__name__)

# 默认备份路径
DEFAULT_BACKUP_PATH = "/app/config/sql_backup"
DEFAULT_RETENTION_COUNT = 5

# 需要备份的表（按依赖顺序排列，被依赖的表在前）
BACKUP_TABLES = [
    ("users", orm_models.User),
    ("anime", orm_models.Anime),
    ("anime_sources", orm_models.AnimeSource),
    ("episode", orm_models.Episode),
    ("anime_metadata", orm_models.AnimeMetadata),
    ("anime_aliases", orm_models.AnimeAlias),
    ("config", orm_models.Config),
    ("media_servers", orm_models.MediaServer),
    ("scheduled_tasks", orm_models.ScheduledTask),
    ("api_tokens", orm_models.ApiToken),
]


def get_column_mapping(model_class) -> Dict[str, str]:
    """获取数据库列名到 Python 属性名的映射"""
    mapper = inspect(model_class)
    mapping = {}
    for attr_name, column_prop in mapper.column_attrs.items():
        # attr_name 是 Python 属性名
        # column_prop.columns[0].name 是数据库列名
        for column in column_prop.columns:
            mapping[column.name] = attr_name
    return mapping


def model_to_dict(obj) -> Dict[str, Any]:
    """将 ORM 对象转换为字典，使用数据库列名作为键"""
    result = {}
    mapper = inspect(obj.__class__)
    for column in mapper.columns:
        # 获取 Python 属性名（用于 getattr）
        attr_name = column.key
        # 获取数据库列名（用于 JSON 键）
        db_column_name = column.name

        try:
            value = getattr(obj, attr_name)
            # 处理 datetime 类型
            if isinstance(value, datetime):
                value = value.isoformat()
            result[db_column_name] = value
        except AttributeError:
            # 如果属性不存在，跳过
            logger.debug(f"属性 {attr_name} 不存在于 {obj.__class__.__name__}")
            continue
    return result


async def get_backup_path(session: AsyncSession) -> Path:
    """获取备份路径"""
    path_str = await crud.get_config_value(session, "backupPath", DEFAULT_BACKUP_PATH)
    return Path(path_str)


async def get_retention_count(session: AsyncSession) -> int:
    """获取备份保留数量"""
    count_str = await crud.get_config_value(session, "backupRetentionCount", str(DEFAULT_RETENTION_COUNT))
    try:
        return int(count_str)
    except (ValueError, TypeError):
        return DEFAULT_RETENTION_COUNT


async def create_backup(session: AsyncSession, progress_callback: Optional[Callable] = None) -> Dict[str, Any]:
    """
    创建数据库备份
    返回备份信息字典
    """
    backup_path = await get_backup_path(session)
    backup_path.mkdir(parents=True, exist_ok=True)
    
    # 生成备份文件名
    timestamp = get_now().strftime("%Y%m%d_%H%M%S")
    filename = f"danmuapi_backup_{timestamp}.json.gz"
    filepath = backup_path / filename
    
    # 构建备份数据
    backup_data = {
        "metadata": {
            "version": "1.0",
            "source_db_type": settings.database.type.lower(),
            "created_at": get_now().isoformat(),
            "tables": [name for name, _ in BACKUP_TABLES],
        },
        "data": {}
    }
    
    total_tables = len(BACKUP_TABLES)
    total_records = 0
    
    for idx, (table_name, model_class) in enumerate(BACKUP_TABLES):
        if progress_callback:
            progress = int((idx / total_tables) * 80)
            await progress_callback(progress, f"正在导出表: {table_name}...")
        
        try:
            stmt = select(model_class)
            result = await session.execute(stmt)
            records = result.scalars().all()
            
            backup_data["data"][table_name] = [model_to_dict(r) for r in records]
            total_records += len(records)
            logger.info(f"导出表 {table_name}: {len(records)} 条记录")
        except Exception as e:
            logger.warning(f"导出表 {table_name} 失败: {e}")
            backup_data["data"][table_name] = []
    
    # 写入压缩文件
    if progress_callback:
        await progress_callback(85, "正在压缩备份文件...")
    
    with gzip.open(filepath, 'wt', encoding='utf-8') as f:
        json.dump(backup_data, f, ensure_ascii=False, indent=2)
    
    file_size = filepath.stat().st_size
    
    # 清理旧备份
    if progress_callback:
        await progress_callback(90, "正在清理旧备份...")
    
    retention_count = await get_retention_count(session)
    await cleanup_old_backups(backup_path, retention_count)
    
    return {
        "filename": filename,
        "filepath": str(filepath),
        "size": file_size,
        "records": total_records,
        "created_at": get_now().isoformat(),
    }


async def cleanup_old_backups(backup_path: Path, retention_count: int):
    """清理旧备份，只保留最近的 N 个"""
    backup_files = sorted(
        [f for f in backup_path.glob("danmuapi_backup_*.json.gz")],
        key=lambda x: x.stat().st_mtime,
        reverse=True
    )

    for old_file in backup_files[retention_count:]:
        try:
            old_file.unlink()
            logger.info(f"删除旧备份: {old_file.name}")
        except Exception as e:
            logger.error(f"删除旧备份失败 {old_file.name}: {e}")


async def list_backups(session: AsyncSession) -> List[Dict[str, Any]]:
    """列出所有备份文件"""
    backup_path = await get_backup_path(session)

    if not backup_path.exists():
        return []

    backups = []
    for filepath in backup_path.glob("danmuapi_backup_*.json.gz"):
        try:
            stat = filepath.stat()
            # 从文件名解析时间和数据库类型
            # 尝试读取元数据
            db_type = None
            try:
                with gzip.open(filepath, 'rt', encoding='utf-8') as f:
                    # 只读取前面一小部分来获取元数据
                    content = f.read(500)
                    if '"source_db_type"' in content:
                        import re
                        match = re.search(r'"source_db_type"\s*:\s*"(\w+)"', content)
                        if match:
                            db_type = match.group(1)
            except:
                pass

            backups.append({
                "filename": filepath.name,
                "size": stat.st_size,
                "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "db_type": db_type,
            })
        except Exception as e:
            logger.error(f"读取备份文件信息失败 {filepath.name}: {e}")

    # 按创建时间倒序排列
    backups.sort(key=lambda x: x["created_at"], reverse=True)
    return backups


async def delete_backup(session: AsyncSession, filename: str) -> bool:
    """删除指定备份文件"""
    backup_path = await get_backup_path(session)
    filepath = backup_path / filename

    # 安全检查：确保文件名合法
    if not filename.startswith("danmuapi_backup_") or not filename.endswith(".json.gz"):
        raise ValueError("无效的备份文件名")

    if not filepath.exists():
        raise FileNotFoundError(f"备份文件不存在: {filename}")

    filepath.unlink()
    logger.info(f"删除备份文件: {filename}")
    return True


async def restore_backup(session: AsyncSession, filename: str, progress_callback: Optional[Callable] = None) -> Dict[str, Any]:
    """
    从备份还原数据库
    警告：此操作会清空现有数据！
    """
    from sqlalchemy import delete

    backup_path = await get_backup_path(session)
    filepath = backup_path / filename

    if not filepath.exists():
        raise FileNotFoundError(f"备份文件不存在: {filename}")

    # 读取备份数据
    if progress_callback:
        await progress_callback(5, "正在读取备份文件...")

    with gzip.open(filepath, 'rt', encoding='utf-8') as f:
        backup_data = json.load(f)

    metadata = backup_data.get("metadata", {})
    data = backup_data.get("data", {})

    if progress_callback:
        await progress_callback(10, "正在验证备份数据...")

    # 按依赖关系的逆序删除数据（先删除有外键依赖的表）
    tables_reversed = list(reversed(BACKUP_TABLES))
    total_tables = len(tables_reversed)

    for idx, (table_name, model_class) in enumerate(tables_reversed):
        if progress_callback:
            progress = 10 + int((idx / total_tables) * 40)
            await progress_callback(progress, f"正在清空表: {table_name}...")

        try:
            await session.execute(delete(model_class))
        except Exception as e:
            logger.warning(f"清空表 {table_name} 失败: {e}")

    await session.flush()

    # 按依赖顺序插入数据
    total_records = 0
    now = get_now()

    for idx, (table_name, model_class) in enumerate(BACKUP_TABLES):
        if progress_callback:
            progress = 50 + int((idx / total_tables) * 45)
            await progress_callback(progress, f"正在还原表: {table_name}...")

        records = data.get(table_name, [])
        if not records:
            continue

        try:
            # 获取数据库列名到 Python 属性名的映射
            column_mapping = get_column_mapping(model_class)

            # 获取模型的所有有效 Python 属性名
            mapper = inspect(model_class)
            valid_attrs = set(column_mapping.values())

            # 存储 NOT NULL 字段信息
            # not_null_datetime_attrs: {Python属性名: 数据库列名} - 日期时间类型
            # not_null_string_attrs: {Python属性名: 数据库列名} - 字符串类型
            not_null_datetime_attrs = {}
            not_null_string_attrs = {}
            primary_key_attrs = set()

            # 遍历 column_attrs 获取正确的属性名和列信息
            for attr_name, column_prop in mapper.column_attrs.items():
                for column in column_prop.columns:
                    # 获取主键字段
                    if column.primary_key:
                        primary_key_attrs.add(attr_name)

                    # 检查是否为 NOT NULL 字段（非主键）
                    if not column.nullable and not column.primary_key:
                        col_type_class = type(column.type).__name__.upper()
                        col_type = str(column.type).upper()

                        if 'DATETIME' in col_type or 'TIMESTAMP' in col_type or 'NAIVEDATETIME' in col_type_class:
                            not_null_datetime_attrs[attr_name] = column.name
                        elif 'VARCHAR' in col_type or 'STRING' in col_type or 'TEXT' in col_type:
                            not_null_string_attrs[attr_name] = column.name

            if not_null_datetime_attrs:
                logger.debug(f"表 {table_name} 的 NOT NULL 日期时间属性: {not_null_datetime_attrs}")
            if not_null_string_attrs:
                logger.debug(f"表 {table_name} 的 NOT NULL 字符串属性: {not_null_string_attrs}")

            for record in records:
                # 将数据库列名转换为 Python 属性名
                converted_record = {}
                for db_col_name, value in record.items():
                    # 获取对应的 Python 属性名
                    attr_name = column_mapping.get(db_col_name, db_col_name)

                    # 只添加模型中存在的属性，忽略无效字段
                    if attr_name not in valid_attrs:
                        logger.debug(f"忽略无效字段: {db_col_name} -> {attr_name}")
                        continue

                    # 处理 datetime 字段
                    if isinstance(value, str) and 'T' in value:
                        try:
                            value = datetime.fromisoformat(value)
                        except:
                            pass

                    converted_record[attr_name] = value

                # 为 NOT NULL 的日期时间字段提供默认值
                # 这样可以处理从 MySQL 备份还原到 PostgreSQL 时的 NOT NULL 约束问题
                for attr_name, db_col_name in not_null_datetime_attrs.items():
                    current_value = converted_record.get(attr_name)
                    if current_value is None:
                        converted_record[attr_name] = now
                        logger.info(f"为 {table_name}.{attr_name} (db: {db_col_name}) 设置默认时间: {now}")

                # 为 NOT NULL 的字符串字段提供默认值
                for attr_name, db_col_name in not_null_string_attrs.items():
                    current_value = converted_record.get(attr_name)
                    if current_value is None:
                        # 尝试从字段名推断默认值
                        default_value = ""
                        attr_lower = attr_name.lower()
                        if 'provider' in attr_lower:
                            # 对于 provider 类型字段，尝试从其他字段推断
                            if 'name' in converted_record:
                                name_val = converted_record.get('name', '')
                                if name_val:
                                    default_value = str(name_val).lower()
                        converted_record[attr_name] = default_value
                        logger.info(f"为 {table_name}.{attr_name} (db: {db_col_name}) 设置默认值: '{default_value}'")

                # 检查主键字段是否为空，如果为空则跳过该记录
                skip_record = False
                for pk_attr in primary_key_attrs:
                    if pk_attr not in converted_record or converted_record.get(pk_attr) is None:
                        logger.warning(f"跳过记录: {table_name} 主键字段 {pk_attr} 为空")
                        skip_record = True
                        break

                if skip_record:
                    continue

                obj = model_class(**converted_record)
                session.add(obj)

            total_records += len(records)
            logger.info(f"还原表 {table_name}: {len(records)} 条记录")
        except Exception as e:
            logger.error(f"还原表 {table_name} 失败: {e}")
            raise

    await session.flush()

    return {
        "filename": filename,
        "records": total_records,
        "source_db_type": metadata.get("source_db_type"),
        "backup_created_at": metadata.get("created_at"),
    }


class DatabaseBackupJob(BaseJob):
    """
    数据库备份定时任务
    """
    job_type = "databaseBackup"
    job_name = "数据库备份"
    description = "定期备份数据库数据为 JSON 格式，支持跨数据库（MySQL/PostgreSQL）还原。"

    async def run(self, session: AsyncSession, progress_callback: Callable):
        """
        执行数据库备份任务
        """
        self.logger.info(f"开始执行 [{self.job_name}] 定时任务...")

        await progress_callback(0, "开始备份数据库...")

        try:
            result = await create_backup(session, progress_callback)

            await progress_callback(100, "备份完成")

            size_mb = result['size'] / (1024 * 1024)
            final_message = f"数据库备份完成。文件: {result['filename']}, 大小: {size_mb:.2f} MB, 记录数: {result['records']}"
            self.logger.info(final_message)
            raise TaskSuccess(final_message)

        except TaskSuccess:
            raise
        except Exception as e:
            self.logger.error(f"数据库备份失败: {e}", exc_info=True)
            raise

