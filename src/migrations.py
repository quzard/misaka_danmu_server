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


async def _migrate_to_text_and_bigint_v1(conn: AsyncConnection, db_type: str):
    """
    全量类型迁移：
    1. 所有时间字段 → MySQL: LONGTEXT, PostgreSQL: TEXT (格式: YYYY-MM-DD HH:MM:SS)
    2. 所有数值字段 → MySQL: BIGINT, PostgreSQL: int8
    3. 所有字符字段 → MySQL: LONGTEXT, PostgreSQL: TEXT
    4. 布尔字段保持不变

    PostgreSQL 特殊处理：先截断微秒部分再转换类型
    """
    logger.info(f"开始执行全量类型迁移 (数据库类型: {db_type})...")

    # ========== 配置：所有需要迁移的字段 ==========

    # 时间字段 {表名: [字段列表]}
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

    # Integer 字段 {表名: [字段列表]}
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

    # 字符串字段 {表名: [字段列表]}
    STRING_FIELDS = {
        'anime': ['title', 'image_url', 'local_image_path'],
        'anime_sources': ['provider_name', 'media_id'],
        'episode': ['title', 'provider_episode_id', 'source_url', 'danmaku_file_path'],
        'users': ['username', 'hashed_password', 'token'],
        'user_sessions': ['jti', 'ip_address', 'user_agent'],
        'scrapers': ['provider_name'],
        'metadata_sources': ['provider_name'],
        'anime_metadata': ['tmdb_id', 'tmdb_episode_group_id', 'imdb_id', 'tvdb_id', 'douban_id', 'bangumi_id'],
        'config': ['config_key', 'config_value', 'description'],
        'cache_data': ['cache_provider', 'cache_key', 'cache_value'],
        'api_tokens': ['name', 'token'],
        'token_access_logs': ['ip_address', 'user_agent', 'status', 'path'],
        'ua_rules': ['ua_string'],
        'bangumi_auth': ['nickname', 'avatar_url', 'access_token', 'refresh_token'],
        'oauth_states': ['state_key'],
        'anime_aliases': ['name_en', 'name_jp', 'name_romaji', 'alias_cn_1', 'alias_cn_2', 'alias_cn_3'],
        'tmdb_episode_mapping': ['tmdb_episode_group_id'],
        'scheduled_tasks': ['id', 'name', 'job_type', 'cron_expression'],
        'webhook_tasks': ['webhook_source', 'status', 'payload', 'unique_key', 'task_title'],
        'task_history': ['id', 'scheduled_task_id', 'title', 'status', 'description', 'unique_key', 'queue_type', 'task_type', 'task_parameters'],
        'task_state_cache': ['task_id', 'task_type', 'task_parameters'],
        'external_api_logs': ['ip_address', 'endpoint', 'message'],
        'rate_limit_state': ['provider_name', 'checksum'],
        'title_recognition': ['content'],
        'media_servers': ['name', 'provider_name', 'url', 'api_token', 'selected_libraries', 'filter_rules'],
        'media_items': ['media_id', 'library_id', 'title', 'tmdb_id', 'tvdb_id', 'imdb_id', 'poster_url'],
        'local_danmaku_items': ['file_path', 'title', 'tmdb_id', 'tvdb_id', 'imdb_id', 'poster_url', 'nfo_path'],
    }

    migrated_count = {'timestamp': 0, 'integer': 0, 'string': 0}

    # ========== Step 1: PostgreSQL 时间字段截断微秒 ==========
    if db_type == 'postgresql':
        logger.info("📝 PostgreSQL: 截断时间字段的微秒部分...")
        for table, fields in TIMESTAMP_FIELDS.items():
            for field in fields:
                try:
                    # 使用 TO_CHAR 格式化为 YYYY-MM-DD HH24:MI:SS，去掉微秒
                    sql = text(f"""
                        UPDATE {table}
                        SET {field} = TO_CHAR({field}, 'YYYY-MM-DD HH24:MI:SS')
                        WHERE {field} IS NOT NULL AND {field}::text LIKE '%.%'
                    """)
                    result = await conn.execute(sql)
                    if result.rowcount > 0:
                        logger.info(f"  ✅ {table}.{field} - 更新 {result.rowcount} 行")
                except Exception as e:
                    logger.warning(f"  ⚠️  {table}.{field} 截断失败: {e}")
        logger.info("")

    # ========== Step 2: 修改时间字段类型 ==========
    logger.info("🕐 修改时间字段类型...")
    # 修正：MySQL 使用 VARCHAR(50)，PostgreSQL 使用 TEXT
    # 原因：MySQL 不允许 LONGTEXT 字段有索引，而许多时间字段有索引
    time_type = 'VARCHAR(50)' if db_type == 'mysql' else 'TEXT'

    for table, fields in TIMESTAMP_FIELDS.items():
        for field in fields:
            try:
                if db_type == 'mysql':
                    sql = text(f"ALTER TABLE `{table}` MODIFY COLUMN `{field}` {time_type}")
                else:  # postgresql
                    sql = text(f'ALTER TABLE "{table}" ALTER COLUMN "{field}" TYPE {time_type} USING {field}::text')
                await conn.execute(sql)
                logger.info(f"  ✅ {table}.{field} → {time_type}")
                migrated_count['timestamp'] += 1
            except Exception as e:
                logger.warning(f"  ⚠️  {table}.{field} 迁移失败: {e}")
    logger.info(f"时间字段迁移完成: {migrated_count['timestamp']} 个字段\n")

    # ========== Step 3: 修改数值字段类型 ==========
    logger.info("🔢 修改数值字段类型...")
    bigint_type = 'BIGINT' if db_type == 'mysql' else 'BIGINT'

    for table, fields in INTEGER_FIELDS.items():
        for field in fields:
            try:
                if db_type == 'mysql':
                    sql = text(f"ALTER TABLE `{table}` MODIFY COLUMN `{field}` {bigint_type}")
                else:  # postgresql
                    sql = text(f'ALTER TABLE "{table}" ALTER COLUMN "{field}" TYPE {bigint_type} USING {field}::bigint')
                await conn.execute(sql)
                logger.info(f"  ✅ {table}.{field} → {bigint_type}")
                migrated_count['integer'] += 1
            except Exception as e:
                logger.warning(f"  ⚠️  {table}.{field} 迁移失败: {e}")
    logger.info(f"数值字段迁移完成: {migrated_count['integer']} 个字段\n")

    # ========== Step 4: 修改字符串字段类型 ==========
    logger.info("📝 修改字符串字段类型...")
    # 新策略：
    # - MySQL: 普通字段用 TEXT (64KB)，超大字段用 LONGTEXT (4GB)
    # - PostgreSQL: 统一使用 TEXT
    #
    # 超大字段列表（需要 LONGTEXT）
    LONGTEXT_FIELDS = {
        'config': ['config_value'],
        'cache_data': ['cache_value'],
        'webhook_tasks': ['payload'],
        'task_history': ['description', 'task_parameters'],
        'task_state_cache': ['task_parameters'],
        'external_api_logs': ['message'],
        'title_recognition': ['content'],
    }

    for table, fields in STRING_FIELDS.items():
        for field in fields:
            try:
                # 判断是否为超大字段
                is_longtext = table in LONGTEXT_FIELDS and field in LONGTEXT_FIELDS.get(table, [])

                if db_type == 'mysql':
                    field_type = 'LONGTEXT' if is_longtext else 'TEXT'
                    sql = text(f"ALTER TABLE `{table}` MODIFY COLUMN `{field}` {field_type}")
                else:  # postgresql
                    sql = text(f'ALTER TABLE "{table}" ALTER COLUMN "{field}" TYPE TEXT')
                    field_type = 'TEXT'

                await conn.execute(sql)
                logger.info(f"  ✅ {table}.{field} → {field_type}")
                migrated_count['string'] += 1
            except Exception as e:
                logger.warning(f"  ⚠️  {table}.{field} 迁移失败: {e}")
    logger.info(f"字符串字段迁移完成: {migrated_count['string']} 个字段\n")

    # ========== 汇总 ==========
    total = sum(migrated_count.values())
    logger.info(f"🎉 全量类型迁移完成！")
    logger.info(f"   - 时间字段: {migrated_count['timestamp']} 个")
    logger.info(f"   - 数值字段: {migrated_count['integer']} 个")
    logger.info(f"   - 字符字段: {migrated_count['string']} 个")
    logger.info(f"   - 总计: {total} 个字段已迁移")


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
        ("migrate_to_text_and_bigint_v1", _migrate_to_text_and_bigint_v1, (db_type,)),
    ]

    for migration_id, migration_func, args in migrations:
        await _run_migration(conn, migration_id, migration_func, *args)

    logger.info("所有数据库迁移检查完成。")
