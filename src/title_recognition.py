"""
标题识别词功能模块
用于解析和应用标题识别词转换规则
参考MoviePilot的识别词格式实现
"""
import os
import logging
import re
from typing import Dict, Tuple, Optional, List, Any, Union
from sqlalchemy.orm import Session
from sqlalchemy import delete, select
from .database import get_db_session
from .orm_models import TitleRecognition
from .timezone import get_now

logger = logging.getLogger(__name__)

class TitleRecognitionRule:
    """识别词规则类"""

    def __init__(self, rule_type: str, **kwargs):
        self.rule_type = rule_type  # 'block', 'replace', 'offset', 'complex'
        self.data = kwargs

class TitleRecognitionManager:
    """标题识别词管理器 - 参考MoviePilot格式"""

    def __init__(self, session_factory):
        """
        初始化识别词管理器

        Args:
            session_factory: 数据库会话工厂
        """
        self.session_factory = session_factory
        self.recognition_rules: List[TitleRecognitionRule] = []
        self._load_recognition_rules()

    def _load_recognition_rules(self):
        """
        从数据库加载识别词规则
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
                         select(TitleRecognition).limit(1)
                     )
                    title_recognition = result.scalar_one_or_none()

                    if title_recognition is None:
                        logger.info("数据库中未找到识别词配置，使用空规则集")
                        return []

                    return self._parse_recognition_content(title_recognition.content)

            self.recognition_rules = loop.run_until_complete(load_rules())
            loop.close()

            logger.info(f"从数据库加载了 {len(self.recognition_rules)} 条识别词规则")

        except Exception as e:
            logger.error(f"从数据库加载识别词规则失败: {e}")
            self.recognition_rules = []
    
    def _parse_recognition_content(self, content: str) -> List[TitleRecognitionRule]:
        """
        解析识别词配置内容 - 参考MoviePilot格式

        支持的格式：
        1. 屏蔽词: 屏蔽词
        2. 简单替换: 被替换词 => 替换词
        3. 集数偏移: 前定位词 <> 后定位词 >> 集偏移量
        4. 复合格式: 被替换词 => 替换词 && 前定位词 <> 后定位词 >> 集偏移量

        Args:
            content: 识别词配置文本内容

        Returns:
            List[TitleRecognitionRule]: 解析后的识别词规则列表
        """
        rules = []

        if not content:
            return rules

        lines = content.split('\n')

        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            try:
                rule = self._parse_single_rule(line, line_num)
                if rule:
                    rules.append(rule)
            except Exception as e:
                logger.warning(f"识别词配置第{line_num}行解析失败，跳过: {line}, 错误: {e}")
                continue

        return rules

    def _parse_single_rule(self, line: str, line_num: int) -> Optional[TitleRecognitionRule]:
        """
        解析单个识别词规则

        Args:
            line: 规则行内容
            line_num: 行号

        Returns:
            TitleRecognitionRule: 解析后的规则对象，解析失败返回None
        """
        # 检查是否包含复合格式标识符
        has_replace = ' => ' in line
        has_offset = ' <> ' in line and ' >> ' in line
        has_complex = has_replace and ' && ' in line

        if has_complex:
            # 复合格式: 被替换词 => 替换词 && 前定位词 <> 后定位词 >> 集偏移量
            return self._parse_complex_rule(line, line_num)
        elif has_replace:
            # 简单替换: 被替换词 => 替换词
            return self._parse_replace_rule(line, line_num)
        elif has_offset:
            # 集数偏移: 前定位词 <> 后定位词 >> 集偏移量
            return self._parse_offset_rule(line, line_num)
        else:
            # 屏蔽词: 屏蔽词
            return self._parse_block_rule(line, line_num)

    def _parse_block_rule(self, line: str, line_num: int) -> Optional[TitleRecognitionRule]:
        """解析屏蔽词规则"""
        block_word = line.strip()
        if not block_word:
            logger.warning(f"识别词配置第{line_num}行屏蔽词为空，跳过: {line}")
            return None

        logger.debug(f"解析屏蔽词规则: {block_word}")
        return TitleRecognitionRule('block', word=block_word)

    def _parse_replace_rule(self, line: str, line_num: int) -> Optional[TitleRecognitionRule]:
        """解析简单替换规则"""
        if ' => ' not in line:
            return None

        parts = line.split(' => ', 1)
        if len(parts) != 2:
            logger.warning(f"识别词配置第{line_num}行替换格式错误，跳过: {line}")
            return None

        source = parts[0].strip()
        target = parts[1].strip()

        if not source or not target:
            logger.warning(f"识别词配置第{line_num}行替换词为空，跳过: {line}")
            return None

        # 检查是否是特殊格式 {[tmdbid/doubanid=xxx;type=movie/tv;s=xxx;e=xxx]}
        if target.startswith('{[') and target.endswith(']}'):
            metadata_info = self._parse_metadata_target(target)
            if metadata_info:
                logger.debug(f"解析元数据替换规则: {source} => {target}")
                return TitleRecognitionRule('metadata_replace', source=source, **metadata_info)

        logger.debug(f"解析简单替换规则: {source} => {target}")
        return TitleRecognitionRule('replace', source=source, target=target)

    def _parse_offset_rule(self, line: str, line_num: int) -> Optional[TitleRecognitionRule]:
        """解析集数偏移规则"""
        if ' <> ' not in line or ' >> ' not in line:
            return None

        # 分割: 前定位词 <> 后定位词 >> 集偏移量
        parts = line.split(' >> ', 1)
        if len(parts) != 2:
            logger.warning(f"识别词配置第{line_num}行偏移格式错误，跳过: {line}")
            return None

        locator_part = parts[0].strip()
        offset_part = parts[1].strip()

        if ' <> ' not in locator_part:
            logger.warning(f"识别词配置第{line_num}行定位词格式错误，跳过: {line}")
            return None

        locator_parts = locator_part.split(' <> ', 1)
        before_locator = locator_parts[0].strip()
        after_locator = locator_parts[1].strip()

        logger.debug(f"解析集数偏移规则: {before_locator} <> {after_locator} >> {offset_part}")
        return TitleRecognitionRule('offset',
                                   before_locator=before_locator,
                                   after_locator=after_locator,
                                   offset=offset_part)

    def _parse_complex_rule(self, line: str, line_num: int) -> Optional[TitleRecognitionRule]:
        """解析复合规则"""
        if ' && ' not in line:
            return None

        # 分割: 被替换词 => 替换词 && 前定位词 <> 后定位词 >> 集偏移量
        parts = line.split(' && ', 1)
        if len(parts) != 2:
            logger.warning(f"识别词配置第{line_num}行复合格式错误，跳过: {line}")
            return None

        replace_part = parts[0].strip()
        offset_part = parts[1].strip()

        # 解析替换部分
        replace_rule = self._parse_replace_rule(replace_part, line_num)
        if not replace_rule:
            return None

        # 解析偏移部分
        offset_rule = self._parse_offset_rule(offset_part, line_num)
        if not offset_rule:
            return None

        logger.debug(f"解析复合规则: {line}")
        return TitleRecognitionRule('complex',
                                   source=replace_rule.data['source'],
                                   target=replace_rule.data['target'],
                                   before_locator=offset_rule.data['before_locator'],
                                   after_locator=offset_rule.data['after_locator'],
                                   offset=offset_rule.data['offset'])

    def _parse_metadata_target(self, target: str) -> Optional[Dict[str, Any]]:
        """
        解析元数据目标格式: {[tmdbid/doubanid=xxx;type=movie/tv;s=xxx;e=xxx]}

        Args:
            target: 目标字符串

        Returns:
            Dict: 解析后的元数据信息
        """
        if not target.startswith('{[') or not target.endswith(']}'):
            return None

        content = target[2:-2]  # 移除 {[ 和 ]}
        metadata = {}

        for part in content.split(';'):
            if '=' not in part:
                continue
            key, value = part.split('=', 1)
            key = key.strip()
            value = value.strip()

            if key in ['tmdbid', 'doubanid']:
                try:
                    metadata[key] = int(value)
                except ValueError:
                    continue
            elif key in ['type', 's', 'e']:
                metadata[key] = value

        return metadata if metadata else None

    async def update_recognition_rules(self, content: str):
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
    
    def apply_title_recognition(self, text: str, episode: Optional[int] = None) -> Tuple[str, Optional[int], bool, Optional[Dict[str, Any]]]:
        """
        应用标题识别词转换 - 参考MoviePilot格式

        Args:
            text: 原始文本（标题或文件名）
            episode: 原始集数

        Returns:
            Tuple[转换后的文本, 转换后的集数, 是否发生了转换, 元数据信息]
        """
        if not text:
            return text, episode, False, None

        processed_text = text
        processed_episode = episode
        has_changed = False
        metadata_info = None

        # 按顺序应用所有规则
        for rule in self.recognition_rules:
            if rule.rule_type == 'block':
                # 屏蔽词：从文本中移除
                if rule.data['word'] in processed_text:
                    processed_text = processed_text.replace(rule.data['word'], '').strip()
                    has_changed = True
                    logger.debug(f"应用屏蔽词规则: 移除 '{rule.data['word']}'")

            elif rule.rule_type == 'replace':
                # 简单替换
                if rule.data['source'] in processed_text:
                    processed_text = processed_text.replace(rule.data['source'], rule.data['target'])
                    has_changed = True
                    logger.debug(f"应用替换规则: '{rule.data['source']}' => '{rule.data['target']}'")

            elif rule.rule_type == 'metadata_replace':
                # 元数据替换
                if rule.data['source'] in processed_text:
                    processed_text = processed_text.replace(rule.data['source'], '')
                    metadata_info = {k: v for k, v in rule.data.items() if k != 'source'}
                    has_changed = True
                    logger.debug(f"应用元数据替换规则: '{rule.data['source']}' => 元数据")

            elif rule.rule_type == 'offset':
                # 集数偏移
                new_episode = self._apply_episode_offset(processed_text, processed_episode, rule)
                if new_episode != processed_episode:
                    processed_episode = new_episode
                    has_changed = True

            elif rule.rule_type == 'complex':
                # 复合规则：先替换，再偏移
                if rule.data['source'] in processed_text:
                    processed_text = processed_text.replace(rule.data['source'], rule.data['target'])
                    new_episode = self._apply_episode_offset_with_locators(
                        processed_text, processed_episode,
                        rule.data['before_locator'],
                        rule.data['after_locator'],
                        rule.data['offset']
                    )
                    if new_episode != processed_episode:
                        processed_episode = new_episode
                    has_changed = True
                    logger.debug(f"应用复合规则: '{rule.data['source']}' => '{rule.data['target']}' + 集数偏移")

        return processed_text, processed_episode, has_changed, metadata_info

    def _apply_episode_offset(self, text: str, episode: Optional[int], rule: TitleRecognitionRule) -> Optional[int]:
        """应用集数偏移规则"""
        return self._apply_episode_offset_with_locators(
            text, episode,
            rule.data['before_locator'],
            rule.data['after_locator'],
            rule.data['offset']
        )

    def _apply_episode_offset_with_locators(self, text: str, episode: Optional[int],
                                          before_locator: str, after_locator: str,
                                          offset: str) -> Optional[int]:
        """
        使用定位词应用集数偏移

        Args:
            text: 文本内容
            episode: 当前集数
            before_locator: 前定位词
            after_locator: 后定位词
            offset: 偏移表达式

        Returns:
            计算后的集数
        """
        # 查找定位词之间的内容
        pattern = re.escape(before_locator) + r'(.*?)' + re.escape(after_locator)
        match = re.search(pattern, text)

        if not match:
            return episode

        content = match.group(1)

        # 提取数字（包括中文小写数字）
        numbers = self._extract_numbers(content)
        if not numbers:
            return episode

        # 使用第一个数字作为集数
        ep = numbers[0]

        # 计算偏移
        try:
            if offset.startswith('EP'):
                # 使用EP变量的表达式
                offset_expr = offset.replace('EP', str(ep))
                new_episode = eval(offset_expr)
            else:
                # 简单的数字偏移
                offset_value = int(offset)
                new_episode = ep + offset_value

            logger.debug(f"集数偏移计算: {ep} + ({offset}) = {new_episode}")
            return max(1, int(new_episode))  # 确保集数不小于1

        except Exception as e:
            logger.warning(f"集数偏移计算失败: {offset}, 错误: {e}")
            return episode

    def _extract_numbers(self, text: str) -> List[int]:
        """
        从文本中提取数字（包括中文小写数字）

        Args:
            text: 文本内容

        Returns:
            提取到的数字列表
        """
        numbers = []

        # 提取阿拉伯数字
        for match in re.finditer(r'\d+', text):
            numbers.append(int(match.group()))

        # 提取中文小写数字
        chinese_numbers = {
            '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
            '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
            '零': 0
        }

        for char in text:
            if char in chinese_numbers:
                numbers.append(chinese_numbers[char])

        return numbers