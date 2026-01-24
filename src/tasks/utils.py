"""任务工具函数模块"""
import logging
import re
from typing import List

logger = logging.getLogger(__name__)


def parse_episode_ranges(episode_str: str) -> List[int]:
    """
    解析集数范围字符串，支持多种格式：
    - 单集: "1"
    - 范围: "1-3"
    - 混合: "1,3,5,7,9,11-13"

    返回所有集数的列表
    """
    episodes = []

    # 移除所有空格
    episode_str = episode_str.replace(" ", "")

    # 按逗号分割
    parts = episode_str.split(",")

    for part in parts:
        if "-" in part:
            # 处理范围，如 "1-3" 或 "31-39"
            try:
                start, end = part.split("-", 1)
                start_num = int(start)
                end_num = int(end)
                episodes.extend(range(start_num, end_num + 1))
            except (ValueError, IndexError) as e:
                logger.warning(f"无法解析集数范围 '{part}': {e}")
                continue
        else:
            # 处理单集，如 "6" 或 "8"
            try:
                episode_num = int(part)
                episodes.append(episode_num)
            except ValueError as e:
                logger.warning(f"无法解析集数 '{part}': {e}")
                continue

    # 去重并排序
    episodes = sorted(list(set(episodes)))
    logger.info(f"解析集数范围 '{episode_str}' -> {episodes}")

    return episodes


def extract_short_error_message(error: Exception) -> str:
    """
    从异常对象中提取简短的错误消息，用于任务管理器显示

    Args:
        error: 异常对象

    Returns:
        简短的错误描述（不包含SQL语句、堆栈等详细信息）
    """
    error_str = str(error)

    # 如果是数据库错误，只保留错误类型和简短描述
    if "DataError" in error_str or "IntegrityError" in error_str or "OperationalError" in error_str:
        # 提取错误类型
        error_type = type(error).__name__

        # 尝试提取MySQL/PostgreSQL错误消息（在括号中）
        match = re.search(r'\((\d+),\s*"([^"]+)"\)', error_str)
        if match:
            error_code = match.group(1)
            error_msg = match.group(2)
            return f"{error_type} ({error_code}): {error_msg}"

        # 如果没有匹配到，返回错误类型
        return error_type

    # 对于其他错误，只返回第一行
    first_line = error_str.split('\n')[0]
    # 限制长度
    if len(first_line) > 100:
        return first_line[:97] + "..."
    return first_line


def is_chinese_title(title: str) -> bool:
    """
    检查标题是否是中文标题（而非日文或其他语言）

    判断逻辑：
    1. 如果包含日文假名（平假名或片假名），则认为是日文标题
    2. 如果包含中文字符且不包含日文假名，则认为是中文标题
    """
    if not title:
        return False

    # 日文假名范围：平假名 \u3040-\u309f，片假名 \u30a0-\u30ff
    japanese_pattern = re.compile(r'[\u3040-\u309f\u30a0-\u30ff]')
    if japanese_pattern.search(title):
        return False  # 包含日文假名，不是中文标题

    # 检查是否包含中文字符（包括中文标点符号）
    chinese_pattern = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]')
    return bool(chinese_pattern.search(title))


def generate_episode_range_string(episode_indices: List[int]) -> str:
    """
    将分集编号列表转换为紧凑的字符串表示形式。
    例如: [1, 2, 3, 5, 8, 9, 10] -> "1-3, 5, 8-10"
    """
    if not episode_indices:
        return "无"

    indices = sorted(list(set(episode_indices)))
    if not indices:
        return "无"

    ranges = []
    start = end = indices[0]

    for i in range(1, len(indices)):
        if indices[i] == end + 1:
            end = indices[i]
        else:
            ranges.append(str(start) if start == end else f"{start}-{end}")
            start = end = indices[i]
    ranges.append(str(start) if start == end else f"{start}-{end}")
    return ", ".join(ranges)


def is_movie_by_title(title: str) -> bool:
    """
    通过标题中的关键词（如"剧场版"）判断是否为电影。
    """
    if not title:
        return False
    # 关键词列表，不区分大小写
    movie_keywords = ["剧场版", "劇場版", "movie", "映画"]
    title_lower = title.lower()
    return any(keyword in title_lower for keyword in movie_keywords)

