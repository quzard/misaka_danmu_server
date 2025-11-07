import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

logger = logging.getLogger(__name__)

async def _check_migration_flag(conn: AsyncConnection, migration_id: str) -> bool:
    """检查迁移是否已执行过。"""
    check_flag_sql = text("SELECT 1 FROM config WHERE config_key = :key")
    flag_exists = (await conn.execute(check_flag_sql, {"key": migration_id})).scalar_one_or_none() is not None
    if flag_exists:
        logger.info(f"迁移 '{migration_id}' 已执行过，跳过。")
        return True
    return False

async def _set_migration_flag(conn: AsyncConnection, migration_id: str):
    """设置迁移完成的标志位。"""
    description = f"标志位，表示已完成数据库迁移: {migration_id}"
    if conn.dialect.name == 'mysql':
        stmt = text("INSERT INTO config (config_key, config_value, description) VALUES (:key, 'true', :desc) ON DUPLICATE KEY UPDATE config_value = 'true'")
    else: # postgresql
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
            # 向上抛出异常以中断应用启动，防止在不完整的数据库结构上运行
            raise

async def _migrate_utc_to_local_datetime_task(conn: AsyncConnection, db_type: str):
    """迁移任务: 将可能被错误存储为UTC时间的datetime字段，转换为服务器的本地时间。"""
    tables_and_columns = {
        "anime": ["created_at"], "anime_sources": ["created_at"], "episode": ["fetched_at"],
        "users": ["token_update", "created_at"], "api_tokens": ["created_at", "expires_at"],
        "token_access_logs": ["access_time"], "ua_rules": ["created_at"],
        "bangumi_auth": ["expires_at", "authorized_at"], "oauth_states": ["expires_at"],
        "scheduled_tasks": ["last_run_at", "next_run_at"],
        "task_history": ["created_at", "updated_at", "finished_at"],
        "external_api_logs": ["access_time"], "rate_limit_state": ["last_reset_time"],
        "cache_data": ["expires_at"],
    }
    for table, columns in tables_and_columns.items():
        for column in columns:
            logger.info(f"正在迁移 {table}.{column}...")
            if db_type == "mysql":
                update_sql = text(f"ALTER TABLE `{table}` MODIFY COLUMN `{column}` DATETIME;")
            else: # postgresql
                update_sql = text(f'ALTER TABLE "{table}" ALTER COLUMN "{column}" TYPE TIMESTAMP WITHOUT TIME ZONE USING "{column}"::timestamp;')
            await conn.execute(update_sql)

async def _migrate_add_source_order_task(conn: AsyncConnection, db_type: str, db_name: str):
    """迁移任务: 确保 anime_sources 表有持久化的 source_order 字段。"""
    if db_type == "mysql":
        check_column_sql = text(f"SELECT 1 FROM information_schema.columns WHERE table_schema = '{db_name}' AND table_name = 'anime_sources' AND column_name = 'source_order'")
        add_column_sql = text("ALTER TABLE anime_sources ADD COLUMN `source_order` INT NULL")
    else: # postgresql
        check_column_sql = text("SELECT 1 FROM information_schema.columns WHERE table_name = 'anime_sources' AND column_name = 'source_order'")
        add_column_sql = text('ALTER TABLE anime_sources ADD COLUMN "source_order" INT NULL')

    if not (await conn.execute(check_column_sql)).scalar_one_or_none():
        await conn.execute(add_column_sql)
        distinct_anime_ids = (await conn.execute(text("SELECT DISTINCT anime_id FROM anime_sources"))).scalars().all()
        for anime_id in distinct_anime_ids:
            sources_ids = (await conn.execute(text("SELECT id FROM anime_sources WHERE anime_id = :anime_id ORDER BY id"), {"anime_id": anime_id})).scalars().all()
            for i, source_id in enumerate(sources_ids):
                await conn.execute(text("UPDATE anime_sources SET source_order = :order WHERE id = :source_id"), {"order": i + 1, "source_id": source_id})
        if db_type == "mysql":
            await conn.execute(text("ALTER TABLE anime_sources MODIFY COLUMN `source_order` INT NOT NULL"))
        else: # postgresql
            await conn.execute(text('ALTER TABLE anime_sources ALTER COLUMN "source_order" SET NOT NULL'))

    if db_type == "mysql":
        check_constraint_sql = text(f"SELECT 1 FROM information_schema.table_constraints WHERE table_schema = '{db_name}' AND table_name = 'anime_sources' AND constraint_name = 'idx_anime_source_order_unique'")
        add_constraint_sql = text("ALTER TABLE anime_sources ADD CONSTRAINT idx_anime_source_order_unique UNIQUE (anime_id, source_order)")
    else: # postgresql
        check_constraint_sql = text("SELECT 1 FROM pg_constraint WHERE conname = 'idx_anime_source_order_unique'")
        add_constraint_sql = text('ALTER TABLE anime_sources ADD CONSTRAINT idx_anime_source_order_unique UNIQUE (anime_id, source_order)')

    if not (await conn.execute(check_constraint_sql)).scalar_one_or_none():
        await conn.execute(add_constraint_sql)

async def _migrate_add_danmaku_file_path_task(conn: AsyncConnection, db_type: str):
    """迁移任务: 确保 episode 表有 danmaku_file_path 字段。"""
    if db_type == "mysql":
        check_column_sql = text("SELECT 1 FROM information_schema.columns WHERE table_name = 'episode' AND column_name = 'danmaku_file_path'")
        add_column_sql = text("ALTER TABLE episode ADD COLUMN `danmaku_file_path` VARCHAR(1024) NULL DEFAULT NULL")
    else: # postgresql
        check_column_sql = text("SELECT 1 FROM information_schema.columns WHERE table_name = 'episode' AND column_name = 'danmaku_file_path'")
        add_column_sql = text('ALTER TABLE episode ADD COLUMN "danmaku_file_path" VARCHAR(1024) NULL DEFAULT NULL')

    if not (await conn.execute(check_column_sql)).scalar_one_or_none():
        await conn.execute(add_column_sql)

async def _migrate_text_to_mediumtext_task(conn: AsyncConnection, db_type: str, db_name: str):
    """迁移任务: 将多个表中可能存在的 TEXT 字段修改为 MEDIUMTEXT (仅MySQL)。"""
    if db_type != "mysql":
        return
    tables_and_columns = {
        "cache_data": "cache_value", "config": "config_value",
        "task_history": "description", "external_api_logs": "message"
    }
    for table, column in tables_and_columns.items():
        check_sql = text(f"SELECT DATA_TYPE FROM information_schema.columns WHERE table_schema = '{db_name}' AND table_name = '{table}' AND column_name = '{column}'")
        current_type = (await conn.execute(check_sql)).scalar_one_or_none()
        if current_type and current_type.lower() == 'text':
            await conn.execute(text(f"ALTER TABLE {table} MODIFY COLUMN `{column}` MEDIUMTEXT"))

async def _migrate_add_source_url_to_episode_task(conn: AsyncConnection, db_type: str, db_name: str):
    """迁移任务: 确保 episode 表有 source_url 字段，并处理旧的命名。"""
    old_name, new_name, table = "sourceUrl", "source_url", "episode"
    if db_type == "mysql":
        check_old_sql = text(f"SELECT 1 FROM information_schema.columns WHERE table_schema = '{db_name}' AND table_name = '{table}' AND column_name = '{old_name}'")
        check_new_sql = text(f"SELECT 1 FROM information_schema.columns WHERE table_schema = '{db_name}' AND table_name = '{table}' AND column_name = '{new_name}'")
        rename_sql = text(f"ALTER TABLE `{table}` CHANGE COLUMN `{old_name}` `{new_name}` TEXT NULL")
        add_sql = text(f"ALTER TABLE `{table}` ADD COLUMN `{new_name}` TEXT NULL")
    else: # postgresql
        check_old_sql = text(f"SELECT 1 FROM information_schema.columns WHERE table_name = '{table}' AND column_name = '{old_name}'")
        check_new_sql = text(f"SELECT 1 FROM information_schema.columns WHERE table_name = '{table}' AND column_name = '{new_name}'")
        rename_sql = text(f'ALTER TABLE "{table}" RENAME COLUMN "{old_name}" TO "{new_name}"')
        add_sql = text(f'ALTER TABLE "{table}" ADD COLUMN "{new_name}" TEXT NULL')

    old_exists = (await conn.execute(check_old_sql)).scalar_one_or_none()
    new_exists = (await conn.execute(check_new_sql)).scalar_one_or_none()

    if old_exists and not new_exists:
        await conn.execute(rename_sql)
    elif not old_exists and not new_exists:
        await conn.execute(add_sql)

async def _migrate_clear_rate_limit_state_task(conn: AsyncConnection):
    """迁移任务: 清理旧的速率限制状态和配置。"""
    await conn.execute(text("TRUNCATE TABLE rate_limit_state;"))
    await conn.execute(text("DELETE FROM config WHERE config_key IN ('globalRateLimitEnabled', 'globalRateLimitCount', 'globalRateLimitPeriod')"))

async def _migrate_add_unique_key_to_task_history_task(conn: AsyncConnection, db_type: str):
    """迁移任务: 确保 task_history 表有 unique_key 字段和索引。"""
    if db_type == "mysql":
        check_column_sql = text("SELECT 1 FROM information_schema.columns WHERE table_name = 'task_history' AND column_name = 'unique_key'")
        add_column_sql = text("ALTER TABLE task_history ADD COLUMN `unique_key` VARCHAR(255) NULL, ADD INDEX `idx_unique_key` (`unique_key`)")
    else: # postgresql
        check_column_sql = text("SELECT 1 FROM information_schema.columns WHERE table_name = 'task_history' AND column_name = 'unique_key'")
        add_column_sql = text('ALTER TABLE task_history ADD COLUMN "unique_key" VARCHAR(255) NULL')
        add_index_sql = text('CREATE INDEX IF NOT EXISTS idx_task_history_unique_key ON task_history (unique_key)')

    if not (await conn.execute(check_column_sql)).scalar_one_or_none():
        await conn.execute(add_column_sql)
        # 仅当数据库是 PostgreSQL 时，才单独执行创建索引的语句
        if db_type == "postgresql":
            await conn.execute(add_index_sql)

async def _migrate_api_token_to_daily_limit_task(conn: AsyncConnection, db_type: str):
    """迁移任务: 将 api_tokens 表的调用限制升级为每日限制。"""
    # 检查新列是否存在，如果存在则认为迁移已完成
    if db_type == "mysql":
        check_new_col_sql = text("SELECT 1 FROM information_schema.columns WHERE table_name = 'api_tokens' AND column_name = 'daily_call_limit'")
    else: # postgresql
        check_new_col_sql = text("SELECT 1 FROM information_schema.columns WHERE table_name = 'api_tokens' AND column_name = 'daily_call_limit'")

    if (await conn.execute(check_new_col_sql)).scalar_one_or_none():
        logger.info("检测到 'daily_call_limit' 列，跳过 api_tokens 表的迁移。")
        return

    # 检查旧列是否存在
    if db_type == "mysql":
        check_old_col_sql = text("SELECT 1 FROM information_schema.columns WHERE table_name = 'api_tokens' AND column_name = 'call_limit'")
    else: # postgresql
        check_old_col_sql = text("SELECT 1 FROM information_schema.columns WHERE table_name = 'api_tokens' AND column_name = 'call_limit'")

    if (await conn.execute(check_old_col_sql)).scalar_one_or_none():
        logger.info("检测到旧的 'call_limit' 列，正在执行重命名和添加新列操作...")
        if db_type == "mysql":
            await conn.execute(text("ALTER TABLE api_tokens CHANGE COLUMN `call_limit` `daily_call_limit` INT NOT NULL DEFAULT 500;"))
            await conn.execute(text("ALTER TABLE api_tokens CHANGE COLUMN `call_count` `daily_call_count` INT NOT NULL DEFAULT 0;"))
            await conn.execute(text("ALTER TABLE api_tokens ADD COLUMN `last_call_at` DATETIME NULL DEFAULT NULL;"))
        else: # postgresql
            await conn.execute(text('ALTER TABLE api_tokens RENAME COLUMN "call_limit" TO "daily_call_limit";'))
            await conn.execute(text('ALTER TABLE api_tokens RENAME COLUMN "call_count" TO "daily_call_count";'))
            await conn.execute(text('ALTER TABLE api_tokens ADD COLUMN "last_call_at" TIMESTAMP NULL DEFAULT NULL;'))
        logger.info("成功将 api_tokens 表升级到每日限制模式。")
    else:
        logger.info("未检测到旧的 'call_limit' 列，可能是新安装，将直接添加新列...")
        if db_type == "mysql":
            await conn.execute(text("ALTER TABLE api_tokens ADD COLUMN `daily_call_limit` INT NOT NULL DEFAULT 500;"))
            await conn.execute(text("ALTER TABLE api_tokens ADD COLUMN `daily_call_count` INT NOT NULL DEFAULT 0;"))
            await conn.execute(text("ALTER TABLE api_tokens ADD COLUMN `last_call_at` DATETIME NULL DEFAULT NULL;"))
        else: # postgresql
            await conn.execute(text('ALTER TABLE api_tokens ADD COLUMN "daily_call_limit" INTEGER NOT NULL DEFAULT 500;'))
            await conn.execute(text('ALTER TABLE api_tokens ADD COLUMN "daily_call_count" INTEGER NOT NULL DEFAULT 0;'))
            await conn.execute(text('ALTER TABLE api_tokens ADD COLUMN "last_call_at" TIMESTAMP NULL DEFAULT NULL;'))
        logger.info("成功为 api_tokens 表添加每日限制相关列。")

async def _migrate_add_log_raw_responses_to_metadata_sources_task(conn: AsyncConnection, db_type: str):
    """迁移任务: 确保 metadata_sources 表有 log_raw_responses 字段。"""
    table_name = 'metadata_sources'
    column_name = 'log_raw_responses'

    if db_type == "mysql":
        check_column_sql = text(f"SELECT 1 FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = '{table_name}' AND column_name = '{column_name}'")
        add_column_sql = text(f"ALTER TABLE {table_name} ADD COLUMN `{column_name}` BOOLEAN NOT NULL DEFAULT FALSE")
    else: # postgresql
        check_column_sql = text(f"SELECT 1 FROM information_schema.columns WHERE table_name = '{table_name}' AND column_name = '{column_name}'")
        add_column_sql = text(f'ALTER TABLE {table_name} ADD COLUMN "{column_name}" BOOLEAN NOT NULL DEFAULT FALSE')

    if not (await conn.execute(check_column_sql)).scalar_one_or_none():
        await conn.execute(add_column_sql)

async def _migrate_danmaku_paths_to_absolute_task(conn: AsyncConnection):
    """迁移任务: 将现有的相对路径转换为绝对路径。"""
    # 查询所有以 /danmaku/ 开头但不以 /app/config/danmaku/ 开头的路径（防止重复拼接）
    select_sql = text("SELECT id, danmaku_file_path FROM episode WHERE danmaku_file_path LIKE '/danmaku/%' AND danmaku_file_path NOT LIKE '/app/config/danmaku/%'")
    episodes = await conn.execute(select_sql)

    migrated_count = 0
    for episode in episodes:
        episode_id, old_path = episode
        # 直接在前面拼接 /app/config
        new_path = f"/app/config{old_path}"

        # 更新数据库
        update_sql = text("UPDATE episode SET danmaku_file_path = :new_path WHERE id = :episode_id")
        await conn.execute(update_sql, {"new_path": new_path, "episode_id": episode_id})
        migrated_count += 1

        logger.debug(f"迁移路径: {old_path} -> {new_path}")

    logger.info(f"弹幕路径迁移完成，共迁移 {migrated_count} 个分集的路径")

async def _enable_metadata_source_proxy_by_default_task(conn: AsyncConnection):
    """迁移任务: 将元信息搜索源的代理开关默认设置为开启。"""
    # 更新所有现有的元信息搜索源，将 use_proxy 设置为 true
    update_sql = text("UPDATE metadata_sources SET use_proxy = true WHERE use_proxy = false")
    result = await conn.execute(update_sql)

    updated_count = result.rowcount
    logger.info(f"元信息搜索源代理设置迁移完成，共更新了 {updated_count} 个源。")
    return f"成功为 {updated_count} 个元信息搜索源启用了代理功能。"

async def _create_task_state_cache_table_task(conn: AsyncConnection, db_type: str):
    """迁移任务: 创建任务状态缓存表，用于支持服务重启后的任务恢复。"""
    table_name = 'task_state_cache'

    # 检查表是否已存在
    if db_type == "mysql":
        check_table_sql = text(f"SELECT 1 FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = '{table_name}'")
        create_table_sql = text(f"""
            CREATE TABLE {table_name} (
                task_id VARCHAR(100) PRIMARY KEY,
                task_type VARCHAR(100) NOT NULL,
                task_parameters MEDIUMTEXT NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                INDEX idx_task_type (task_type)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
    else: # postgresql
        check_table_sql = text(f"SELECT 1 FROM information_schema.tables WHERE table_name = '{table_name}'")
        create_table_sql = text(f"""
            CREATE TABLE {table_name} (
                task_id VARCHAR(100) PRIMARY KEY,
                task_type VARCHAR(100) NOT NULL,
                task_parameters TEXT NOT NULL,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
                updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL
            )
        """)
        create_index_sql = text(f"CREATE INDEX IF NOT EXISTS idx_task_state_cache_task_type ON {table_name} (task_type)")

    if not (await conn.execute(check_table_sql)).scalar_one_or_none():
        await conn.execute(create_table_sql)
        # 仅当数据库是 PostgreSQL 时，才单独执行创建索引的语句
        if db_type == "postgresql":
            await conn.execute(create_index_sql)
        logger.info(f"成功创建任务状态缓存表 '{table_name}'")
    else:
        logger.info(f"任务状态缓存表 '{table_name}' 已存在，跳过创建")

async def _create_title_recognition_table_task(conn: AsyncConnection, db_type: str):
    """创建识别词配置表"""
    table_name = "title_recognition"

    # 检查表是否已存在
    if db_type == "mysql":
        check_sql = text("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = :table_name")
    else:  # postgresql
        check_sql = text("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = :table_name")

    result = await conn.execute(check_sql, {"table_name": table_name})
    table_exists = result.scalar() > 0

    if not table_exists:
        if db_type == "mysql":
            create_table_sql = text(f"""
                CREATE TABLE {table_name} (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    content MEDIUMTEXT NOT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
        else:  # postgresql
            create_table_sql = text(f"""
                CREATE TABLE {table_name} (
                    id SERIAL PRIMARY KEY,
                    content TEXT NOT NULL
                )
            """)

        await conn.execute(create_table_sql)
        logger.info(f"成功创建识别词配置表 '{table_name}'")
    else:
        logger.info(f"识别词配置表 '{table_name}' 已存在，跳过创建")

async def _add_queue_type_to_task_history_task(conn: AsyncConnection, db_type: str):
    """迁移任务: 为task_history表添加queue_type字段"""
    table_name = "task_history"
    column_name = "queue_type"

    # 检查列是否已存在
    if db_type == "mysql":
        check_sql = text(f"""
            SELECT COUNT(*) FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
            AND TABLE_NAME = '{table_name}'
            AND COLUMN_NAME = '{column_name}'
        """)
    else:  # postgresql
        check_sql = text(f"""
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_name = '{table_name}'
            AND column_name = '{column_name}'
        """)

    column_exists = (await conn.execute(check_sql)).scalar() > 0

    if not column_exists:
        logger.info(f"为表 '{table_name}' 添加 '{column_name}' 列...")
        if db_type == "mysql":
            alter_sql = text(f"""
                ALTER TABLE {table_name}
                ADD COLUMN {column_name} VARCHAR(20) NOT NULL DEFAULT 'download'
            """)
        else:  # postgresql
            alter_sql = text(f"""
                ALTER TABLE {table_name}
                ADD COLUMN {column_name} VARCHAR(20) NOT NULL DEFAULT 'download'
            """)
        await conn.execute(alter_sql)
        logger.info(f"成功为表 '{table_name}' 添加 '{column_name}' 列")
    else:
        logger.info(f"表 '{table_name}' 的 '{column_name}' 列已存在，跳过添加")

async def _add_alias_locked_to_anime_aliases_task(conn: AsyncConnection, db_type: str):
    """迁移任务: 为anime_aliases表添加alias_locked字段 + 移除旧的TMDB映射定时任务"""
    table_name = "anime_aliases"
    column_name = "alias_locked"

    # 检查列是否已存在
    if db_type == "mysql":
        check_sql = text(f"""
            SELECT COUNT(*) FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
            AND TABLE_NAME = '{table_name}'
            AND COLUMN_NAME = '{column_name}'
        """)
    else:  # postgresql
        check_sql = text(f"""
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_name = '{table_name}'
            AND column_name = '{column_name}'
        """)

    column_exists = (await conn.execute(check_sql)).scalar() > 0

    if not column_exists:
        logger.info(f"为表 '{table_name}' 添加 '{column_name}' 列...")
        if db_type == "mysql":
            alter_sql = text(f"""
                ALTER TABLE {table_name}
                ADD COLUMN {column_name} BOOLEAN NOT NULL DEFAULT FALSE
            """)
        else:  # postgresql
            alter_sql = text(f"""
                ALTER TABLE {table_name}
                ADD COLUMN {column_name} BOOLEAN NOT NULL DEFAULT FALSE
            """)
        await conn.execute(alter_sql)
        logger.info(f"成功为表 '{table_name}' 添加 '{column_name}' 列")
    else:
        logger.info(f"表 '{table_name}' 的 '{column_name}' 列已存在，跳过添加")

    # 移除旧的TMDB映射定时任务(job_type='tmdbAutoMap')
    delete_sql = text("DELETE FROM scheduled_tasks WHERE job_type = 'tmdbAutoMap'")
    result = await conn.execute(delete_sql)
    deleted_count = result.rowcount

    if deleted_count > 0:
        logger.info(f"成功删除 {deleted_count} 个旧的TMDB映射定时任务(job_type='tmdbAutoMap')")
    else:
        logger.info("未找到需要删除的旧TMDB映射定时任务")

async def _add_updated_at_to_media_items_task(conn: AsyncConnection, db_type: str):
    """迁移任务: 为media_items表添加updated_at字段"""
    table_name = "media_items"
    column_name = "updated_at"

    # 检查列是否已存在
    if db_type == "mysql":
        check_sql = text(f"""
            SELECT COUNT(*) FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
            AND TABLE_NAME = '{table_name}'
            AND COLUMN_NAME = '{column_name}'
        """)
    else:  # postgresql
        check_sql = text(f"""
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_name = '{table_name}'
            AND column_name = '{column_name}'
        """)

    column_exists = (await conn.execute(check_sql)).scalar() > 0

    if not column_exists:
        logger.info(f"为表 '{table_name}' 添加 '{column_name}' 列...")
        if db_type == "mysql":
            alter_sql = text(f"""
                ALTER TABLE {table_name}
                ADD COLUMN {column_name} DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            """)
        else:  # postgresql
            alter_sql = text(f"""
                ALTER TABLE {table_name}
                ADD COLUMN {column_name} TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
            """)
        await conn.execute(alter_sql)
        logger.info(f"成功为表 '{table_name}' 添加 '{column_name}' 列")
    else:
        logger.info(f"表 '{table_name}' 的 '{column_name}' 列已存在，跳过添加")

async def _rename_ai_config_keys_task(conn: AsyncConnection):
    """迁移任务: 重命名AI配置键,统一使用不带Match的键名"""
    # 定义需要重命名的配置键映射 (旧键名 -> 新键名)
    key_mappings = {
        'aiMatchProvider': 'aiProvider',
        'aiMatchApiKey': 'aiApiKey',
        'aiMatchBaseUrl': 'aiBaseUrl',
        'aiMatchModel': 'aiModel',
        'aiMatchPrompt': 'aiPrompt',
        'aiMatchFallbackEnabled': 'aiFallbackEnabled',
    }

    for old_key, new_key in key_mappings.items():
        # 检查旧键是否存在
        check_old_sql = text("SELECT config_value, description FROM config WHERE config_key = :old_key")
        result = await conn.execute(check_old_sql, {"old_key": old_key})
        old_row = result.fetchone()

        if old_row:
            old_value, old_desc = old_row
            logger.info(f"正在重命名配置键: '{old_key}' -> '{new_key}'")

            # 检查新键是否已存在
            check_new_sql = text("SELECT 1 FROM config WHERE config_key = :new_key")
            new_exists = (await conn.execute(check_new_sql, {"new_key": new_key})).scalar_one_or_none()

            if new_exists:
                # 新键已存在,只删除旧键
                logger.info(f"新键 '{new_key}' 已存在,删除旧键 '{old_key}'")
                delete_sql = text("DELETE FROM config WHERE config_key = :old_key")
                await conn.execute(delete_sql, {"old_key": old_key})
            else:
                # 新键不存在,重命名旧键
                update_sql = text("UPDATE config SET config_key = :new_key WHERE config_key = :old_key")
                await conn.execute(update_sql, {"new_key": new_key, "old_key": old_key})
                logger.info(f"成功重命名配置键: '{old_key}' -> '{new_key}'")
        else:
            logger.info(f"旧键 '{old_key}' 不存在,跳过重命名")

    logger.info("AI配置键重命名完成")

async def _create_local_danmaku_items_table_task(conn: AsyncConnection, db_type: str):
    """创建本地弹幕扫描表"""
    logger.info("开始创建 local_danmaku_items 表...")

    if db_type == 'mysql':
        create_table_sql = text("""
            CREATE TABLE IF NOT EXISTS local_danmaku_items (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                file_path VARCHAR(1024) NOT NULL,
                title VARCHAR(512) NOT NULL,
                media_type ENUM('movie', 'tv_series') NOT NULL,
                season INT NULL,
                episode INT NULL,
                year INT NULL,
                tmdb_id VARCHAR(50) NULL,
                tvdb_id VARCHAR(50) NULL,
                imdb_id VARCHAR(50) NULL,
                poster_url VARCHAR(1024) NULL,
                nfo_path VARCHAR(1024) NULL,
                is_imported BOOLEAN NOT NULL DEFAULT FALSE,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_local_file_path (file_path(255)),
                INDEX idx_local_media_type (media_type),
                INDEX idx_local_is_imported (is_imported)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
    else:  # postgresql
        # 先创建枚举类型
        create_enum_sql = text("""
            DO $$ BEGIN
                CREATE TYPE local_media_type AS ENUM ('movie', 'tv_series');
            EXCEPTION
                WHEN duplicate_object THEN null;
            END $$;
        """)
        await conn.execute(create_enum_sql)

        create_table_sql = text("""
            CREATE TABLE IF NOT EXISTS local_danmaku_items (
                id BIGSERIAL PRIMARY KEY,
                file_path VARCHAR(1024) NOT NULL,
                title VARCHAR(512) NOT NULL,
                media_type local_media_type NOT NULL,
                season INTEGER NULL,
                episode INTEGER NULL,
                year INTEGER NULL,
                tmdb_id VARCHAR(50) NULL,
                tvdb_id VARCHAR(50) NULL,
                imdb_id VARCHAR(50) NULL,
                poster_url VARCHAR(1024) NULL,
                nfo_path VARCHAR(1024) NULL,
                is_imported BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute(create_table_sql)

        # 创建索引
        index_sqls = [
            text("CREATE INDEX IF NOT EXISTS idx_local_file_path ON local_danmaku_items (file_path)"),
            text("CREATE INDEX IF NOT EXISTS idx_local_media_type ON local_danmaku_items (media_type)"),
            text("CREATE INDEX IF NOT EXISTS idx_local_is_imported ON local_danmaku_items (is_imported)")
        ]
        for index_sql in index_sqls:
            await conn.execute(index_sql)

        logger.info("local_danmaku_items 表创建完成(PostgreSQL)")
        return

    await conn.execute(create_table_sql)
    logger.info("local_danmaku_items 表创建完成(MySQL)")

async def run_migrations(conn: AsyncConnection, db_type: str, db_name: str):
    """
    按顺序执行所有数据库架构迁移。
    """
    logger.info("开始执行数据库迁移检查...")

    # 迁移任务列表，按依赖顺序列出
    migrations = [
        ("migrate_utc_to_local_datetime_v2", _migrate_utc_to_local_datetime_task, (db_type,)),
        ("migrate_clear_rate_limit_state_v1", _migrate_clear_rate_limit_state_task, ()),
        ("migrate_add_source_order_v1", _migrate_add_source_order_task, (db_type, db_name)),
        ("migrate_add_danmaku_file_path_v1", _migrate_add_danmaku_file_path_task, (db_type,)),
        ("migrate_text_to_mediumtext_v1", _migrate_text_to_mediumtext_task, (db_type, db_name)),
        ("migrate_add_source_url_to_episode_v1", _migrate_add_source_url_to_episode_task, (db_type, db_name)),
        ("migrate_add_unique_key_to_task_history_v1", _migrate_add_unique_key_to_task_history_task, (db_type,)),
        ("migrate_api_token_to_daily_limit_v1", _migrate_api_token_to_daily_limit_task, (db_type,)),
        ("migrate_add_log_raw_responses_to_metadata_sources_v1", _migrate_add_log_raw_responses_to_metadata_sources_task, (db_type,)),
        ("migrate_danmaku_paths_to_absolute_v2", _migrate_danmaku_paths_to_absolute_task, ()),
        ("migrate_enable_metadata_source_proxy_by_default_v1", _enable_metadata_source_proxy_by_default_task, ()),
        ("migrate_create_task_state_cache_table_v1", _create_task_state_cache_table_task, (db_type,)),
        ("migrate_create_title_recognition_table_v1", _create_title_recognition_table_task, (db_type,)),
        ("migrate_add_queue_type_to_task_history_v1", _add_queue_type_to_task_history_task, (db_type,)),
        ("migrate_add_alias_locked_to_anime_aliases_v1", _add_alias_locked_to_anime_aliases_task, (db_type,)),
        ("migrate_add_updated_at_to_media_items_v1", _add_updated_at_to_media_items_task, (db_type,)),
        ("migrate_rename_ai_config_keys_v1", _rename_ai_config_keys_task, ()),
        ("migrate_create_local_danmaku_items_table_v1", _create_local_danmaku_items_table_task, (db_type,)),
    ]

    for migration_id, migration_func, args in migrations:
        await _run_migration(conn, migration_id, migration_func, *args)

    logger.info("所有数据库迁移检查完成。")