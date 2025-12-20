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


async def _migrate_clear_rate_limit_state_v1(conn: AsyncConnection):
    """
    清空 rate_limit_state 表数据。

    原因：修复了 MySQL DATETIME 微秒四舍五入导致 checksum 验证失败的问题。
    旧数据的 checksum 是用错误的时间计算的，需要清空后重新生成。
    """
    logger.info("清空 rate_limit_state 表...")
    await conn.execute(text("DELETE FROM rate_limit_state"))
    logger.info("rate_limit_state 表已清空，将在下次访问时重新生成正确的 checksum。")


async def _rollback_to_original_types_v1(conn: AsyncConnection, db_type: str):
    """
    将数据库字段类型恢复到原始 ORM 模型定义

    目标:
    1. VARCHAR/TEXT 时间字段 → DATETIME
    2. BIGINT 数值字段 → INTEGER (仅恢复原本为 Integer 的字段)
    3. TEXT/LONGTEXT 字符串字段 → VARCHAR (根据原始长度)

    Args:
        conn: 数据库连接
        db_type: 数据库类型 ('mysql' 或 'postgresql')
    """
    logger.info(f"开始回退字段类型到原始定义 (数据库类型: {db_type})...")

    total_converted = 0

    # ========== 第 1 步: 时间字段 → DATETIME ==========
    logger.info("🕐 步骤 1/3: 转换时间字段 → DATETIME")

    TIMESTAMP_FIELDS = {
        'anime': ['created_at'],
        'anime_sources': ['last_refresh_latest_episode_at', 'created_at'],
        'episode': ['fetched_at'],
        'users': ['token_update', 'created_at'],
        'user_sessions': ['created_at', 'last_used_at', 'expires_at'],
        'cache_data': ['expires_at'],
        'api_tokens': ['created_at', 'expires_at', 'last_call_at'],
        'token_access_logs': ['access_time'],
        'ua_rules': ['created_at'],
        'bangumi_auth': ['expires_at', 'authorized_at'],
        'oauth_states': ['expires_at'],
        'scheduled_tasks': ['last_run_at', 'next_run_at'],
        'webhook_tasks': ['reception_time', 'execute_time'],
        'task_history': ['created_at', 'updated_at', 'finished_at'],
        'task_state_cache': ['created_at', 'updated_at'],
        'external_api_logs': ['access_time'],
        'rate_limit_state': ['last_reset_time'],
        'title_recognition': ['created_at', 'updated_at'],
        'media_servers': ['created_at', 'updated_at'],
        'media_items': ['created_at', 'updated_at'],
        'local_danmaku_items': ['created_at', 'updated_at'],
    }

    for table, fields in TIMESTAMP_FIELDS.items():
        for field in fields:
            try:
                if db_type == 'mysql':
                    sql = text(f"ALTER TABLE `{table}` MODIFY COLUMN `{field}` DATETIME")
                else:  # postgresql
                    sql = text(f'ALTER TABLE "{table}" ALTER COLUMN "{field}" TYPE TIMESTAMP USING "{field}"::timestamp')

                await conn.execute(sql)
                logger.info(f"  ✅ {table}.{field} → DATETIME")
                total_converted += 1
            except Exception as e:
                logger.warning(f"  ⚠️  {table}.{field} 转换失败: {e}")


    # ========== 第 2 步: 数值字段 BIGINT → INTEGER ==========
    logger.info("🔢 步骤 2/3: 转换数值字段 BIGINT → INTEGER")

    # 注意: 只包含原本为 Integer 的字段,不包括主键等 BigInteger 字段
    INTEGER_FIELDS = {
        'anime': ['season', 'episode_count', 'year'],
        'anime_sources': ['source_order', 'incremental_refresh_failures'],
        'episode': ['episode_index', 'comment_count'],
        'scrapers': ['display_order'],
        'metadata_sources': ['display_order'],
        'api_tokens': ['id', 'daily_call_limit', 'daily_call_count'],
        'token_access_logs': ['token_id'],
        'ua_rules': ['id'],
        'bangumi_auth': ['bangumi_user_id'],
        'tmdb_episode_mapping': ['tmdb_tv_id', 'tmdb_episode_id', 'tmdb_season_number',
                                 'tmdb_episode_number', 'custom_season_number',
                                 'custom_episode_number', 'absolute_episode_number'],
        'task_history': ['progress'],
        'external_api_logs': ['status_code'],
        'rate_limit_state': ['request_count'],
        'title_recognition': ['id'],
        'media_servers': ['id'],
        'media_items': ['season', 'episode', 'year'],
        'local_danmaku_items': ['season', 'episode', 'year'],
    }

    for table, fields in INTEGER_FIELDS.items():
        for field in fields:
            try:
                if db_type == 'mysql':
                    sql = text(f"ALTER TABLE `{table}` MODIFY COLUMN `{field}` INT")
                else:  # postgresql
                    sql = text(f'ALTER TABLE "{table}" ALTER COLUMN "{field}" TYPE INTEGER USING "{field}"::integer')

                await conn.execute(sql)
                logger.info(f"  ✅ {table}.{field} → INTEGER")
                total_converted += 1
            except Exception as e:
                logger.warning(f"  ⚠️  {table}.{field} 转换失败: {e}")


    # ========== 第 3 步: 字符串字段 TEXT/LONGTEXT → VARCHAR ==========
    logger.info("📝 步骤 3/3: 转换字符串字段 TEXT/LONGTEXT → VARCHAR")

    # VARCHAR 字段映射 {表名: {字段名: 长度}} - 最低 500
    VARCHAR_FIELDS = {
        'anime': {'title': 500, 'image_url': 512, 'local_image_path': 512},
        'anime_sources': {'provider_name': 500, 'media_id': 500},
        'episode': {'title': 500, 'provider_episode_id': 500, 'danmaku_file_path': 1024},
        'users': {'username': 500, 'hashed_password': 500},
        'user_sessions': {'jti': 500, 'ip_address': 500, 'user_agent': 500},
        'scrapers': {'provider_name': 500},
        'metadata_sources': {'provider_name': 500},
        'anime_metadata': {'tmdb_id': 500, 'tmdb_episode_group_id': 500, 'imdb_id': 500, 'tvdb_id': 500, 'douban_id': 500, 'bangumi_id': 500},
        'config': {'config_key': 500},
        'cache_data': {'cache_provider': 500, 'cache_key': 500},
        'api_tokens': {'name': 500, 'token': 500},
        'token_access_logs': {'ip_address': 500, 'status': 500, 'path': 512},
        'ua_rules': {'ua_string': 500},
        'bangumi_auth': {'nickname': 500, 'avatar_url': 512},
        'oauth_states': {'state_key': 500},
        'anime_aliases': {'name_en': 500, 'name_jp': 500, 'name_romaji': 500, 'alias_cn_1': 500, 'alias_cn_2': 500, 'alias_cn_3': 500},
        'tmdb_episode_mapping': {'tmdb_episode_group_id': 500},
        'scheduled_tasks': {'id': 500, 'name': 500, 'job_type': 500, 'cron_expression': 500},
        'webhook_tasks': {'webhook_source': 500, 'status': 500, 'unique_key': 500, 'task_title': 500},
        'task_history': {'id': 500, 'title': 500, 'status': 500, 'unique_key': 500, 'queue_type': 500, 'task_type': 500},
        'task_state_cache': {'task_id': 500, 'task_type': 500},
        'external_api_logs': {'ip_address': 500, 'endpoint': 500},
        'rate_limit_state': {'provider_name': 500, 'checksum': 500},
        'media_servers': {'name': 500, 'provider_name': 500, 'url': 512, 'api_token': 512},
        'media_items': {'media_id': 500, 'library_id': 500, 'title': 500, 'tmdb_id': 500, 'tvdb_id': 500, 'imdb_id': 500, 'poster_url': 1024},
        'local_danmaku_items': {'file_path': 1024, 'title': 512, 'tmdb_id': 500, 'tvdb_id': 500, 'imdb_id': 500, 'poster_url': 1024, 'nfo_path': 1024},
    }

    for table, fields_dict in VARCHAR_FIELDS.items():
        for field, length in fields_dict.items():
            try:
                if db_type == 'mysql':
                    sql = text(f"ALTER TABLE `{table}` MODIFY COLUMN `{field}` VARCHAR({length})")
                else:  # postgresql
                    sql = text(f'ALTER TABLE "{table}" ALTER COLUMN "{field}" TYPE VARCHAR({length})')

                await conn.execute(sql)
                logger.info(f"  ✅ {table}.{field} → VARCHAR({length})")
                total_converted += 1
            except Exception as e:
                logger.warning(f"  ⚠️  {table}.{field} 转换失败: {e}")


    # ========== 第 4 步: LONGTEXT → MEDIUMTEXT/TEXT ==========
    logger.info("📦 步骤 4/4: 转换 LONGTEXT → MEDIUMTEXT/TEXT")

    # 这些字段在 ORM 中是 TEXT().with_variant(MEDIUMTEXT, "mysql")
    # 数据库中当前是 LONGTEXT，需要转换为 MEDIUMTEXT (MySQL) 或 TEXT (PostgreSQL)
    MEDIUMTEXT_FIELDS = {
        'config': ['config_value'],
        'cache_data': ['cache_value'],
        'webhook_tasks': ['payload'],
        'task_history': ['description', 'task_parameters'],
        'task_state_cache': ['task_parameters'],
        'external_api_logs': ['message'],
        'title_recognition': ['content'],
    }

    for table, fields in MEDIUMTEXT_FIELDS.items():
        for field in fields:
            try:
                if db_type == 'mysql':
                    sql = text(f"ALTER TABLE `{table}` MODIFY COLUMN `{field}` MEDIUMTEXT")
                else:  # postgresql
                    sql = text(f'ALTER TABLE "{table}" ALTER COLUMN "{field}" TYPE TEXT')

                await conn.execute(sql)
                field_type = "MEDIUMTEXT" if db_type == 'mysql' else "TEXT"
                logger.info(f"  ✅ {table}.{field} → {field_type}")
                total_converted += 1
            except Exception as e:
                logger.warning(f"  ⚠️  {table}.{field} 转换失败: {e}")

    logger.info(f"\n✅ 回退迁移完成! 共转换 {total_converted} 个字段")
    logger.info("   请重启应用验证字段类型是否恢复正常")


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
        ("migrate_clear_rate_limit_state_v1", _migrate_clear_rate_limit_state_v1, ()),
        ("rollback_to_original_types_v1", _rollback_to_original_types_v1, (db_type,)),
    ]

    for migration_id, migration_func, args in migrations:
        await _run_migration(conn, migration_id, migration_func, *args)

    logger.info("所有数据库迁移检查完成。")
