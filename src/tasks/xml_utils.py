"""XML弹幕处理工具模块"""
import logging
import io
import xml.etree.ElementTree as ET
from typing import List, Dict
from xml.sax.saxutils import escape as xml_escape

logger = logging.getLogger(__name__)


def parse_xml_content(xml_content: str) -> List[Dict[str, str]]:
    """
    使用 iterparse 高效解析XML弹幕内容，无条数限制，并规范化p属性。
    """
    comments = []
    try:
        # 使用 io.StringIO 将字符串转换为文件流，以便 iterparse 处理
        xml_stream = io.StringIO(xml_content)
        # iterparse 以事件驱动的方式解析，内存效率高，适合大文件
        for event, elem in ET.iterparse(xml_stream, events=('end',)):
            # 当一个 <d> 标签结束时处理它
            if elem.tag == 'd':
                p_attr = elem.get('p')
                text = elem.text
                if p_attr is not None and text is not None:
                    p_parts = p_attr.split(',')
                    if len(p_parts) >= 4:
                        # 提取前4个核心参数: 时间, 模式, 字体大小, 颜色
                        processed_p_attr = f"{p_parts[0]},{p_parts[1]},{p_parts[2]},{p_parts[3]},[custom_xml]"
                        comments.append({'p': processed_p_attr, 'm': text})
                    else:
                        # 如果参数不足4个，保持原样以避免数据损坏
                        comments.append({'p': p_attr, 'm': text})
                # 清理已处理的元素以释放内存
                elem.clear()
    except ET.ParseError as e:
        logger.error(f"解析XML时出错: {e}")
        # 即使解析出错，也可能已经解析了一部分，返回已解析的内容
    return comments


def generate_dandan_xml(comments: List[dict]) -> str:
    """
    根据弹幕字典列表生成 dandanplay 格式的 XML 字符串。
    """
    xml_parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<i>',
        '  <chatserver>danmu</chatserver>',
        '  <chatid>0</chatid>',
        '  <mission>0</mission>',
        f'  <maxlimit>{len(comments)}</maxlimit>',
        '  <source>kuyun</source>'
    ]
    for comment in comments:
        content = xml_escape(comment.get('m', ''))
        p_attr_str = comment.get('p', '0,1,25,16777215')
        p_parts = p_attr_str.split(',')

        # 强制修复逻辑：确保 p 属性的格式为 时间,模式,字体大小,颜色,...
        core_parts_end_index = len(p_parts)
        for i, part in enumerate(p_parts):
            if '[' in part and ']' in part:
                core_parts_end_index = i
                break
        core_parts = p_parts[:core_parts_end_index]
        optional_parts = p_parts[core_parts_end_index:]

        # 场景1: 缺少字体大小 (e.g., "1.23,1,16777215")
        if len(core_parts) == 3:
            core_parts.insert(2, '25')
        # 场景2: 字体大小为空或无效 (e.g., "1.23,1,,16777215")
        elif len(core_parts) == 4 and (not core_parts[2] or not core_parts[2].strip().isdigit()):
            core_parts[2] = '25'

        final_p_attr = ','.join(core_parts + optional_parts)
        xml_parts.append(f'  <d p="{final_p_attr}">{content}</d>')
    xml_parts.append('</i>')
    return '\n'.join(xml_parts)


def convert_text_danmaku_to_xml(text_content: str) -> str:
    """
    将非标准的、基于行的纯文本弹幕格式转换为标准的XML格式。
    支持的格式: "时间,模式,?,颜色,... | 弹幕内容"
    """
    xml_parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<i>',
        '  <chatserver>danmu</chatserver>',
        '  <chatid>0</chatid>',
        '  <mission>0</mission>',
        '  <source>misaka</source>'
    ]
    comments = []
    for line in text_content.strip().split('\n'):
        if '|' not in line:
            continue
        params_str, text = line.split('|', 1)
        params = params_str.split(',')
        if len(params) >= 4:
            # 提取关键参数: 时间, 模式, 颜色
            # 格式: 756.103,1,25,16777215,...
            time_sec = params[0]
            mode     = params[1]
            fontsize = params[2]
            color    = params[3]
            p_attr = f"{time_sec},{mode},{fontsize},{color},[custom_text]"
            escaped_text = xml_escape(text.strip())
            comments.append(f'  <d p="{p_attr}">{escaped_text}</d>')
    xml_parts.insert(5, f'  <maxlimit>{len(comments)}</maxlimit>')
    xml_parts.extend(comments)
    xml_parts.append('</i>')
    return '\n'.join(xml_parts)

