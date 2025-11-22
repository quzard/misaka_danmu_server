"""
AI 响应缓存模块

提供 AI 调用结果的缓存功能,减少重复调用,降低成本
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Optional, Dict

logger = logging.getLogger(__name__)


class AIResponseCache:
    """AI 响应缓存"""
    
    def __init__(self, ttl_seconds: int = 3600, max_size: int = 1000):
        """
        初始化缓存
        
        Args:
            ttl_seconds: 缓存过期时间(秒),默认1小时
            max_size: 最大缓存条目数
        """
        self._cache: Dict[str, tuple[Any, datetime]] = {}
        self.ttl_seconds = ttl_seconds
        self.max_size = max_size
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # 统计信息
        self._hits = 0
        self._misses = 0
    
    def _generate_cache_key(self, method: str, **kwargs) -> str:
        """
        生成缓存键
        
        Args:
            method: 方法名
            **kwargs: 方法参数
        
        Returns:
            缓存键(MD5哈希)
        """
        # 构建缓存数据
        cache_data = {"method": method}
        
        # 添加参数,确保可序列化
        for key, value in kwargs.items():
            if hasattr(value, 'to_dict'):
                # 如果对象有 to_dict 方法,使用它
                cache_data[key] = value.to_dict()
            elif isinstance(value, (list, tuple)):
                # 列表/元组,尝试转换每个元素
                cache_data[key] = [
                    item.to_dict() if hasattr(item, 'to_dict') else str(item)
                    for item in value
                ]
            elif isinstance(value, dict):
                cache_data[key] = value
            else:
                # 其他类型转为字符串
                cache_data[key] = str(value)
        
        # 生成 JSON 字符串并计算 MD5
        cache_str = json.dumps(cache_data, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(cache_str.encode()).hexdigest()
    
    def get(self, method: str, **kwargs) -> Optional[Any]:
        """
        从缓存获取结果
        
        Args:
            method: 方法名
            **kwargs: 方法参数
        
        Returns:
            缓存的结果,如果不存在或已过期则返回 None
        """
        cache_key = self._generate_cache_key(method, **kwargs)
        
        if cache_key in self._cache:
            result, timestamp = self._cache[cache_key]
            
            # 检查是否过期
            if datetime.now() - timestamp < timedelta(seconds=self.ttl_seconds):
                self._hits += 1
                self.logger.debug(f"AI缓存命中: {method} | key={cache_key[:8]}...")
                return result
            else:
                # 过期,删除
                del self._cache[cache_key]
                self.logger.debug(f"AI缓存过期: {method} | key={cache_key[:8]}...")
        
        self._misses += 1
        return None
    
    def set(self, result: Any, method: str, **kwargs):
        """
        设置缓存
        
        Args:
            result: 要缓存的结果
            method: 方法名
            **kwargs: 方法参数
        """
        cache_key = self._generate_cache_key(method, **kwargs)
        
        # 如果缓存已满,删除最旧的条目
        if len(self._cache) >= self.max_size:
            oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][1])
            del self._cache[oldest_key]
            self.logger.debug(f"AI缓存已满,删除最旧条目: {oldest_key[:8]}...")
        
        self._cache[cache_key] = (result, datetime.now())
        self.logger.debug(f"AI缓存设置: {method} | key={cache_key[:8]}...")
    
    def clear(self):
        """清空缓存"""
        self._cache.clear()
        self._hits = 0
        self._misses = 0
        self.logger.info("AI缓存已清空")
    
    def get_stats(self) -> Dict:
        """
        获取缓存统计信息
        
        Returns:
            统计信息字典
        """
        total_requests = self._hits + self._misses
        hit_rate = self._hits / total_requests if total_requests > 0 else 0.0
        
        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "ttl_seconds": self.ttl_seconds,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": hit_rate
        }
    
    def cleanup_expired(self):
        """清理过期的缓存条目"""
        now = datetime.now()
        expired_keys = [
            key for key, (_, timestamp) in self._cache.items()
            if now - timestamp >= timedelta(seconds=self.ttl_seconds)
        ]
        
        for key in expired_keys:
            del self._cache[key]
        
        if expired_keys:
            self.logger.info(f"清理了 {len(expired_keys)} 个过期的AI缓存条目")

