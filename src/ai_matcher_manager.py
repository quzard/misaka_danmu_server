"""
AI匹配管理器

提供统一的AI匹配接口,管理AI匹配器的创建和使用
"""

import logging
from typing import Optional, Dict, Any, List
from .ai_matcher import AIMatcher, DEFAULT_AI_MATCH_PROMPT
from .config_manager import ConfigManager


class AIMatcherManager:
    """AI匹配管理器"""
    
    def __init__(self, config_manager: ConfigManager):
        """
        初始化AI匹配管理器
        
        Args:
            config_manager: 配置管理器实例
        """
        self.config_manager = config_manager
        self.logger = logging.getLogger(self.__class__.__name__)
        self._matcher_cache: Optional[AIMatcher] = None
        self._last_config_hash: Optional[str] = None
    
    async def is_enabled(self) -> bool:
        """
        检查AI匹配是否启用
        
        Returns:
            True if enabled, False otherwise
        """
        enabled = await self.config_manager.get("aiMatchEnabled", "false")
        return enabled.lower() == "true"
    
    async def _get_config(self) -> Dict[str, Any]:
        """
        获取AI匹配配置
        
        Returns:
            配置字典
        """
        return {
            "ai_match_provider": await self.config_manager.get("aiProvider", "deepseek"),
            "ai_match_api_key": await self.config_manager.get("aiApiKey", ""),
            "ai_match_base_url": await self.config_manager.get("aiBaseUrl", ""),
            "ai_match_model": await self.config_manager.get("aiModel", "deepseek-chat"),
            "ai_match_prompt": await self.config_manager.get("aiPrompt", ""),
            "ai_log_raw_response": (await self.config_manager.get("aiLogRawResponse", "false")).lower() == "true"
        }
    
    def _config_hash(self, config: Dict[str, Any]) -> str:
        """
        计算配置的哈希值,用于检测配置变化
        
        Args:
            config: 配置字典
        
        Returns:
            配置哈希值
        """
        import hashlib
        import json
        config_str = json.dumps(config, sort_keys=True)
        return hashlib.md5(config_str.encode()).hexdigest()
    
    async def get_matcher(self) -> Optional[AIMatcher]:
        """
        获取AI匹配器实例
        
        如果配置未变化,返回缓存的实例;否则创建新实例
        
        Returns:
            AIMatcher实例,如果配置不完整或创建失败则返回None
        """
        try:
            # 检查是否启用
            if not await self.is_enabled():
                self.logger.debug("AI匹配未启用")
                return None
            
            # 获取配置
            config = await self._get_config()
            
            # 检查必要配置
            if not config["ai_match_api_key"]:
                self.logger.warning("AI匹配已启用但未配置API密钥")
                return None
            
            # 检查配置是否变化
            config_hash = self._config_hash(config)
            if self._matcher_cache and self._last_config_hash == config_hash:
                self.logger.debug("使用缓存的AI匹配器实例")
                return self._matcher_cache
            
            # 创建新实例
            self.logger.info("创建新的AI匹配器实例")
            self._matcher_cache = AIMatcher(config)
            self._last_config_hash = config_hash
            
            return self._matcher_cache
        except Exception as e:
            self.logger.error(f"创建AI匹配器失败: {e}", exc_info=True)
            return None
    
    async def select_best_match(
        self,
        query_info: Dict[str, Any],
        sorted_results: List[Any],
        favorited_info: Dict[str, bool]
    ) -> Optional[int]:
        """
        使用AI选择最佳匹配结果
        
        Args:
            query_info: 查询信息 {"title", "season", "episode", "year", "type"}
            sorted_results: 排序后的搜索结果列表
            favorited_info: 收藏信息
        
        Returns:
            选中的结果索引,如果AI匹配失败或未找到合适结果则返回None
        """
        try:
            matcher = await self.get_matcher()
            if not matcher:
                return None
            
            ai_selected_index = await matcher.select_best_match(
                query_info, sorted_results, favorited_info
            )
            
            if ai_selected_index is not None:
                self.logger.info(f"AI匹配成功选择: 索引 {ai_selected_index}")
            else:
                self.logger.info("AI匹配未找到合适结果")
            
            return ai_selected_index
        except Exception as e:
            self.logger.error(f"AI匹配失败: {e}", exc_info=True)
            return None

