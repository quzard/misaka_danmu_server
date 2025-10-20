import re
import logging
from typing import Any, Dict, List, Tuple

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

def _calculate_comment_quality_score(comment: Dict[str, Any]) -> float:
    """
    计算弹幕的质量评分

    评分标准:
    1. 长度: 5-50字符得分最高,过短或过长降分
    2. 内容: 包含关键词(如"?", "!", 中文字符)加分
    3. 重复字符: 过多重复字符降分

    Args:
        comment: 弹幕对象,包含'#text'字段

    Returns:
        质量评分 (0.0-1.0)
    """
    text = comment.get('#text', '').strip()
    if not text:
        return 0.0

    score = 0.5  # 基础分

    # 1. 长度评分 (0.0-0.3)
    length = len(text)
    if 5 <= length <= 50:
        score += 0.3
    elif 3 <= length < 5 or 50 < length <= 100:
        score += 0.15
    elif length < 3 or length > 100:
        score += 0.0

    # 2. 内容评分 (0.0-0.2)
    # 包含问号或感叹号(可能是提问或强调)
    if '?' in text or '?' in text or '!' in text or '!' in text:
        score += 0.1

    # 包含中文字符(通常比纯符号/数字更有意义)
    if any('\u4e00' <= char <= '\u9fff' for char in text):
        score += 0.1

    # 3. 重复字符惩罚 (-0.0 to -0.3)
    # 检测连续重复字符(如"哈哈哈哈哈")
    max_repeat = 1
    current_repeat = 1
    for i in range(1, len(text)):
        if text[i] == text[i-1]:
            current_repeat += 1
            max_repeat = max(max_repeat, current_repeat)
        else:
            current_repeat = 1

    if max_repeat > 5:
        score -= 0.3
    elif max_repeat > 3:
        score -= 0.15

    return max(0.0, min(1.0, score))


def _deduplicate_segment(segment_data: Tuple[int, List[Dict[str, Any]], float]) -> Tuple[int, List[Dict[str, Any]]]:
    """
    对单个时间段的弹幕进行去重和质量筛选 (用于多进程并行)

    Args:
        segment_data: (segment_index, segment_comments, similarity_threshold)

    Returns:
        (segment_index, deduplicated_comments)
    """
    segment_index, segment, similarity_threshold = segment_data

    if not segment:
        return (segment_index, [])

    # 1. 聚类相似弹幕
    clusters = _cluster_similar_comments(segment, similarity_threshold)

    # 2. 从每个聚类中选择质量最高的代表
    representatives = []
    for cluster in clusters:
        # 计算每条弹幕的质量评分
        scored_comments = [(comment, _calculate_comment_quality_score(comment)) for comment in cluster]
        # 选择评分最高的
        best_comment = max(scored_comments, key=lambda x: x[1])[0]
        representatives.append(best_comment)

    return (segment_index, representatives)


def _cluster_similar_comments(comments: List[Dict[str, Any]], similarity_threshold: float = 0.8) -> List[List[Dict[str, Any]]]:
    """
    对相似弹幕进行聚类

    使用简单的编辑距离算法对文本相似的弹幕分组

    Args:
        comments: 弹幕列表
        similarity_threshold: 相似度阈值 (0.0-1.0)

    Returns:
        聚类列表,每个聚类包含相似的弹幕
    """
    from difflib import SequenceMatcher

    if not comments:
        return []

    clusters = []

    for comment in comments:
        text = comment.get('#text', '').strip()
        if not text:
            continue

        # 尝试找到相似的聚类
        found_cluster = False
        for cluster in clusters:
            # 与聚类中第一个弹幕比较
            cluster_text = cluster[0].get('#text', '').strip()
            similarity = SequenceMatcher(None, text, cluster_text).ratio()

            if similarity >= similarity_threshold:
                cluster.append(comment)
                found_cluster = True
                break

        # 如果没有找到相似聚类,创建新聚类
        if not found_cluster:
            clusters.append([comment])

    return clusters


def sample_comments_evenly(comments: List[Dict[str, Any]], target_count: int) -> List[Dict[str, Any]]:
    """
    按固定时间段（6分钟）均匀采样弹幕,增强版

    改进策略:
    1. 语义去重: 聚类相似弹幕,每个聚类只保留质量最高的代表
    2. 质量评分: 根据长度、内容、重复度对弹幕打分
    3. 时间均匀: 在去重后的弹幕中按时间段均匀采样

    Args:
        comments: 原始弹幕列表,每个弹幕包含 'p' 字段（时间,类型,字号,颜色,时间戳,弹幕池,用户ID,弹幕ID）
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

    # 固定时间段长度：3分钟 = 180秒
    SEGMENT_DURATION = 180.0

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

    # === 新增: 对每个时间段内的弹幕进行去重和质量筛选 (多进程并行) ===
    original_total = sum(len(seg) for seg in segments)

    # 准备多进程任务数据
    segment_tasks = [
        (i, segment, 0.8)  # (segment_index, segment_comments, similarity_threshold)
        for i, segment in enumerate(segments)
    ]

    # 使用多进程并行处理每个时间段
    from concurrent.futures import ProcessPoolExecutor

    # 固定使用3个进程
    max_workers = 3

    # 只有当时间段数量>=2时才使用多进程,否则单线程处理
    if len(segment_tasks) >= 2:
        logger.debug(f"使用 {max_workers} 个进程并行处理 {len(segment_tasks)} 个时间段")

        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            results = list(executor.map(_deduplicate_segment, segment_tasks))

        # 按segment_index排序结果
        results.sort(key=lambda x: x[0])
        deduplicated_segments = [representatives for _, representatives in results]

        # 记录每段的去重情况
        for i, (seg_idx, representatives) in enumerate(results):
            original_count = len(segments[seg_idx])
            if original_count > 0:
                logger.debug(f"时间段 {seg_idx}: 原始 {original_count} 条 -> 去重后 {len(representatives)} 条")
    else:
        # 单线程处理
        logger.debug(f"使用单线程处理 {len(segment_tasks)} 个时间段")
        deduplicated_segments = []

        for i, segment in enumerate(segments):
            if not segment:
                deduplicated_segments.append([])
                continue

            # 1. 聚类相似弹幕
            clusters = _cluster_similar_comments(segment, similarity_threshold=0.8)

            # 2. 从每个聚类中选择质量最高的代表
            representatives = []
            for cluster in clusters:
                # 计算每条弹幕的质量评分
                scored_comments = [(comment, _calculate_comment_quality_score(comment)) for comment in cluster]
                # 选择评分最高的
                best_comment = max(scored_comments, key=lambda x: x[1])[0]
                representatives.append(best_comment)

            deduplicated_segments.append(representatives)
            logger.debug(f"时间段 {i}: 原始 {len(segment)} 条 -> 去重后 {len(representatives)} 条 (聚类数: {len(clusters)})")

    deduplicated_total = sum(len(seg) for seg in deduplicated_segments)
    logger.info(f"弹幕去重: {original_total} 条 -> {deduplicated_total} 条 (减少 {original_total - deduplicated_total} 条, {(1 - deduplicated_total/original_total)*100:.1f}%)")

    # 如果去重后的弹幕数量已经小于等于目标数量,直接返回
    if deduplicated_total <= target_count:
        result = []
        for seg in deduplicated_segments:
            result.extend(seg)
        logger.info(f"去重后弹幕数量 {deduplicated_total} 已小于目标 {target_count}, 直接返回")
        return result

    # === 改进的时间均匀采样逻辑 (确保最大均匀性) ===
    # 策略: 按每段弹幕密度比例分配配额,而不是平均分配

    # 计算每段的弹幕密度权重
    segment_weights = []
    for i, segment in enumerate(deduplicated_segments):
        weight = len(segment) if len(segment) > 0 else 0
        segment_weights.append(weight)

    total_weight = sum(segment_weights)

    if total_weight == 0:
        # 所有段都没有弹幕
        logger.warning("所有时间段都没有弹幕")
        return []

    # 按权重分配配额
    segment_quotas = []
    allocated_total = 0

    for i, weight in enumerate(segment_weights):
        if weight == 0:
            segment_quotas.append(0)
        else:
            # 按比例分配
            quota = int(target_count * weight / total_weight)
            segment_quotas.append(quota)
            allocated_total += quota

    # 处理余数: 将剩余配额分配给弹幕最多的段
    remainder = target_count - allocated_total
    if remainder > 0:
        # 找出弹幕最多的段
        sorted_indices = sorted(range(len(segment_weights)), key=lambda i: segment_weights[i], reverse=True)
        for i in range(remainder):
            if i < len(sorted_indices):
                idx = sorted_indices[i]
                segment_quotas[idx] += 1

    logger.debug(f"按密度分配配额: {segment_quotas}")

    # 第一轮: 从每段中采样分配的配额
    sampled_comments = []
    segment_stats = []

    for i, segment in enumerate(deduplicated_segments):
        quota = segment_quotas[i]

        if quota == 0:
            segment_stats.append({
                'index': i,
                'total': len(segment),
                'sampled': 0,
                'remaining': len(segment),
                'deficit': 0
            })
            continue

        if len(segment) >= quota:
            # 弹幕充足,均匀采样
            # 使用等间隔采样而不是随机采样,确保时间上更均匀
            if quota == len(segment):
                sampled = segment
            else:
                # 等间隔采样
                step = len(segment) / quota
                sampled = [segment[int(i * step)] for i in range(quota)]

            sampled_comments.extend(sampled)
            segment_stats.append({
                'index': i,
                'total': len(segment),
                'sampled': quota,
                'remaining': len(segment) - quota
            })
            logger.debug(f"时间段 {i} ({i*SEGMENT_DURATION:.0f}s-{(i+1)*SEGMENT_DURATION:.0f}s): 从 {len(segment)} 条中等间隔采样 {quota} 条")
        else:
            # 弹幕不足,全部采样
            sampled_comments.extend(segment)
            segment_stats.append({
                'index': i,
                'total': len(segment),
                'sampled': len(segment),
                'remaining': 0,
                'deficit': quota - len(segment)
            })
            logger.debug(f"时间段 {i} ({i*SEGMENT_DURATION:.0f}s-{(i+1)*SEGMENT_DURATION:.0f}s): 弹幕不足,全部采样 {len(segment)} 条 (缺口 {quota - len(segment)} 条)")

    # 第二轮: 如果有缺口,从有剩余弹幕的段中按比例补充
    total_deficit = sum(stat.get('deficit', 0) for stat in segment_stats)

    if total_deficit > 0:
        logger.debug(f"总缺口: {total_deficit} 条,开始从有剩余的段中按比例补充")

        # 找出有剩余弹幕的段
        segments_with_remaining = [
            (stat['index'], deduplicated_segments[stat['index']], stat['remaining'])
            for stat in segment_stats if stat['remaining'] > 0
        ]

        if segments_with_remaining:
            # 计算每段的补充配额(按剩余数量比例)
            total_remaining = sum(r for _, _, r in segments_with_remaining)

            for seg_idx, segment, remaining in segments_with_remaining:
                # 按比例分配补充配额
                补充配额 = int(total_deficit * remaining / total_remaining)

                if 补充配额 > 0:
                    # 找出该段中未被采样的弹幕
                    already_sampled_set = set(id(c) for c in sampled_comments if c in segment)
                    available = [c for c in segment if id(c) not in already_sampled_set]

                    if available:
                        actual_补充 = min(补充配额, len(available))
                        # 等间隔补充
                        if actual_补充 == len(available):
                            补充_comments = available
                        else:
                            step = len(available) / actual_补充
                            补充_comments = [available[int(i * step)] for i in range(actual_补充)]

                        sampled_comments.extend(补充_comments)
                        logger.debug(f"从时间段 {seg_idx} 等间隔补充 {actual_补充} 条弹幕")

    logger.info(f"弹幕均匀采样: 原始{len(comments)}条 -> 去重{deduplicated_total}条 -> 采样{len(sampled_comments)}条 (目标{target_count}条, 分{total_segments}段, 每段{SEGMENT_DURATION}s)")

    # 确保返回的数量不超过目标数量
    return sampled_comments[:target_count]
