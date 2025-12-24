"""
统一数据库初始化器

参考 emby-toolkit 项目的设计理念，整合以下功能：
1. 表创建（基于 SQLAlchemy ORM 模型）
2. 字段升级（声明式配置 + 自动检测）
3. 索引管理（集中声明式定义）
4. 废弃对象清理（主动清理过时的表和字段）

优势：
- 单一入口，易于维护
- 声明式配置，结构清晰
- 幂等性操作，可重复执行
- 完整的生命周期管理
"""

import logging
from typing import Dict, List, Set
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from .orm_models import Base
from .db_maintainer import sync_database_schema
from .migrations import run_migrations

logger = logging.getLogger(__name__)


# ============================================================
# 📊 声明式配置区域
# ============================================================

# 🔹 字段升级配置（可选，与 db_maintainer 配合使用）
# 格式: {'表名': {'字段名': '字段类型'}}
SCHEMA_UPGRADES: Dict[str, Dict[str, str]] = {
    # 示例（已由 db_maintainer 自动处理，这里仅作备份记录）:
    # 'anime': {
    #     'new_field': 'VARCHAR(255)',
    # },
}

# 🔹 废弃表清理配置
# 格式: ['表名1', '表名2']
DEPRECATED_TABLES: List[str] = [
    # 示例：
    # 'old_cache_table',  # 已被 cache_data 表替代
    # 'legacy_logs',      # 已迁移到新的日志系统
]

# 🔹 废弃字段清理配置
# 格式: {'表名': ['字段名1', '字段名2']}
DEPRECATED_COLUMNS: Dict[str, List[str]] = {
    # 示例：
    # 'anime': [
    #     'old_status_field',  # 已被 new_status 替代
    # ],
    # 'api_tokens': [
    #     'legacy_permissions',  # 已迁移到新的权限系统
    # ],
}

# 🔹 索引管理配置
# 格式: ['CREATE INDEX IF NOT EXISTS ...', ...]
# 注意：基础索引已在 ORM 模型中定义，这里只添加额外的优化索引
ADDITIONAL_INDEXES: List[str] = [
    # 示例：复合索引、降序索引、部分索引等
    # MySQL 示例：
    # "CREATE INDEX IF NOT EXISTS idx_anime_year_type ON anime(year, type)",
    # "CREATE INDEX IF NOT EXISTS idx_episodes_anime_index ON episodes(anime_id, episode_index)",

    # PostgreSQL 特有示例（GIN 索引用于 JSONB）：
    # "CREATE INDEX IF NOT EXISTS idx_metadata_json_gin ON anime_metadata USING GIN(metadata_json)",
]


# ============================================================
# 🔧 核心初始化函数
# ============================================================

async def init_database_schema(conn: AsyncConnection, db_type: str, db_name: str):
    """
    【统一数据库初始化入口】

    按以下顺序执行所有数据库初始化任务：
    1. 基于 ORM 模型创建所有表
    2. 自动检测并补充缺失的字段（db_maintainer）
    3. 执行需要数据转换的复杂迁移（migrations）
    4. 创建额外的优化索引
    5. 清理废弃的表和字段

    Args:
        conn: 数据库连接
        db_type: 数据库类型 ('mysql' 或 'postgresql')
        db_name: 数据库名称
    """
    logger.info("="*60)
    logger.info("开始数据库初始化流程...")
    logger.info("="*60)

    # ✅ 阶段 1: 创建所有基于 ORM 模型的表
    logger.info("📋 [阶段 1/5] 正在同步 ORM 模型，创建新表...")
    await conn.run_sync(Base.metadata.create_all)
    logger.info("✓ ORM 模型同步完成。")

    # ✅ 阶段 2: 自动检测并补充缺失的字段
    logger.info("🔍 [阶段 2/5] 正在检测并补充缺失的字段...")
    await sync_database_schema(conn, db_type)
    logger.info("✓ 字段同步完成。")

    # ✅ 阶段 3: 执行复杂的数据迁移任务
    logger.info("🔄 [阶段 3/5] 正在执行数据库迁移任务...")
    await run_migrations(conn, db_type, db_name)
    logger.info("✓ 迁移任务完成。")

    # ✅ 阶段 4: 创建额外的优化索引
    logger.info("📊 [阶段 4/5] 正在创建额外的优化索引...")
    await _create_additional_indexes(conn, db_type)
    logger.info("✓ 索引创建完成。")

    # ✅ 阶段 5: 清理废弃的表和字段
    logger.info("🧹 [阶段 5/5] 正在清理废弃的数据库对象...")
    await _cleanup_deprecated_objects(conn, db_type)
    logger.info("✓ 清理完成。")

    logger.info("="*60)
    logger.info("✅ 数据库初始化流程全部完成！")
    logger.info("="*60)


# ============================================================
# 🛠️ 辅助函数
# ============================================================

async def _create_additional_indexes(conn: AsyncConnection, db_type: str):
    """创建额外的优化索引"""
    if not ADDITIONAL_INDEXES:
        logger.info("   无需创建额外索引。")
        return

    created_count = 0
    for index_sql in ADDITIONAL_INDEXES:
        try:
            await conn.execute(text(index_sql))
            # 提取索引名用于日志
            index_name = index_sql.split("IF NOT EXISTS")[1].split("ON")[0].strip() if "IF NOT EXISTS" in index_sql else "未知"
            logger.info(f"   ✓ 创建索引: {index_name}")
            created_count += 1
        except Exception as e:
            logger.warning(f"   ⚠️ 创建索引失败（可能已存在）: {e}")

    logger.info(f"   成功创建 {created_count} 个索引。")




async def _cleanup_deprecated_objects(conn: AsyncConnection, db_type: str):
    """清理废弃的表和字段"""
    cleanup_stats = {
        'tables_dropped': 0,
        'columns_dropped': 0,
        'warnings': 0
    }

    # 清理废弃的表
    if DEPRECATED_TABLES:
        logger.info(f"   正在清理 {len(DEPRECATED_TABLES)} 个废弃表...")
        for table_name in DEPRECATED_TABLES:
            try:
                if await _check_table_exists(conn, db_type, table_name):
                    # 使用 CASCADE 确保清理外键关联
                    await conn.execute(text(f"DROP TABLE IF EXISTS {table_name} CASCADE"))
                    logger.info(f"   ✓ 删除废弃表: {table_name}")
                    cleanup_stats['tables_dropped'] += 1
            except Exception as e:
                logger.error(f"   ✗ 删除表 {table_name} 失败: {e}")
                cleanup_stats['warnings'] += 1

    # 清理废弃的字段
    if DEPRECATED_COLUMNS:
        logger.info(f"   正在清理废弃字段...")
        for table_name, columns in DEPRECATED_COLUMNS.items():
            # 先检查表是否存在
            if not await _check_table_exists(conn, db_type, table_name):
                logger.warning(f"   ⚠️ 表 {table_name} 不存在，跳过字段清理。")
                continue

            for column_name in columns:
                try:
                    # 检查字段是否存在
                    if await _check_column_exists(conn, db_type, table_name, column_name):
                        await conn.execute(text(f"ALTER TABLE {table_name} DROP COLUMN IF EXISTS {column_name}"))
                        logger.info(f"   ✓ 删除废弃字段: {table_name}.{column_name}")
                        cleanup_stats['columns_dropped'] += 1
                except Exception as e:
                    logger.error(f"   ✗ 删除字段 {table_name}.{column_name} 失败: {e}")
                    cleanup_stats['warnings'] += 1

    # 输出统计信息
    if cleanup_stats['tables_dropped'] > 0 or cleanup_stats['columns_dropped'] > 0:
        logger.info(f"   清理统计: 删除了 {cleanup_stats['tables_dropped']} 个表, {cleanup_stats['columns_dropped']} 个字段。")
    else:
        logger.info("   无需清理任何对象。")

    if cleanup_stats['warnings'] > 0:
        logger.warning(f"   清理过程中有 {cleanup_stats['warnings']} 个警告。")


async def _check_table_exists(conn: AsyncConnection, db_type: str, table_name: str) -> bool:
    """检查表是否存在"""
    if db_type == "mysql":
        sql = text("SELECT 1 FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = :table_name")
    else:  # postgresql
        sql = text("SELECT 1 FROM information_schema.tables WHERE table_schema = current_schema() AND table_name = :table_name")

    result = await conn.execute(sql, {"table_name": table_name})
    return result.scalar_one_or_none() is not None


async def _check_column_exists(conn: AsyncConnection, db_type: str, table_name: str, column_name: str) -> bool:
    """检查字段是否存在"""
    if db_type == "mysql":
        sql = text("""
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = DATABASE()
            AND table_name = :table_name
            AND column_name = :column_name
        """)
    else:  # postgresql
        sql = text("""
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = current_schema()
            AND table_name = :table_name
            AND column_name = :column_name
        """)

    result = await conn.execute(sql, {"table_name": table_name, "column_name": column_name})
    return result.scalar_one_or_none() is not None


# ============================================================
# 📝 使用示例
# ============================================================
"""
在 main.py 中简化调用：

# 修改前（分散在多个步骤）:
async with engine.begin() as conn:
    await conn.run_sync(Base.metadata.create_all)
    await sync_database_schema(conn, db_type)
    await run_migrations(conn, db_type, db_name)

# 修改后（统一入口）:
async with engine.begin() as conn:
    from .database_initializer import init_database_schema
    await init_database_schema(conn, db_type, db_name)
"""

