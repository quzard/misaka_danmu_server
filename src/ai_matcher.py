#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI智能匹配模块 - 用于自动选择最佳搜索结果"""

import json
import logging
from typing import List, Dict, Any, Optional
from .models import ProviderSearchInfo

logger = logging.getLogger(__name__)

# 默认提示词
DEFAULT_AI_MATCH_PROMPT = """你是一个专业的影视内容匹配专家。你的任务是从搜索结果列表中选择最匹配用户查询的条目。

**输入格式**:
- query: 用户查询信息 (包含标题、季度、集数、年份等)
- results: 搜索结果列表,每个结果包含:
  - title: 标题
  - type: 类型 (tv_series/movie)
  - season: 季度
  - year: 年份
  - episodeCount: 集数
  - isFavorited: 是否被用户标记为精确源 (重要!)

**匹配规则** (按优先级排序):
1. **精确标记优先**: 如果某个结果的 isFavorited=true,强烈优先选择它 (除非明显不匹配)
2. **标题相似度**: 优先匹配标题相似度最高的条目
3. **季度严格匹配**: 如果指定了季度,必须严格匹配
4. **类型匹配**: 电视剧优先匹配 tv_series,电影优先匹配 movie
5. **年份接近**: 优先选择年份接近的
6. **集数完整**: 如果有多个高度相似的结果,选择集数最完整的

**输出格式**:
返回一个JSON对象,包含:
- index: 最佳匹配结果在列表中的索引 (从0开始)
- confidence: 匹配置信度 (0-100)
- reason: 选择理由 (简短说明,需提及是否因为精确标记而选择)

如果没有合适的匹配,返回 {"index": -1, "confidence": 0, "reason": "无合适匹配"}"""


def _safe_json_loads(text: str) -> Optional[Dict]:
    """安全的JSON解析函数,能处理AI返回的常见错误"""
    if not text:
        return None
    
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(f"JSON直接解析失败: {e}。尝试智能修复...")
        
        # 尝试从markdown代码块中提取JSON
        import re
        match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if match:
            json_str = match.group(1)
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass
        
        # 尝试直接提取第一个完整的JSON对象
        match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        
        logger.error("JSON修复失败")
        return None


# --- 动态导入AI SDK ---
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    logger.debug("OpenAI SDK 未安装")


class AIMatcher:
    """AI智能匹配器"""
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化AI匹配器

        Args:
            config: 配置字典,包含:
                - ai_match_provider: AI提供商 (deepseek/openai)
                - ai_match_api_key: API密钥
                - ai_match_base_url: Base URL (可选)
                - ai_match_model: 模型名称
                - ai_match_prompt: 自定义提示词 (可选)
        """
        self.provider = config.get("ai_match_provider", "deepseek").lower()
        self.api_key = config.get("ai_match_api_key")
        self.base_url = config.get("ai_match_base_url")
        self.model = config.get("ai_match_model")
        self.prompt = config.get("ai_match_prompt") or DEFAULT_AI_MATCH_PROMPT
        
        if not self.api_key:
            raise ValueError("AI Matcher: API Key 未配置")
        
        if not self.model:
            raise ValueError("AI Matcher: 模型名称未配置")
        
        self.client = None
        self._initialize_client()
    
    def _initialize_client(self):
        """根据提供商初始化客户端 (仅支持OpenAI兼容接口)"""
        try:
            if self.provider in ['deepseek', 'openai']:
                if not OPENAI_AVAILABLE:
                    raise ImportError("OpenAI SDK 未安装,请运行: pip install openai")

                # DeepSeek使用OpenAI兼容接口
                if self.provider == 'deepseek' and not self.base_url:
                    self.base_url = "https://api.deepseek.com"

                self.client = OpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url if self.base_url else None
                )
                logger.info(f"AI匹配器初始化成功: {self.provider} ({self.model})")
            else:
                raise ValueError(f"不支持的AI提供商: {self.provider} (仅支持 deepseek, openai)")

        except Exception as e:
            logger.error(f"AI匹配器初始化失败: {e}")
            raise
    
    async def select_best_match(
        self,
        query: Dict[str, Any],
        results: List[ProviderSearchInfo],
        favorited_info: Optional[Dict[str, bool]] = None
    ) -> Optional[int]:
        """
        使用AI从搜索结果中选择最佳匹配
        
        Args:
            query: 查询信息,包含 title, season, episode, year 等
            results: 搜索结果列表
            favorited_info: 精确标记信息 {provider:mediaId -> isFavorited}
        
        Returns:
            最佳匹配结果的索引,如果没有合适的匹配则返回None
        """
        if not results:
            return None
        
        try:
            # 构建输入数据
            results_data = []
            for idx, result in enumerate(results):
                # 检查是否被精确标记
                is_favorited = False
                if favorited_info:
                    key = f"{result.provider}:{result.mediaId}"
                    is_favorited = favorited_info.get(key, False)
                
                results_data.append({
                    "index": idx,
                    "provider": result.provider,
                    "title": result.title,
                    "type": result.type,
                    "season": result.season,
                    "year": result.year,
                    "episodeCount": result.episodeCount,
                    "isFavorited": is_favorited
                })
            
            input_data = {
                "query": query,
                "results": results_data
            }
            
            logger.info(f"AI匹配: 开始分析 {len(results)} 个搜索结果")
            logger.debug(f"查询信息: {query}")
            
            # 调用AI (仅支持OpenAI兼容接口)
            response_data = await self._match_openai(input_data)

            if not response_data:
                logger.warning("AI匹配: 未能获取有效响应")
                return None

            # 检查返回类型
            if not isinstance(response_data, dict):
                logger.error(f"AI匹配: 返回数据类型错误,期望dict,实际为{type(response_data).__name__}: {response_data}")
                return None

            # 解析结果
            index = response_data.get("index", -1)
            confidence = response_data.get("confidence", 0)
            reason = response_data.get("reason", "")

            if index < 0 or index >= len(results):
                logger.info(f"AI匹配: 未找到合适的匹配 (reason: {reason})")
                return None

            selected = results[index]
            logger.info(f"AI匹配: 选择结果 #{index} - {selected.provider}:{selected.title} (置信度: {confidence}%, 理由: {reason})")

            return index
        
        except Exception as e:
            logger.error(f"AI匹配过程中发生错误: {e}", exc_info=True)
            return None
    
    async def _match_openai(self, input_data: Dict[str, Any]) -> Optional[Dict]:
        """使用OpenAI兼容接口进行匹配"""
        if not self.client:
            return None
        
        try:
            user_prompt = json.dumps(input_data, ensure_ascii=False, indent=2)
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
                timeout=30
            )

            content = response.choices[0].message.content
            logger.debug(f"AI原始响应: {content}")

            parsed_data = _safe_json_loads(content)
            if parsed_data:
                logger.debug(f"解析后的数据类型: {type(parsed_data).__name__}, 内容: {parsed_data}")

            return parsed_data

        except Exception as e:
            logger.error(f"OpenAI匹配调用失败: {e}")
            return None
    


