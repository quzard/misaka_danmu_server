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
    按固定时间段（6分钟）均匀采样弹幕

    新逻辑：
    1. 将视频按6分钟（360秒）分段，最后一段不足6分钟也算一段
    2. 计算每段应该采样的弹幕数 = target_count / 总段数
    3. 从每段中随机采样对应数量的弹幕
    4. 如果某段弹幕不足，从其他段补充

    Args:
        comments: 原始弹幕列表，每个弹幕包含 'p' 字段（时间,类型,字号,颜色,时间戳,弹幕池,用户ID,弹幕ID）
        target_count: 目标弹幕数量

    Returns:
        采样后的弹幕列表
    """
    import random
    import math
    logger = logging.getLogger(__name__)

    if len(comments) <= target_count:
        return comments

    if target_count <= 0:
        return []

    # 固定时间段长度：6分钟 = 360秒
    SEGMENT_DURATION = 360.0

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

    # 计算总时长和段数
    time_duration = max_time - min_time
    total_segments = math.ceil(time_duration / SEGMENT_DURATION)

    logger.debug(f"弹幕采样详情: 时间范围 {min_time:.1f}s - {max_time:.1f}s (总时长 {time_duration:.1f}s), 分成 {total_segments} 段 (每段 {SEGMENT_DURATION}s)")

    # 为每个时间段分配弹幕
    segments = [[] for _ in range(total_segments)]

    for time_seconds, comment in timed_comments:
        # 计算当前弹幕属于哪个时间段
        segment_index = int((time_seconds - min_time) / SEGMENT_DURATION)

        # 确保不超出范围
        if segment_index >= total_segments:
            segment_index = total_segments - 1

        segments[segment_index].append(comment)

    # 计算每段应该采样的弹幕数（基础配额）
    base_quota_per_segment = target_count // total_segments
    remainder = target_count % total_segments

    logger.debug(f"每段基础配额: {base_quota_per_segment} 条, 余数: {remainder} 条")

    # 第一轮：从每段中采样基础配额
    sampled_comments = []
    segment_stats = []  # 记录每段的统计信息

    for i, segment in enumerate(segments):
        # 计算当前段的配额（前remainder个段多分配1条）
        quota = base_quota_per_segment + (1 if i < remainder else 0)

        if len(segment) >= quota:
            # 弹幕充足，随机采样
            sampled = random.sample(segment, quota)
            sampled_comments.extend(sampled)
            segment_stats.append({
                'index': i,
                'total': len(segment),
                'sampled': quota,
                'remaining': len(segment) - quota
            })
            logger.debug(f"时间段 {i} ({i*SEGMENT_DURATION:.0f}s-{(i+1)*SEGMENT_DURATION:.0f}s): 从 {len(segment)} 条中采样 {quota} 条")
        elif len(segment) > 0:
            # 弹幕不足，全部采样
            sampled_comments.extend(segment)
            segment_stats.append({
                'index': i,
                'total': len(segment),
                'sampled': len(segment),
                'remaining': 0,
                'deficit': quota - len(segment)  # 记录缺口
            })
            logger.debug(f"时间段 {i} ({i*SEGMENT_DURATION:.0f}s-{(i+1)*SEGMENT_DURATION:.0f}s): 弹幕不足，全部采样 {len(segment)} 条 (缺口 {quota - len(segment)} 条)")
        else:
            # 空段
            segment_stats.append({
                'index': i,
                'total': 0,
                'sampled': 0,
                'remaining': 0,
                'deficit': quota
            })
            logger.debug(f"时间段 {i} ({i*SEGMENT_DURATION:.0f}s-{(i+1)*SEGMENT_DURATION:.0f}s): 无弹幕 (缺口 {quota} 条)")

    # 第二轮：如果有缺口，从有剩余弹幕的段中补充
    total_deficit = sum(stat.get('deficit', 0) for stat in segment_stats)

    if total_deficit > 0:
        logger.debug(f"总缺口: {total_deficit} 条，开始从有剩余的段中补充")

        # 找出有剩余弹幕的段
        segments_with_remaining = [
            (stat['index'], segments[stat['index']], stat['remaining'])
            for stat in segment_stats if stat['remaining'] > 0
        ]

        if segments_with_remaining:
            # 按剩余数量排序（从多到少）
            segments_with_remaining.sort(key=lambda x: x[2], reverse=True)

            补充计数 = 0
            for seg_idx, segment, remaining in segments_with_remaining:
                if 补充计数 >= total_deficit:
                    break

                # 计算可以补充的数量
                can_补充 = min(remaining, total_deficit - 补充计数)

                # 找出该段中未被采样的弹幕
                already_sampled = [c for c in sampled_comments if c in segment]
                available = [c for c in segment if c not in already_sampled]

                if available:
                    actual_补充 = min(can_补充, len(available))
                    补充_comments = random.sample(available, actual_补充)
                    sampled_comments.extend(补充_comments)
                    补充计数 += actual_补充
                    logger.debug(f"从时间段 {seg_idx} 补充 {actual_补充} 条弹幕")

    logger.info(f"弹幕均匀采样: 原始{len(comments)}条 -> 采样{len(sampled_comments)}条 (目标{target_count}条, 分{total_segments}段, 每段{SEGMENT_DURATION}s)")

    # 确保返回的数量不超过目标数量
    return sampled_comments[:target_count]
