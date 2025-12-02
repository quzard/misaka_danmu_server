"""
数据库迁移模块

此模块用于执行一次性的数据库迁移任务。
迁移任务通过标志位机制确保只执行一次。

注意：简单的添加字段和类型扩展现在由 db_maintainer.py 自动处理，
此模块仅用于需要数据转换、重命名、填充等复杂操作的迁移。
"""

import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

logger = logging.getLogger(__name__)


async def _check_migration_flag(conn: AsyncConnection, migration_id: str) -> bool:
    """检查迁移是否已执行过。"""
    check_flag_sql = text("SELECT 1 FROM config WHERE config_key = :key")
    flag_exists = (await conn.execute(check_flag_sql, {"key": migration_id})).scalar_one_or_none() is not None
    if flag_exists:
        logger.debug(f"迁移 '{migration_id}' 已执行过，跳过。")
        return True
    return False


async def _set_migration_flag(conn: AsyncConnection, migration_id: str):
    """设置迁移完成的标志位。"""
    description = f"标志位，表示已完成数据库迁移: {migration_id}"
    if conn.dialect.name == 'mysql':
        stmt = text("INSERT INTO config (config_key, config_value, description) VALUES (:key, 'true', :desc) ON DUPLICATE KEY UPDATE config_value = 'true'")
    else:  # postgresql
        stmt = text("INSERT INTO config (config_key, config_value, description) VALUES (:key, 'true', :desc) ON CONFLICT (config_key) DO UPDATE SET config_value = 'true'")
    await conn.execute(stmt, {"key": migration_id, "desc": description})
    logger.info(f"成功设置迁移标志 '{migration_id}'。")


async def _run_migration(conn: AsyncConnection, migration_id: str, migration_func, *args):
    """一个包装器，用于运行单个迁移任务并处理标志位。"""
    if not await _check_migration_flag(conn, migration_id):
        logger.warning(f"将执行一次性数据库迁移 '{migration_id}'...")
        try:
            await migration_func(conn, *args)
            await _set_migration_flag(conn, migration_id)
            logger.info(f"迁移任务 '{migration_id}' 成功完成。")
        except Exception as e:
            logger.error(f"执行迁移 '{migration_id}' 时发生错误: {e}", exc_info=True)
            raise


# async def _migrate_clear_rate_limit_state_v1(conn: AsyncConnection):
#     """
#     清空 rate_limit_state 表数据。

#     原因：修复了 MySQL DATETIME 微秒四舍五入导致 checksum 验证失败的问题。
#     旧数据的 checksum 是用错误的时间计算的，需要清空后重新生成。
#     """
#     logger.info("清空 rate_limit_state 表...")
#     await conn.execute(text("DELETE FROM rate_limit_state"))
#     logger.info("rate_limit_state 表已清空，将在下次访问时重新生成正确的 checksum。")


async def run_migrations(conn: AsyncConnection, db_type: str, db_name: str):
    """
    按顺序执行所有数据库架构迁移。

    注意：简单的添加字段和类型扩展现在由 db_maintainer.py 自动处理。
    此处仅保留需要数据转换的复杂迁移任务。
    """
    logger.info("开始执行数据库迁移检查...")

    # 迁移任务列表
    migrations = [
        # 格式: ("migration_id", migration_func, (args,))
 #       ("migrate_clear_rate_limit_state_v1", _migrate_clear_rate_limit_state_v1, ()),
    ]

    for migration_id, migration_func, args in migrations:
        await _run_migration(conn, migration_id, migration_func, *args)

    logger.info("所有数据库迁移检查完成。")
