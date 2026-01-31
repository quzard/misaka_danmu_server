"""
配置相关的CRUD操作
"""

import logging
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.postgresql import insert as postgresql_insert

from ..orm_models import Config

logger = logging.getLogger(__name__)


async def get_config_value(session: AsyncSession, key: str, default: str = "") -> str:
    """
    从数据库获取配置值

    Args:
        session: 数据库会话
        key: 配置键
        default: 默认值,当数据库中不存在该键时返回此值(默认为空字符串)

    Returns:
        配置值,如果数据库中不存在则返回default

    注意:
        - 如果数据库中存在该键但值为空字符串,会返回空字符串(不会返回default)
        - 只有当数据库中不存在该键时,才会返回default
        - 对于AI提示词等配置,应该先调用initialize_configs确保键存在,再调用此函数读取
    """
    stmt = select(Config.configValue).where(Config.configKey == key)
    result = await session.execute(stmt)
    value = result.scalar_one_or_none()
    
    if value is None:
        return default
    return value


async def update_config_value(session: AsyncSession, key: str, value: str):
    """
    更新配置值(如果不存在则插入)

    Args:
        session: 数据库会话
        key: 配置键
        value: 配置值
    """
    dialect = session.bind.dialect.name
    values_to_insert = {"configKey": key, "configValue": value}

    if dialect == 'mysql':
        stmt = mysql_insert(Config).values(values_to_insert)
        stmt = stmt.on_duplicate_key_update(config_value=stmt.inserted.config_value)
    elif dialect == 'postgresql':
        stmt = postgresql_insert(Config).values(values_to_insert)
        # 修正：使用 on_conflict_do_update 并通过 index_elements 指定主键列，以提高兼容性
        stmt = stmt.on_conflict_do_update(
            index_elements=['config_key'],
            set_={'config_value': stmt.excluded.config_value}
        )
    else:
        raise NotImplementedError(f"配置更新功能尚未为数据库类型 '{dialect}' 实现。")

    await session.execute(stmt)
    await session.commit()


async def initialize_configs(session: AsyncSession, defaults: Dict[str, tuple[Any, str]]):
    """
    初始化默认配置(仅插入数据库中不存在的配置项)

    Args:
        session: 数据库会话
        defaults: 默认配置字典,格式为 {key: (value, description)}
    """
    if not defaults:
        return
    
    existing_stmt = select(Config.configKey)
    existing_keys = set((await session.execute(existing_stmt)).scalars().all())
    
    new_configs = [
        Config(configKey=key, configValue=str(value), description=description)
        for key, (value, description) in defaults.items()
        if key not in existing_keys
    ]
    if new_configs:
        session.add_all(new_configs)
        await session.commit()
        logger.info(f"成功初始化 {len(new_configs)} 个新配置项。")
    logger.info("默认配置检查完成。")

