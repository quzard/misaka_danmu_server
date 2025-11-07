"""
本地弹幕文件扫描器
"""
import os
import re
import logging
import shutil
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .crud import local_danmaku as crud


logger = logging.getLogger(__name__)


class LocalDanmakuScanner:
    """本地弹幕文件扫描器"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory
        self.logger = logging.getLogger(self.__class__.__name__)

    async def scan_directory(self, scan_path: str) -> Dict[str, Any]:
        """
        扫描指定目录下的所有.xml弹幕文件
        
        Args:
            scan_path: 扫描根目录
            
        Returns:
            扫描结果统计
        """
        if not os.path.exists(scan_path):
            raise ValueError(f"扫描路径不存在: {scan_path}")

        if not os.path.isdir(scan_path):
            raise ValueError(f"扫描路径不是目录: {scan_path}")

        self.logger.info(f"开始扫描目录: {scan_path}")

        # 清空之前的扫描结果
        async with self.session_factory() as session:
            await crud.clear_all_local_items(session)

        # 递归扫描.xml文件
        xml_files = []
        for root, dirs, files in os.walk(scan_path):
            for file in files:
                if file.lower().endswith('.xml'):
                    xml_files.append(os.path.join(root, file))

        self.logger.info(f"找到 {len(xml_files)} 个.xml文件")

        # 解析每个文件
        success_count = 0
        error_count = 0

        for xml_file in xml_files:
            try:
                await self._process_xml_file(xml_file, scan_path)
                success_count += 1
            except Exception as e:
                self.logger.error(f"处理文件失败 {xml_file}: {e}")
                error_count += 1

        self.logger.info(f"扫描完成: 成功 {success_count}, 失败 {error_count}")

        return {
            "total": len(xml_files),
            "success": success_count,
            "error": error_count
        }

    async def _process_xml_file(self, xml_file: str, scan_root: str):
        """处理单个.xml文件"""
        file_path = Path(xml_file)
        parent_dir = file_path.parent
        file_name = file_path.stem  # 不含扩展名的文件名

        # 尝试查找nfo文件
        nfo_path, nfo_data = self._find_and_parse_nfo(file_path)

        # 从文件名或nfo提取信息
        title, media_type, season, episode = self._extract_metadata(
            file_name, parent_dir, nfo_data
        )

        # 从nfo提取其他元数据
        year = nfo_data.get('year') if nfo_data else None
        tmdb_id = nfo_data.get('tmdbid') if nfo_data else None
        tvdb_id = nfo_data.get('tvdbid') if nfo_data else None
        imdb_id = nfo_data.get('imdbid') if nfo_data else None
        poster_url = nfo_data.get('thumb') if nfo_data else None

        # 如果poster_url是本地路径,转换为相对路径
        if poster_url and os.path.isabs(poster_url):
            poster_url = os.path.relpath(poster_url, scan_root)

        # 对于电影,检测版本标识(如果文件名包含语言/版本信息)
        # 例如: movie.zh.xml, movie.en.xml, movie.4k.xml
        version_suffix = None
        if media_type == "movie" and '.' in file_name:
            parts = file_name.split('.')
            if len(parts) > 1:
                # 最后一部分可能是版本标识
                potential_version = parts[-1]
                # 常见的版本标识: zh, en, ja, 4k, 1080p, bluray等
                if potential_version.lower() in ['zh', 'en', 'ja', 'ko', 'cht', 'chs', '4k', '1080p', '720p', 'bluray', 'web-dl', 'webrip']:
                    version_suffix = potential_version
                    # 如果有版本标识,在标题后添加
                    title = f"{title} [{version_suffix.upper()}]"

        # 存入数据库
        async with self.session_factory() as session:
            await crud.create_local_item(
                session,
                file_path=str(xml_file),
                title=title,
                media_type=media_type,
                season=season,
                episode=episode,
                year=year,
                tmdb_id=tmdb_id,
                tvdb_id=tvdb_id,
                imdb_id=imdb_id,
                poster_url=poster_url,
                nfo_path=nfo_path
            )

        self.logger.debug(f"已添加: {title} (S{season}E{episode})" if season and episode else f"已添加: {title}")

    def _find_and_parse_nfo(self, xml_file: Path) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """
        查找并解析nfo文件

        Returns:
            (nfo文件路径, nfo数据字典)
        """
        # 策略1: 查找同名nfo文件(电影)
        # 例如: movie.zh.xml -> movie.nfo 或 movie.zh.nfo
        nfo_file = xml_file.with_suffix('.nfo')
        if nfo_file.exists():
            return str(nfo_file), self._parse_nfo(nfo_file)

        # 策略1.1: 尝试去除语言后缀后查找nfo
        # 例如: movie.zh.xml -> movie.nfo
        stem = xml_file.stem  # 例如: movie.zh
        if '.' in stem:
            base_name = stem.rsplit('.', 1)[0]  # 例如: movie
            base_nfo = xml_file.parent / f"{base_name}.nfo"
            if base_nfo.exists():
                return str(base_nfo), self._parse_nfo(base_nfo)

        # 策略2: 查找父目录下的tvshow.nfo(电视剧)
        tvshow_nfo = xml_file.parent / 'tvshow.nfo'
        if tvshow_nfo.exists():
            return str(tvshow_nfo), self._parse_nfo(tvshow_nfo)

        # 策略3: 查找上级目录的tvshow.nfo(季度文件夹)
        parent_tvshow_nfo = xml_file.parent.parent / 'tvshow.nfo'
        if parent_tvshow_nfo.exists():
            return str(parent_tvshow_nfo), self._parse_nfo(parent_tvshow_nfo)

        # 策略4: 查找父目录下的movie.nfo(电影文件夹)
        movie_nfo = xml_file.parent / 'movie.nfo'
        if movie_nfo.exists():
            return str(movie_nfo), self._parse_nfo(movie_nfo)

        return None, None

    def _parse_nfo(self, nfo_file: Path) -> Dict[str, Any]:
        """解析nfo文件"""
        try:
            tree = ET.parse(nfo_file)
            root = tree.getroot()

            data = {}

            # 提取常见字段
            for tag in ['title', 'year', 'tmdbid', 'tvdbid', 'imdbid', 'thumb']:
                elem = root.find(tag)
                if elem is not None and elem.text:
                    data[tag] = elem.text.strip()

            # 处理uniqueid标签(Kodi格式)
            for uniqueid in root.findall('uniqueid'):
                id_type = uniqueid.get('type', '').lower()
                id_value = uniqueid.text.strip() if uniqueid.text else None
                if id_value:
                    if id_type == 'tmdb':
                        data['tmdbid'] = id_value
                    elif id_type == 'tvdb':
                        data['tvdbid'] = id_value
                    elif id_type == 'imdb':
                        data['imdbid'] = id_value

            return data
        except Exception as e:
            self.logger.warning(f"解析nfo文件失败 {nfo_file}: {e}")
            return {}

    def _extract_metadata(
        self,
        file_name: str,
        parent_dir: Path,
        nfo_data: Optional[Dict[str, Any]]
    ) -> Tuple[str, str, Optional[int], Optional[int]]:
        """
        从文件名和目录结构提取元数据
        
        Returns:
            (title, media_type, season, episode)
        """
        # 尝试从文件名提取季集信息
        season, episode = self._extract_season_episode(file_name)

        # 确定媒体类型
        if season is not None and episode is not None:
            media_type = "tv_series"
        else:
            media_type = "movie"

        # 确定标题
        if nfo_data and 'title' in nfo_data:
            title = nfo_data['title']
        else:
            # 从目录结构推断标题
            if media_type == "tv_series":
                # 电视剧: 使用父目录或上级目录名
                if parent_dir.name.lower().startswith('season'):
                    # 在季度文件夹内,使用上级目录名
                    title = parent_dir.parent.name
                else:
                    title = parent_dir.name
            else:
                # 电影: 使用文件名(去除年份)
                title = re.sub(r'\s*\(\d{4}\)\s*$', '', file_name)

        # 清理标题
        title = self._clean_title(title)

        return title, media_type, season, episode

    def _extract_season_episode(self, file_name: str) -> Tuple[Optional[int], Optional[int]]:
        """
        从文件名提取季集信息
        
        支持格式:
        - S01E01, S1E1
        - 第1季第1集
        - 1x01
        """
        # 标准格式: S01E01
        match = re.search(r'[Ss](\d+)[Ee](\d+)', file_name)
        if match:
            return int(match.group(1)), int(match.group(2))

        # 中文格式: 第1季第1集
        match = re.search(r'第(\d+)季第(\d+)集', file_name)
        if match:
            return int(match.group(1)), int(match.group(2))

        # 简写格式: 1x01
        match = re.search(r'(\d+)x(\d+)', file_name)
        if match:
            return int(match.group(1)), int(match.group(2))

        # 仅集数: E01, EP01
        match = re.search(r'[Ee][Pp]?(\d+)', file_name)
        if match:
            return 1, int(match.group(1))  # 默认第1季

        return None, None

    def _clean_title(self, title: str) -> str:
        """清理标题"""
        # 移除常见的无用字符
        title = re.sub(r'[\[\]()【】]', ' ', title)
        # 移除多余空格
        title = re.sub(r'\s+', ' ', title).strip()
        return title


def copy_local_poster(poster_path: str) -> Optional[str]:
    """
    复制本地海报文件到海报目录

    Args:
        poster_path: 本地海报文件路径(可以是相对路径或绝对路径)

    Returns:
        复制后的Web可访问路径,例如 /data/images/xxxx.jpg
        失败返回None
    """
    try:
        from .image_utils import IMAGE_DIR

        poster_file = Path(poster_path)

        # 如果是相对路径,尝试解析为绝对路径
        if not poster_file.is_absolute():
            # 尝试相对于当前工作目录
            poster_file = Path.cwd() / poster_file

        if not poster_file.exists():
            logger.warning(f"海报文件不存在: {poster_file}")
            return None

        if not poster_file.is_file():
            logger.warning(f"海报路径不是文件: {poster_file}")
            return None

        # 确保图片目录存在
        IMAGE_DIR.mkdir(parents=True, exist_ok=True)

        # 生成新文件名
        extension = poster_file.suffix or ".jpg"
        new_filename = f"{uuid.uuid4()}{extension}"
        dest_path = IMAGE_DIR / new_filename

        # 复制文件
        shutil.copy2(poster_file, dest_path)
        logger.info(f"海报已复制: {poster_file} -> {dest_path}")

        return f"/data/images/{new_filename}"

    except Exception as e:
        logger.error(f"复制海报文件失败 {poster_path}: {e}", exc_info=True)
        return None

