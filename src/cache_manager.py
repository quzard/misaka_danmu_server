"""
缓存管理器模块

提供统一的缓存管理接口,支持:
- 创建/获取/更新/删除缓存
- 自动TTL过期
- 缓存前缀管理
- 模式匹配查询
"""

import logging
import asyncio
from typing import Any, Optional, List
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from . import crud


class CacheManager:
    """
    统一的缓存管理器,用于管理数据库缓存
    
    使用示例:
        cache_manager = CacheManager(session_factory)
        
        # 设置缓存
        await cache_manager.set("user_data", "user_123", {"name": "Alice"}, ttl=3600)
        
        # 获取缓存
        data = await cache_manager.get("user_data", "user_123")
        
        # 删除缓存
        await cache_manager.delete("user_data", "user_123")
        
        # 清除某个前缀的所有缓存
        await cache_manager.clear_by_prefix("user_data")
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        """
        初始化缓存管理器
        
        Args:
            session_factory: SQLAlchemy异步会话工厂
        """
        self.session_factory = session_factory
        self._lock = asyncio.Lock()
        self.logger = logging.getLogger(self.__class__.__name__)

    async def get(self, prefix: str, key: str, session: Optional[AsyncSession] = None) -> Optional[Any]:
        """
        获取缓存数据
        
        Args:
            prefix: 缓存前缀,用于分类管理
            key: 缓存键
            session: 可选的数据库会话,如果不提供则创建新会话
            
        Returns:
            缓存的数据,如果不存在或已过期则返回None
        """
        cache_key = f"{prefix}{key}"
        
        if session:
            return await crud.get_cache(session, cache_key)
        else:
            async with self.session_factory() as new_session:
                return await crud.get_cache(new_session, cache_key)

    async def set(
        self, 
        prefix: str, 
        key: str, 
        value: Any, 
        ttl_seconds: int,
        session: Optional[AsyncSession] = None
    ) -> None:
        """
        设置缓存数据
        
        Args:
            prefix: 缓存前缀
            key: 缓存键
            value: 要缓存的数据(会自动JSON序列化)
            ttl_seconds: 过期时间(秒)
            session: 可选的数据库会话
        """
        cache_key = f"{prefix}{key}"
        
        if session:
            await crud.set_cache(session, cache_key, value, ttl_seconds)
        else:
            async with self.session_factory() as new_session:
                await crud.set_cache(new_session, cache_key, value, ttl_seconds)
                await new_session.commit()

    async def delete(self, prefix: str, key: str, session: Optional[AsyncSession] = None) -> bool:
        """
        删除指定的缓存
        
        Args:
            prefix: 缓存前缀
            key: 缓存键
            session: 可选的数据库会话
            
        Returns:
            是否成功删除
        """
        cache_key = f"{prefix}{key}"
        
        try:
            if session:
                await crud.delete_cache(session, cache_key)
            else:
                async with self.session_factory() as new_session:
                    await crud.delete_cache(new_session, cache_key)
                    await new_session.commit()
            return True
        except Exception as e:
            self.logger.error(f"删除缓存失败: {cache_key}, 错误: {e}")
            return False

    async def exists(self, prefix: str, key: str, session: Optional[AsyncSession] = None) -> bool:
        """
        检查缓存是否存在
        
        Args:
            prefix: 缓存前缀
            key: 缓存键
            session: 可选的数据库会话
            
        Returns:
            缓存是否存在且未过期
        """
        data = await self.get(prefix, key, session)
        return data is not None

    async def get_keys_by_pattern(
        self,
        pattern: str,
        session: Optional[AsyncSession] = None
    ) -> List[str]:
        """
        根据模式匹配获取缓存键列表

        Args:
            pattern: SQL LIKE模式,例如 "user_data_*"
            session: 可选的数据库会话

        Returns:
            匹配的缓存键列表
        """
        if session:
            return await crud.get_cache_keys_by_pattern(session, pattern)
        else:
            async with self.session_factory() as new_session:
                return await crud.get_cache_keys_by_pattern(new_session, pattern)

    async def clear_by_prefix(self, prefix: str, session: Optional[AsyncSession] = None) -> int:
        """
        清除指定前缀的所有缓存

        Args:
            prefix: 缓存前缀
            session: 可选的数据库会话

        Returns:
            删除的缓存数量
        """
        pattern = f"{prefix}*"
        keys = await self.get_keys_by_pattern(pattern, session)

        deleted_count = 0
        for cache_key in keys:
            try:
                if session:
                    await crud.delete_cache(session, cache_key)
                else:
                    async with self.session_factory() as new_session:
                        await crud.delete_cache(new_session, cache_key)
                        await new_session.commit()
                deleted_count += 1
            except Exception as e:
                self.logger.error(f"删除缓存失败: {cache_key}, 错误: {e}")

        self.logger.info(f"清除前缀 '{prefix}' 的缓存,共删除 {deleted_count} 条")
        return deleted_count

    async def clear_all(self, session: Optional[AsyncSession] = None) -> int:
        """
        清除所有缓存

        Args:
            session: 可选的数据库会话

        Returns:
            删除的缓存数量
        """
        if session:
            deleted_count = await crud.clear_all_cache(session)
        else:
            async with self.session_factory() as new_session:
                deleted_count = await crud.clear_all_cache(new_session)
                await new_session.commit()

        self.logger.info(f"清除所有缓存,共删除 {deleted_count} 条")
        return deleted_count

    async def get_or_set(
        self,
        prefix: str,
        key: str,
        factory_func,
        ttl_seconds: int,
        session: Optional[AsyncSession] = None
    ) -> Any:
        """
        获取缓存,如果不存在则通过工厂函数创建并缓存

        Args:
            prefix: 缓存前缀
            key: 缓存键
            factory_func: 异步工厂函数,用于生成缓存数据
            ttl_seconds: 过期时间(秒)
            session: 可选的数据库会话

        Returns:
            缓存的数据
        """
        # 先尝试获取
        cached_data = await self.get(prefix, key, session)
        if cached_data is not None:
            return cached_data

        # 使用锁防止并发创建
        async with self._lock:
            # 双重检查
            cached_data = await self.get(prefix, key, session)
            if cached_data is not None:
                return cached_data

            # 调用工厂函数生成数据
            new_data = await factory_func()

            # 缓存数据
            await self.set(prefix, key, new_data, ttl_seconds, session)

            return new_data

