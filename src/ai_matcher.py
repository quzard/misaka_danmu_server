#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI智能匹配模块 - 用于自动选择最佳搜索结果"""

import json
import logging
from typing import List, Dict, Any, Optional
from .models import ProviderSearchInfo

logger = logging.getLogger(__name__)

# 默认匹配提示词
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

# 默认识别提示词
DEFAULT_AI_RECOGNITION_PROMPT = """你是一个专业的影视标题格式纠正与匹配选择专家。你的任务是:
1. 将数据库中的标题信息标准化,生成最适合TMDB搜索的查询关键词
2. 识别作品的季度信息,用于后续的剧集组匹配选择

**背景说明**:
- 输入来源: 数据库中的 Anime.title, Anime.year, Anime.type 字段
- 目标: 输出标准化的搜索关键词 + 季度信息,用于TMDB搜索和剧集组匹配
- 应用场景: TMDB自动刮削定时任务,批量为库内作品获取TMDB ID并匹配剧集组

**输入格式**:
- title: 数据库中的标题 (可能格式不规范,包含季度信息等)
- year: 年份 (整数或null)
- type: 类型 ("tv_series" 或 "movie")

**纠正规则**:
1. **标题标准化** (最重要):
   - 去除季度标记: "第X季", "Season X", "S0X", "Part X"等
   - 去除年份信息 (年份已单独提供)
   - 去除多余空格和标点符号
   - 如果标题同时包含中文和英文/日文,优先保留**更完整、更官方**的版本
   - 如果标题包含罗马音和中文,优先保留中文
   - 输出的标题应该是**作品的核心名称**,适合TMDB搜索

2. **季度提取** (重要,用于剧集组匹配):
   - 从标题中识别季度: "第X季", "Season X", "S0X", "Part X"等
   - 罗马数字: "II"=2, "III"=3, "IV"=4
   - **特别季**: "OVA", "OAD", "SP", "特别篇" → season=0 (第0季)
   - 如果无法确定,返回null

3. **类型纠错** (重要):
   - 如果标题包含"剧场版"、"Movie"、"电影"等关键词,**纠正为"movie"** (即使输入type为tv_series)
   - 如果标题包含"OVA"、"OAD"、"SP"、"特别篇"等,保持"tv_series"
   - 如果标题明显是电视剧但输入type为movie,**纠正为"tv_series"**
   - 否则使用输入的type值

4. **年份纠错** (重要):
   - 如果标题中包含明确的年份信息,**优先使用标题中的年份** (即使与输入year不同)
   - 如果输入的year明显错误 (如1900, 2099等异常值),尝试从标题或常识推断正确年份
   - 如果无法确定,使用输入的year值

**剧集组识别与匹配** (针对特殊作品):
某些作品在TMDB中不分季,而是使用剧集组(Episode Groups)来组织不同季度。
需要识别这类作品并标记:
- 日本动画作品,标题包含"第X季"但在TMDB中通常只有一个TV系列
- 例如: "Re:Zero"、"从零开始的异世界生活"、"某科学的超电磁炮"等
- 如果识别到这类作品,设置 use_episode_group=true
- 剧集组从第0季开始: 第0季=特别季(OVA/SP), 第1季=正片第一季, 第2季=正片第二季...

**输出格式**:
返回一个JSON对象,包含:
- search_title: 标准化的搜索关键词 (字符串,用于TMDB搜索)
- season: 季度 (整数,用于筛选搜索结果或剧集组,无法确定则为null)
- type: 类型 ("tv_series" 或 "movie")
- year: 年份 (整数,没有则为null)
- use_episode_group: 是否需要使用剧集组 (布尔值,默认false)
- episode_title_cn: 集标题(中文) (字符串,仅当season=0时需要,用于匹配第0季中的具体集)
- episode_title_jp: 集标题(日文) (字符串,仅当season=0时需要,用于匹配第0季中的具体集)

**示例**:
输入: {"title": "魔法使的新娘 第二季", "year": 2023, "type": "tv_series"}
输出: {"search_title": "魔法使的新娘", "season": 2, "type": "tv_series", "year": 2023, "use_episode_group": false}

输入: {"title": "Re:Zero kara Hajimeru Isekai Seikatsu 2nd Season", "year": 2020, "type": "tv_series"}
输出: {"search_title": "Re:Zero kara Hajimeru Isekai Seikatsu", "season": 2, "type": "tv_series", "year": 2020, "use_episode_group": true}
(剧集组识别: Re:Zero在TMDB中不分季,需要使用剧集组)

输入: {"title": "从零开始的异世界生活 第三季", "year": 2024, "type": "tv_series"}
输出: {"search_title": "从零开始的异世界生活", "season": 3, "type": "tv_series", "year": 2024, "use_episode_group": true}
(剧集组识别: 该作品在TMDB中使用剧集组组织)

输入: {"title": "某科学的超电磁炮 OVA", "year": 2010, "type": "tv_series"}
输出: {
  "search_title": "某科学的超电磁炮",
  "season": 0,
  "type": "tv_series",
  "year": 2010,
  "use_episode_group": true,
  "episode_title_cn": "OVA",
  "episode_title_jp": null
}
(特别季识别: OVA对应第0季,提取集标题用于匹配Specials中的具体集)

输入: {"title": "葬送的芙莉莲 剧场版", "year": null, "type": "tv_series"}
输出: {"search_title": "葬送的芙莉莲", "season": null, "type": "movie", "year": null, "use_episode_group": false}
(纠错: 标题包含"剧场版",type从tv_series纠正为movie)

输入: {"title": "进击的巨人 最终季", "year": 2020, "type": "tv_series"}
输出: {"search_title": "进击的巨人", "season": null, "type": "tv_series", "year": 2020, "use_episode_group": false}

输入: {"title": "Frieren: Beyond Journey's End", "year": 2023, "type": "tv_series"}
输出: {"search_title": "Frieren: Beyond Journey's End", "season": null, "type": "tv_series", "year": 2023, "use_episode_group": false}

输入: {"title": "你的名字 (2016)", "year": 2020, "type": "tv_series"}
输出: {"search_title": "你的名字", "season": null, "type": "movie", "year": 2016, "use_episode_group": false}
(纠错: 标题中年份2016覆盖错误的2020,根据常识判断为电影)"""

# 默认别名验证提示词
DEFAULT_AI_ALIAS_VALIDATION_PROMPT = """你是一个专业的动漫作品别名验证与分类专家。你的任务是:
1. 验证一组别名是否真正属于指定作品
2. 识别每个别名的语言类型(英文/日文/罗马音/中文)
3. 选择最官方的别名填入对应字段

**输入格式**:
- title: 作品标题
- year: 年份 (可能为null)
- type: 类型 (tv_series/movie)
- aliases: 待验证的别名列表

**验证规则**:
1. **真实性验证**: 只保留真正属于这个作品的别名,丢弃不相关的
2. **语言识别**: 识别每个别名的语言类型
   - 英文: 英语标题
   - 日文: 日语标题(包含假名或汉字)
   - 罗马音: 日语的罗马字拼写
   - 中文: 简体中文、繁体中文标题
3. **官方性优先**: 每种语言只选1个最官方的别名
4. **中文别名**: 最多保留3个,按官方程度排序
5. **标点符号与分隔符处理**:
   - 英文冒号(:)、中文冒号(：)、空格( )在标题中可能互换使用
   - 例如: "创:战纪"、"创：战纪"、"创 战纪" 都可能是同一作品的不同写法
   - 选择最官方或最常用的版本
   - 如果无法确定,优先级: 英文冒号(:) > 中文冒号(：) > 空格( )

**输出格式**:
返回一个JSON对象,包含:
- nameEn: 英文名 (字符串,只选1个最官方的,没有则为null)
- nameJp: 日文名 (字符串,只选1个最官方的,没有则为null)
- nameRomaji: 罗马音 (字符串,只选1个,没有则为null)
- aliasesCn: 中文别名数组 (最多3个,按官方程度排序,没有则为空数组)

**示例**:

输入: {
  "title": "葬送的芙莉莲",
  "year": 2023,
  "type": "tv_series",
  "aliases": [
    "Frieren: Beyond Journey's End",
    "葬送のフリーレン",
    "Sousou no Frieren",
    "葬送的芙莉莲",
    "芙莉莲",
    "葬送",
    "Frieren",
    "进击的巨人"
  ]
}
输出: {
  "nameEn": "Frieren: Beyond Journey's End",
  "nameJp": "葬送のフリーレン",
  "nameRomaji": "Sousou no Frieren",
  "aliasesCn": ["葬送的芙莉莲", "芙莉莲"]
}
(丢弃: "葬送"太短不完整, "Frieren"不完整, "进击的巨人"不相关)

输入: {
  "title": "Re:从零开始的异世界生活",
  "year": 2016,
  "type": "tv_series",
  "aliases": [
    "Re:Zero - Starting Life in Another World",
    "Re:ゼロから始める異世界生活",
    "Re:Zero kara Hajimeru Isekai Seikatsu",
    "从零开始的异世界生活",
    "Re:从零开始的异世界生活",
    "Re0",
    "リゼロ"
  ]
}
输出: {
  "nameEn": "Re:Zero - Starting Life in Another World",
  "nameJp": "Re:ゼロから始める異世界生活",
  "nameRomaji": "Re:Zero kara Hajimeru Isekai Seikatsu",
  "aliasesCn": ["Re:从零开始的异世界生活", "从零开始的异世界生活"]
}
(丢弃: "Re0"和"リゼロ"是缩写,不够官方)

输入: {
  "title": "你的名字",
  "year": 2016,
  "type": "movie",
  "aliases": [
    "Your Name",
    "君の名は。",
    "Kimi no Na wa",
    "你的名字",
    "你的名字。",
    "妳的名字",
    "Weathering with You"
  ]
}
输出: {
  "nameEn": "Your Name",
  "nameJp": "君の名は。",
  "nameRomaji": "Kimi no Na wa",
  "aliasesCn": ["你的名字。", "你的名字", "妳的名字"]
}
(丢弃: "Weathering with You"是另一部作品)"""


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
                - ai_match_prompt: 自定义匹配提示词 (可选)
                - ai_recognition_prompt: 自定义识别提示词 (可选)
                - ai_alias_validation_prompt: 自定义别名验证提示词 (可选)
        """
        self.provider = config.get("ai_match_provider", "deepseek").lower()
        self.api_key = config.get("ai_match_api_key")
        self.base_url = config.get("ai_match_base_url")
        self.model = config.get("ai_match_model")

        # 提示词配置: 优先使用传入的配置,如果为空则使用硬编码的默认值
        self.match_prompt = config.get("ai_match_prompt")
        if not self.match_prompt:
            self.match_prompt = DEFAULT_AI_MATCH_PROMPT

        self.recognition_prompt = config.get("ai_recognition_prompt")
        if not self.recognition_prompt:
            self.recognition_prompt = DEFAULT_AI_RECOGNITION_PROMPT

        self.alias_validation_prompt = config.get("ai_alias_validation_prompt")
        if not self.alias_validation_prompt:
            self.alias_validation_prompt = DEFAULT_AI_ALIAS_VALIDATION_PROMPT
        
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
                    {"role": "system", "content": self.match_prompt},
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

    async def recognize_title(self, title: str, year: Optional[int] = None, anime_type: str = "tv_series") -> Optional[Dict[str, Any]]:
        """
        使用AI将标题信息标准化,生成适合TMDB搜索的查询关键词

        Args:
            title: 标题字符串
            year: 年份 (可选)
            anime_type: 类型 ("tv_series" 或 "movie")

        Returns:
            标准化后的信息,包含 search_title, season, type, year 等字段
            如果识别失败则返回None
        """
        if not title:
            return None

        try:
            input_data = {
                "title": title,
                "year": year,
                "type": anime_type
            }
            logger.info(f"AI识别: 开始标准化标题 - {input_data}")

            # 调用AI
            response_data = await self._recognize_openai(input_data)

            if not response_data:
                logger.warning("AI识别: 未能获取有效响应")
                return None

            # 检查返回类型
            if not isinstance(response_data, dict):
                logger.error(f"AI识别: 返回数据类型错误,期望dict,实际为{type(response_data).__name__}: {response_data}")
                return None

            # 验证必需字段
            if "search_title" not in response_data:
                logger.error(f"AI识别: 返回数据缺少search_title字段: {response_data}")
                return None

            logger.info(f"AI识别: 标准化成功 - {response_data}")
            return response_data

        except Exception as e:
            logger.error(f"AI识别过程中发生错误: {e}", exc_info=True)
            return None

    async def _recognize_openai(self, input_data: Dict[str, Any]) -> Optional[Dict]:
        """使用OpenAI兼容接口进行识别"""
        if not self.client:
            return None

        try:
            import json
            user_prompt = json.dumps(input_data, ensure_ascii=False, indent=2)

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.recognition_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
                timeout=30
            )

            content = response.choices[0].message.content
            logger.debug(f"AI识别原始响应: {content}")

            parsed_data = _safe_json_loads(content)
            if parsed_data:
                logger.debug(f"解析后的数据类型: {type(parsed_data).__name__}, 内容: {parsed_data}")

            return parsed_data

        except Exception as e:
            logger.error(f"OpenAI识别调用失败: {e}")
            return None

    def validate_aliases(
        self,
        title: str,
        year: Optional[int],
        anime_type: str,
        aliases: List[str],
        custom_prompt: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        使用AI验证并分类别名

        Args:
            title: 作品标题
            year: 年份
            anime_type: 类型 (tv_series/movie)
            aliases: 待验证的别名列表
            custom_prompt: 自定义提示词 (可选,优先级高于实例配置)

        Returns:
            {
                "nameEn": "英文名",
                "nameJp": "日文名",
                "nameRomaji": "罗马音",
                "aliasesCn": ["中文别名1", "中文别名2", "中文别名3"]
            }
            如果失败返回None
        """
        if not self.client:
            logger.error("AI客户端未初始化")
            return None

        if not aliases:
            logger.warning("别名列表为空,跳过验证")
            return None

        try:
            # 使用自定义提示词 > 实例配置 > 默认提示词
            validation_prompt = custom_prompt or self.alias_validation_prompt

            # 构建输入数据
            input_data = {
                "title": title,
                "year": year,
                "type": anime_type,
                "aliases": aliases
            }

            logger.info(f"正在使用AI验证别名: title='{title}', aliases={len(aliases)}个")
            logger.debug(f"AI别名验证输入: {input_data}")

            import json
            user_prompt = json.dumps(input_data, ensure_ascii=False, indent=2)

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": validation_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
                timeout=30
            )

            content = response.choices[0].message.content
            logger.debug(f"AI别名验证原始响应: {content}")

            parsed_data = _safe_json_loads(content)
            if parsed_data:
                logger.info(f"AI别名验证成功: nameEn={parsed_data.get('nameEn')}, nameJp={parsed_data.get('nameJp')}, nameRomaji={parsed_data.get('nameRomaji')}, aliasesCn={len(parsed_data.get('aliasesCn', []))}个")
                logger.debug(f"解析后的数据: {parsed_data}")

            return parsed_data

        except Exception as e:
            logger.error(f"AI别名验证失败: {e}")
            return None


