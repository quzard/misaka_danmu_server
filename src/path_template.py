"""
弹幕文件路径模板解析器

支持的变量：
- ${title}: 作品标题
- ${season}: 季度号
- ${episode}: 分集号
- ${year}: 年份
- ${provider}: 数据源提供商
- ${animeId}: 作品ID
- ${episodeId}: 分集ID
- ${sourceId}: 数据源ID

支持的格式化选项：
- ${season:02d}: 季度号补零到2位
- ${episode:02d}: 分集号补零到2位
- ${episode:03d}: 分集号补零到3位
"""

import re
import os
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from string import Template

logger = logging.getLogger(__name__)


class DanmakuPathTemplate:
    """弹幕文件路径模板解析器"""
    
    def __init__(self, template: str):
        """
        初始化路径模板
        
        Args:
            template: 路径模板字符串，如 "/downloads/${title}/Season ${season}/${title} - S${season:02d}E${episode:02d}"
        """
        self.template = template
        self._validate_template()
    
    def _validate_template(self):
        """验证模板格式是否正确"""
        # 检查是否包含不安全的路径字符
        unsafe_chars = ['..', '\\', '<', '>', '|', '"', '?', '*']
        for char in unsafe_chars:
            if char in self.template:
                raise ValueError(f"路径模板包含不安全字符 '{char}': {self.template}")
    
    def generate_path(self, context: Dict[str, Any]) -> Path:
        """
        根据上下文生成弹幕文件路径
        
        Args:
            context: 包含变量值的字典
            
        Returns:
            生成的文件路径
        """
        try:
            # 清理和准备变量
            clean_context = self._prepare_context(context)
            
            # 处理格式化变量（如 ${season:02d}）
            formatted_template = self._process_formatted_variables(self.template, clean_context)
            
            # 使用 string.Template 进行变量替换
            template = Template(formatted_template)
            resolved_path = template.safe_substitute(clean_context)
            
            # 检查是否有未替换的变量
            if '$' in resolved_path:
                logger.warning(f"路径模板中存在未替换的变量: {resolved_path}")

            # 自动添加.xml后缀（如果没有的话）
            if not resolved_path.endswith('.xml'):
                resolved_path += '.xml'

            # 处理路径分隔符，确保跨平台兼容性
            # 将Unix风格的路径分隔符转换为当前系统的分隔符
            if '/' in resolved_path and not resolved_path.startswith('/'):
                # 相对路径，转换分隔符
                resolved_path = resolved_path.replace('/', os.sep)

            return Path(resolved_path)
            
        except Exception as e:
            logger.error(f"生成弹幕路径失败: {e}, 模板: {self.template}, 上下文: {context}")
            # 回退到默认路径
            def _is_docker_environment():
                """检测是否在Docker容器中运行"""
                import os
                # 方法1: 检查 /.dockerenv 文件（Docker标准做法）
                if Path("/.dockerenv").exists():
                    return True
                # 方法2: 检查环境变量
                if os.getenv("DOCKER_CONTAINER") == "true" or os.getenv("IN_DOCKER") == "true":
                    return True
                # 方法3: 检查当前工作目录是否为 /app
                if Path.cwd() == Path("/app"):
                    return True
                return False

            def _get_default_path():
                """根据运行环境获取默认路径"""
                if _is_docker_environment():
                    # 容器环境
                    return f"/app/config/danmaku/{context.get('animeId', 'unknown')}/{context.get('episodeId', 'unknown')}.xml"
                else:
                    # 源码运行环境
                    return f"config/danmaku/{context.get('animeId', 'unknown')}/{context.get('episodeId', 'unknown')}.xml"

            return Path(_get_default_path())
    
    def _prepare_context(self, context: Dict[str, Any]) -> Dict[str, str]:
        """准备和清理上下文变量"""
        clean_context = {}
        
        for key, value in context.items():
            if value is None:
                clean_context[key] = 'unknown'
            elif isinstance(value, (int, float)):
                clean_context[key] = str(value)
            else:
                # 清理文件名中的非法字符
                clean_value = self._sanitize_filename(str(value))
                clean_context[key] = clean_value
        
        return clean_context
    
    def _sanitize_filename(self, filename: str) -> str:
        """清理文件名中的非法字符"""
        # Windows和Linux都不允许的字符
        illegal_chars = ['<', '>', ':', '"', '|', '?', '*', '\\', '/']
        
        clean_name = filename
        for char in illegal_chars:
            clean_name = clean_name.replace(char, '_')
        
        # 移除前后空格和点
        clean_name = clean_name.strip(' .')
        
        # 如果清理后为空，使用默认值
        if not clean_name:
            clean_name = 'unknown'
        
        return clean_name
    
    def _process_formatted_variables(self, template: str, context: Dict[str, str]) -> str:
        """处理带格式化的变量，如 ${season:02d}"""
        # 匹配格式化变量的正则表达式
        pattern = r'\$\{(\w+):(\w+)\}'
        
        def replace_formatted(match):
            var_name = match.group(1)
            format_spec = match.group(2)
            
            if var_name not in context:
                return match.group(0)  # 保持原样
            
            try:
                value = context[var_name]
                # 尝试转换为数字并格式化
                if format_spec.endswith('d'):  # 整数格式
                    num_value = int(value)
                    return f"{num_value:{format_spec}}"
                else:
                    return value
            except (ValueError, TypeError):
                logger.warning(f"无法格式化变量 {var_name} 的值 '{value}' 使用格式 '{format_spec}'")
                return value
        
        return re.sub(pattern, replace_formatted, template)
    



def create_danmaku_context(anime_title: str, season: int, episode_index: int, 
                          year: Optional[int] = None, provider: Optional[str] = None,
                          anime_id: Optional[int] = None, episode_id: Optional[int] = None,
                          source_id: Optional[int] = None) -> Dict[str, Any]:
    """
    创建弹幕路径模板的上下文变量
    
    Args:
        anime_title: 作品标题
        season: 季度号
        episode_index: 分集号
        year: 年份
        provider: 数据源提供商
        anime_id: 作品ID
        episode_id: 分集ID
        source_id: 数据源ID
        
    Returns:
        上下文字典
    """
    return {
        'title': anime_title,
        'season': season,
        'episode': episode_index,
        'year': year,
        'provider': provider,
        'animeId': anime_id,
        'episodeId': episode_id,
        'sourceId': source_id
    }


# 预定义的路径模板示例（.xml后缀会自动添加）
TEMPLATE_EXAMPLES = {
    'default': '/app/config/danmaku/${animeId}/${episodeId}',
    'organized_by_title': 'downloads/弹幕/${title}/${title} - S${season:02d}E${episode:02d}',
    'qbittorrent_style': 'downloads/QB下载/动漫/${title}/Season ${season}/${title} - S${season:02d}E${episode:02d}',
    'plex_style': 'media/动漫/${title} (${year})/Season ${season:02d}/${title} - S${season:02d}E${episode:02d}',
    'emby_style': 'media/动漫/${title}/${title} S${season:02d}/${title} S${season:02d}E${episode:02d}',
    'simple': '弹幕/${title}/${episode:03d}',
    # Windows绝对路径示例
    'windows_absolute': 'D:/弹幕/${title}/${title} - S${season:02d}E${episode:02d}',
    'windows_downloads': 'C:/Users/${username}/Downloads/弹幕/${title}/${episode:03d}'
}
