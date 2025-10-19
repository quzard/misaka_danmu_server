import re
import logging
from typing import Any, Dict, List

def _roman_to_int(s: str) -> int:
    """将罗马数字字符串转换为整数。"""
    roman_map = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}
    s = s.upper()
    result = 0
    i = 0
    while i < len(s):
        # 处理减法规则 (e.g., IV, IX)
        if i + 1 < len(s) and roman_map[s[i]] < roman_map[s[i+1]]:
            result += roman_map[s[i+1]] - roman_map[s[i]]
            i += 2
        else:
            result += roman_map[s[i]]
            i += 1
    return result
 
def parse_search_keyword(keyword: str) -> Dict[str, Any]:
    """
    解析搜索关键词，提取标题、季数和集数。
    支持 "Title S01E01", "Title S01", "Title 2", "Title 第二季", "Title Ⅲ" 等格式。
    """
    keyword = keyword.strip()

    # 1. 优先匹配 SXXEXX 格式
    s_e_pattern = re.compile(r"^(?P<title>.+?)\s*S(?P<season>\d{1,2})E(?P<episode>\d{1,4})$", re.IGNORECASE)
    match = s_e_pattern.match(keyword)
    if match:
        data = match.groupdict()
        return {
            "title": data["title"].strip(),
            "season": int(data["season"]),
            "episode": int(data["episode"]),
        }

    # 2. 匹配季度信息
    season_patterns = [
        (re.compile(r"^(.*?)\s*(?:S|Season)\s*(\d{1,2})$", re.I), lambda m: int(m.group(2))),
        (re.compile(r"^(.*?)\s*第\s*([一二三四五六七八九十\d]+)\s*[季部]$", re.I), 
         lambda m: {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}.get(m.group(2)) or int(m.group(2))),
        (re.compile(r"^(.*?)\s*([Ⅰ-Ⅻ])$"), 
         lambda m: {'Ⅰ': 1, 'Ⅱ': 2, 'Ⅲ': 3, 'Ⅳ': 4, 'Ⅴ': 5, 'Ⅵ': 6, 'Ⅶ': 7, 'Ⅷ': 8, 'Ⅸ': 9, 'Ⅹ': 10, 'Ⅺ': 11, 'Ⅻ': 12}.get(m.group(2).upper())),
        (re.compile(r"^(.*?)\s+([IVXLCDM]+)$", re.I), lambda m: _roman_to_int(m.group(2))),
        (re.compile(r"^(.*?)\s+(\d{1,2})$"), lambda m: int(m.group(2))),
    ]

    for pattern, handler in season_patterns:
        match = pattern.match(keyword)
        if match:
            try:
                title = match.group(1).strip()
                season = handler(match)
                if season and not (len(title) > 4 and title[-4:].isdigit()): # 避免将年份误认为季度
                    return {"title": title, "season": season, "episode": None}
            except (ValueError, KeyError, IndexError):
                continue

    # 3. 如果没有匹配到特定格式，则返回原始标题
    return {"title": keyword, "season": None, "episode": None}

def to_camel(snake_str: str) -> str:
    """将 snake_case 字符串转换为 camelCase。"""
    components = snake_str.split('_')
    # 我们将除第一个之外的每个组件的首字母大写，然后连接起来。
    return components[0] + ''.join(x.title() for x in components[1:])

def convert_keys_to_camel(data: Any) -> Any:
    """
    递归地将字典的键从 snake_case 转换为 camelCase。
    """
    if isinstance(data, dict):
        return {to_camel(k): convert_keys_to_camel(v) for k, v in data.items()}
    if isinstance(data, list):
        return [convert_keys_to_camel(i) for i in data]
    return data

def clean_xml_string(xml_string: str) -> str:
    """
    移除XML字符串中的无效字符以防止解析错误。
    此函数针对XML 1.0规范中非法的控制字符。
    """
    # XML 1.0 规范允许的字符范围: #x9 | #xA | #xD | [#x20-#xD7FF] | [#xE000-#xFFFD] | [#x10000-#x10FFFF]
    # 此正则表达式匹配所有不在上述范围内的字符。
    invalid_xml_char_re = re.compile(
        r'[^\x09\x0A\x0D\x20-\uD7FF\uE000-\uFFFD\U00010000-\U0010FFFF]'
    )
    return invalid_xml_char_re.sub('', xml_string)

def sample_comments_evenly(comments: List[Dict[str, Any]], target_count: int) -> List[Dict[str, Any]]:
    """
    按时间段均匀采样弹幕，确保弹幕在整个视频时长中分布均匀

    Args:
        comments: 原始弹幕列表，每个弹幕包含 'p' 字段（时间,类型,字号,颜色,时间戳,弹幕池,用户ID,弹幕ID）
        target_count: 目标弹幕数量

    Returns:
        采样后的弹幕列表
    """
    import random
    logger = logging.getLogger(__name__)

    if len(comments) <= target_count:
        return comments

    if target_count <= 0:
        return []

    # 解析弹幕时间并排序
    timed_comments = []
    for comment in comments:
        try:
            p_attr = comment.get('p', '')
            if p_attr:
                # p属性格式：时间,类型,字号,颜色,时间戳,弹幕池,用户ID,弹幕ID
                time_str = p_attr.split(',')[0]
                time_seconds = float(time_str)
                timed_comments.append((time_seconds, comment))
        except (ValueError, IndexError):
            # 如果解析失败，跳过这条弹幕
            continue

    if not timed_comments:
        return comments[:target_count]  # 如果没有有效时间，直接截取

    # 按时间排序
    timed_comments.sort(key=lambda x: x[0])

    # 获取时间范围
    min_time = timed_comments[0][0]
    max_time = timed_comments[-1][0]

    if max_time <= min_time:
        # 如果所有弹幕时间相同，随机采样
        return [comment for _, comment in random.sample(timed_comments, min(target_count, len(timed_comments)))]

    # 计算时间段
    time_duration = max_time - min_time
    segment_duration = time_duration / target_count

    logger.debug(f"弹幕采样详情: 时间范围 {min_time:.1f}s - {max_time:.1f}s (总时长 {time_duration:.1f}s), 每段 {segment_duration:.1f}s")

    # 为每个时间段分配弹幕
    segments = [[] for _ in range(target_count)]

    for time_seconds, comment in timed_comments:
        # 计算当前弹幕属于哪个时间段
        segment_index = int((time_seconds - min_time) / segment_duration)

        # 确保不超出范围
        if segment_index >= target_count:
            segment_index = target_count - 1

        segments[segment_index].append(comment)

    # 从每个时间段随机选择一条弹幕
    sampled_comments = []
    empty_segments = []

    for i, segment in enumerate(segments):
        if segment:
            # 随机选择一条
            sampled_comments.append(random.choice(segment))
            logger.debug(f"时间段 {i}: 从 {len(segment)} 条弹幕中随机选择 1 条")
        else:
            # 记录空时间段
            empty_segments.append(i)
            logger.debug(f"时间段 {i}: 无弹幕")

    # 如果有空时间段，从有多条弹幕的时间段补充
    if empty_segments and len(sampled_comments) < target_count:
        logger.debug(f"发现 {len(empty_segments)} 个空时间段，需要补充")

        # 找出有多条弹幕的时间段
        multi_comment_segments = [(i, seg) for i, seg in enumerate(segments) if len(seg) > 1]

        if multi_comment_segments:
            # 从这些时间段中随机补充
            needed = min(len(empty_segments), target_count - len(sampled_comments))

            for _ in range(needed):
                if not multi_comment_segments:
                    break

                # 随机选择一个有多条弹幕的时间段
                seg_idx, segment = random.choice(multi_comment_segments)

                # 从该时间段中随机选择一条未被采样的弹幕
                available = [c for c in segment if c not in sampled_comments]
                if available:
                    sampled_comments.append(random.choice(available))
                    logger.debug(f"补充采样: 从时间段 {seg_idx} 补充 1 条")

                # 如果该时间段只剩1条可用弹幕，移除它
                if len(available) <= 1:
                    multi_comment_segments = [(i, s) for i, s in multi_comment_segments if i != seg_idx]

    logger.info(f"弹幕均匀采样: 原始{len(comments)}条 -> 采样{len(sampled_comments)}条 (目标{target_count}条, 空时间段{len(empty_segments)}个)")

    # 确保返回的数量不超过目标数量
    return sampled_comments[:target_count]
