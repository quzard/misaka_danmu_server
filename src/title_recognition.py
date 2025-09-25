"""
标题识别词功能模块
用于解析和应用标题识别词转换规则
"""
import os
import logging
import re
from typing import Dict, Tuple, Optional
from sqlalchemy.orm import Session
from sqlalchemy import delete
from .database import get_db_session
from .orm_models import TitleRecognition
from .timezone import get_now

logger = logging.getLogger(__name__)

class TitleRecognitionManager:
    """标题识别词管理器"""
    
    def __init__(self, session_factory):
        """
        初始化识别词管理器
        
        Args:
            session_factory: 数据库会话工厂
        """
        self.session_factory = session_factory
        self.recognition_rules = {}
        self._load_recognition_rules()

    def _load_recognition_rules(self):
        """
        从数据库加载识别词规则，使用全量替换模式
        """
        try:
            # 创建同步会话来加载规则
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            async def load_rules():
                async with self.session_factory() as session:
                    # 获取最新的识别词配置（只有一条记录）
                    result = await session.execute(
                         select(orm_models.TitleRecognition).limit(1)
                     )
                    title_recognition = result.scalar_one_or_none()
                    
                    if title_recognition is None:
                        logger.info("数据库中未找到识别词配置，使用空规则集")
                        return {}
                    
                    return self._parse_recognition_content(title_recognition.content)
            
            self.recognition_rules = loop.run_until_complete(load_rules())
            loop.close()
            
            logger.info(f"从数据库加载了 {len(self.recognition_rules)} 条识别词规则")
            
        except Exception as e:
            logger.error(f"从数据库加载识别词规则失败: {e}")
            self.recognition_rules = {}
    
    def _parse_recognition_content(self, content):
        """
        解析识别词配置内容
        
        Args:
            content: 识别词配置文本内容
            
        Returns:
            dict: 解析后的识别词规则字典
        """
        rules = {}
        
        if not content:
            return rules
        
        lines = content.split('\n')
        
        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            # 解析格式: "原标题 S季数 => 目标标题 S目标季数"
            if ' => ' not in line:
                logger.warning(f"识别词配置第{line_num}行格式错误，跳过: {line}")
                continue
            
            try:
                source_part, target_part = line.split(' => ', 1)
                source_part = source_part.strip()
                target_part = target_part.strip()
                
                # 解析源部分
                if ' S' not in source_part:
                    logger.warning(f"识别词配置第{line_num}行源部分格式错误，跳过: {line}")
                    continue
                
                source_title_part, source_season_part = source_part.rsplit(' S', 1)
                source_title = source_title_part.strip()
                
                try:
                    source_season = int(source_season_part.strip())
                except ValueError:
                    logger.warning(f"识别词配置第{line_num}行源季数格式错误，跳过: {line}")
                    continue
                
                # 解析目标部分
                if ' S' not in target_part:
                    logger.warning(f"识别词配置第{line_num}行目标部分格式错误，跳过: {line}")
                    continue
                
                target_title_part, target_season_part = target_part.rsplit(' S', 1)
                target_title = target_title_part.strip()
                
                try:
                    target_season = int(target_season_part.strip())
                except ValueError:
                    logger.warning(f"识别词配置第{line_num}行目标季数格式错误，跳过: {line}")
                    continue
                
                # 构建规则键
                rule_key = f"{source_title}|{source_season}"
                rules[rule_key] = (target_title, target_season)
                
                logger.debug(f"解析识别词规则: {source_title} S{source_season:02d} => {target_title} S{target_season:02d}")
            
            except Exception as e:
                logger.warning(f"识别词配置第{line_num}行解析失败，跳过: {line}, 错误: {e}")
                continue
        
        return rules

    async def update_recognition_rules(self, content):
        """
        更新识别词规则，使用全量替换模式
        
        Args:
            content: 新的识别词配置内容
        """
        try:
            async with self.session_factory() as session:
                # 删除所有现有记录
                await session.execute(delete(TitleRecognition))
                
                # 插入新的配置记录
                new_recognition = TitleRecognition(content=content)
                session.add(new_recognition)
                
                await session.commit()
                
                # 重新加载规则到内存
                self.recognition_rules = self._parse_recognition_content(content)
                
                logger.info(f"成功更新识别词规则，共 {len(self.recognition_rules)} 条规则")
                
        except Exception as e:
            logger.error(f"更新识别词规则失败: {e}")
            raise
    
    def _normalize_title(self, title: str) -> str:
        """
        标准化标题，移除季数相关的后缀
        
        Args:
            title: 原始标题
            
        Returns:
            标准化后的标题
        """
        # 移除常见的季数表示：第X季、第X部、Season X等
        patterns = [
            r'\s*第\d+季\s*$',      # 第1季、第2季等
            r'\s*第\d+部\s*$',      # 第1部、第2部等
            r'\s*Season\s*\d+\s*$', # Season 1、Season 2等
            r'\s*S\d+\s*$'         # S1、S2等
        ]
        
        normalized_title = title
        for pattern in patterns:
            normalized_title = re.sub(pattern, '', normalized_title, flags=re.IGNORECASE)
        
        return normalized_title.strip()

    def apply_title_recognition(self, anime_title: str, season: Optional[int]) -> Tuple[str, Optional[int], bool]:
        """
        应用标题识别词转换
        
        Args:
            anime_title: 原始动画标题
            season: 原始季数
            
        Returns:
            Tuple[转换后的标题, 转换后的季数, 是否发生了转换]
        """
        if not anime_title or season is None:
            return anime_title, season, False
        
        # 先尝试精确匹配
        rule_key = f"{anime_title}|{season}"
        if rule_key in self.recognition_rules:
            target_title, target_season = self.recognition_rules[rule_key]
            logger.info(f"应用标题识别词转换(精确匹配): {anime_title} S{season:02d} => {target_title} S{target_season:02d}")
            return target_title, target_season, True
        
        # 如果精确匹配失败，尝试标准化标题后匹配
        normalized_title = self._normalize_title(anime_title)
        if normalized_title != anime_title:
            normalized_rule_key = f"{normalized_title}|{season}"
            if normalized_rule_key in self.recognition_rules:
                target_title, target_season = self.recognition_rules[normalized_rule_key]
                logger.info(f"应用标题识别词转换(标准化匹配): {anime_title} -> {normalized_title} S{season:02d} => {target_title} S{target_season:02d}")
                return target_title, target_season, True
        
        return anime_title, season, False