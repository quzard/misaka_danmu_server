import logging
import re
from typing import Dict, List
from xml.etree import ElementTree

from src.utils import clean_xml_string

logger = logging.getLogger(__name__)

def _normalize_p_attr_to_internal_format(p_attr: str, source_tag: str = "[xml]") -> str:
    """
    将各种格式的 p 属性标准化为内部存储格式。

    内部存储格式: "时间,模式,字体大小,颜色,[来源]" (4个核心参数 + 来源标签)

    支持的输入格式:
    1. Bilibili XML: "时间,模式,字号,颜色,时间戳,弹幕池,用户ID,弹幕ID" (8个参数)
    2. Dandanplay API: "时间,模式,颜色,用户ID,..." (第3个是颜色，没有字号)
    3. 已标准化格式: "时间,模式,字号,颜色,[来源]" (4个核心参数 + 来源标签)
    """
    if not p_attr:
        return f"0,1,25,16777215,{source_tag}"

    parts = p_attr.split(',')

    # 检查是否已有来源标签
    existing_source_tag = None
    core_parts_end = len(parts)
    for i, part in enumerate(parts):
        if '[' in part and ']' in part:
            existing_source_tag = part
            core_parts_end = i
            break

    core_parts = parts[:core_parts_end]

    # 根据核心参数数量判断格式并标准化
    if len(core_parts) >= 4:
        # Bilibili 格式 (8参数) 或已标准化格式 (4参数)
        # 格式: 时间,模式,字号,颜色,...
        # 只保留前4个核心参数
        time_val = core_parts[0]
        mode_val = core_parts[1]
        fontsize_val = core_parts[2]
        color_val = core_parts[3]

        # 验证字号是否为有效数字，如果不是则使用默认值
        if not fontsize_val.strip().isdigit():
            fontsize_val = '25'

        final_source = existing_source_tag if existing_source_tag else source_tag
        return f"{time_val},{mode_val},{fontsize_val},{color_val},{final_source}"

    elif len(core_parts) == 3:
        # Dandanplay API 格式: 时间,模式,颜色 (没有字号)
        # 需要插入默认字号 25
        time_val = core_parts[0]
        mode_val = core_parts[1]
        color_val = core_parts[2]

        final_source = existing_source_tag if existing_source_tag else source_tag
        return f"{time_val},{mode_val},25,{color_val},{final_source}"

    else:
        # 参数不足，补全默认值
        while len(core_parts) < 4:
            if len(core_parts) == 0:
                core_parts.append('0')       # 时间
            elif len(core_parts) == 1:
                core_parts.append('1')       # 模式
            elif len(core_parts) == 2:
                core_parts.append('25')      # 字号
            elif len(core_parts) == 3:
                core_parts.append('16777215')  # 颜色（白色）

        final_source = existing_source_tag if existing_source_tag else source_tag
        return f"{core_parts[0]},{core_parts[1]},{core_parts[2]},{core_parts[3]},{final_source}"


def parse_dandan_xml_to_comments(xml_content: str, source_tag: str = "[xml]") -> List[Dict]:
    """
    解析 XML 弹幕内容，并标准化为内部存储格式。

    支持的 XML 格式:
    1. Bilibili XML: p="时间,模式,字号,颜色,时间戳,弹幕池,用户ID,弹幕ID"
    2. Dandanplay XML: p="时间,模式,颜色,用户ID,..."
    3. 其他标准 XML 格式

    输出的内部存储格式: p="时间,模式,字号,颜色,[来源]"
    """
    comments = []
    try:
        # 关键修复：在解析之前，先清理XML内容，移除所有非法字符。
        # 这可以防止因弹幕内容包含无效控制字符（如退格符）而导致的解析失败。
        xml_content = clean_xml_string(xml_content)
        # Remove any XML declaration that might cause issues
        xml_content = re.sub(r'<\?xml.*?\?>', '', xml_content, count=1).strip()
        root = ElementTree.fromstring(xml_content)
        for comment_node in root.findall('d'):
            try:
                p_attr = comment_node.attrib.get('p', '0,1,25,16777215')
                text = comment_node.text or ''

                # 标准化 p 属性为内部存储格式
                normalized_p = _normalize_p_attr_to_internal_format(p_attr, source_tag)

                # 解析时间用于排序
                parts = p_attr.split(',')
                time_sec = float(parts[0]) if parts else 0.0

                # 尝试获取弹幕ID (bilibili格式的第8个参数)
                comment_id = 0
                if len(parts) > 7:
                    try:
                        comment_id = int(parts[7])
                    except ValueError:
                        pass

                comment_dict = {
                    'p': normalized_p,
                    'm': text,
                    't': time_sec,
                    'cid': comment_id
                }
                comments.append(comment_dict)
            except (IndexError, ValueError) as e:
                logger.warning(f"Skipping malformed comment node: {ElementTree.tostring(comment_node, 'unicode')}. Error: {e}")
                continue
    except ElementTree.ParseError as e:
        logger.error(f"Failed to parse XML content: {e}")
        # Return empty list if XML is invalid
        return []

    return comments
