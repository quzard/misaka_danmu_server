"""
Plex媒体服务器实现
"""

from typing import List, Dict, Any, Optional
import xml.etree.ElementTree as ET
from .base import BaseMediaServer, MediaLibrary, MediaItem


class PlexMediaServer(BaseMediaServer):
    """Plex媒体服务器"""
    
    def _get_headers(self) -> Dict[str, str]:
        """Plex使用X-Plex-Token"""
        return {
            'X-Plex-Token': self.api_token,
            'Accept': 'application/json',
        }
    
    async def test_connection(self) -> Dict[str, Any]:
        """测试连接"""
        try:
            data = await self._request('GET', '/')
            if data and 'MediaContainer' in data:
                container = data['MediaContainer']
                return {
                    "ServerName": container.get('friendlyName', 'Plex Server'),
                    "Version": container.get('version'),
                    "Id": container.get('machineIdentifier')
                }
            raise Exception("无法获取服务器信息")
        except Exception as e:
            self.logger.error(f"Plex连接测试失败: {e}")
            raise
    
    async def get_libraries(self) -> List[MediaLibrary]:
        """获取所有媒体库"""
        try:
            data = await self._request('GET', '/library/sections')
            libraries = []
            
            for item in data.get('MediaContainer', {}).get('Directory', []):
                lib_type = item.get('type')
                # 转换Plex的类型到统一类型
                if lib_type == 'movie':
                    unified_type = 'movies'
                elif lib_type == 'show':
                    unified_type = 'tvshows'
                else:
                    unified_type = 'mixed'
                
                libraries.append(MediaLibrary(
                    id=item.get('key'),
                    name=item.get('title'),
                    type=unified_type
                ))
            
            return libraries
        except Exception as e:
            self.logger.error(f"获取Plex媒体库失败: {e}")
            return []
    
    async def get_library_items(
        self,
        library_id: str,
        media_type: Optional[str] = None
    ) -> List[MediaItem]:
        """获取媒体库中的所有项"""
        try:
            data = await self._request('GET', f'/library/sections/{library_id}/all')
            items = []
            
            for item in data.get('MediaContainer', {}).get('Metadata', []):
                item_type = item.get('type')
                
                if item_type == 'movie' and (not media_type or media_type == 'movie'):
                    items.append(self._parse_movie(item, library_id))
                elif item_type == 'show' and (not media_type or media_type == 'tv_series'):
                    items.append(self._parse_series(item, library_id))
            
            return items
        except Exception as e:
            self.logger.error(f"获取Plex媒体库项失败: {e}")
            return []
    
    async def get_item_details(self, item_id: str) -> Optional[MediaItem]:
        """获取单个媒体项详情"""
        try:
            data = await self._request('GET', f'/library/metadata/{item_id}')
            metadata = data.get('MediaContainer', {}).get('Metadata', [])
            
            if not metadata:
                return None
            
            item = metadata[0]
            item_type = item.get('type')
            
            if item_type == 'movie':
                return self._parse_movie(item)
            elif item_type == 'show':
                return self._parse_series(item)
            elif item_type == 'episode':
                return self._parse_episode(item)
            
            return None
        except Exception as e:
            self.logger.error(f"获取Plex媒体项详情失败: {e}")
            return None
    
    async def get_tv_seasons(self, series_id: str) -> List[Dict[str, Any]]:
        """获取电视节目的所有季度"""
        try:
            data = await self._request('GET', f'/library/metadata/{series_id}/children')
            
            seasons = []
            for item in data.get('MediaContainer', {}).get('Metadata', []):
                if item.get('type') == 'season':
                    seasons.append({
                        'season_id': item.get('ratingKey'),
                        'season_number': item.get('index', 0),
                        'episode_count': item.get('leafCount', 0),
                    })
            
            return sorted(seasons, key=lambda x: x['season_number'])
        except Exception as e:
            self.logger.error(f"获取Plex季度信息失败: {e}")
            return []
    
    async def get_season_episodes(
        self,
        series_id: str,
        season_number: int
    ) -> List[MediaItem]:
        """获取某一季的所有集"""
        try:
            # 先获取季度ID
            seasons = await self.get_tv_seasons(series_id)
            season_id = None
            for season in seasons:
                if season['season_number'] == season_number:
                    season_id = season['season_id']
                    break
            
            if not season_id:
                return []
            
            data = await self._request('GET', f'/library/metadata/{season_id}/children')
            
            episodes = []
            for item in data.get('MediaContainer', {}).get('Metadata', []):
                if item.get('type') == 'episode':
                    episodes.append(self._parse_episode(item))
            
            return sorted(episodes, key=lambda x: x.episode or 0)
        except Exception as e:
            self.logger.error(f"获取Plex集数信息失败: {e}")
            return []
    
    def _parse_movie(self, data: Dict[str, Any], library_id: Optional[str] = None) -> MediaItem:
        """解析电影数据"""
        # Plex的GUID格式: plex://movie/5d776825880197001ec967c8
        # 或者: tmdb://12345, imdb://tt1234567
        guids = data.get('Guid', [])
        tmdb_id = None
        tvdb_id = None
        imdb_id = None
        
        for guid in guids:
            guid_id = guid.get('id', '')
            if guid_id.startswith('tmdb://'):
                tmdb_id = guid_id.replace('tmdb://', '')
            elif guid_id.startswith('tvdb://'):
                tvdb_id = guid_id.replace('tvdb://', '')
            elif guid_id.startswith('imdb://'):
                imdb_id = guid_id.replace('imdb://', '')
        
        return MediaItem(
            media_id=data.get('ratingKey'),
            title=data.get('title'),
            media_type='movie',
            year=data.get('year'),
            tmdb_id=tmdb_id,
            tvdb_id=tvdb_id,
            imdb_id=imdb_id,
            poster_url=self._get_image_url(data.get('thumb')),
            library_id=library_id,
        )
    
    def _parse_series(self, data: Dict[str, Any], library_id: Optional[str] = None) -> MediaItem:
        """解析剧集数据"""
        guids = data.get('Guid', [])
        tmdb_id = None
        tvdb_id = None
        imdb_id = None
        
        for guid in guids:
            guid_id = guid.get('id', '')
            if guid_id.startswith('tmdb://'):
                tmdb_id = guid_id.replace('tmdb://', '')
            elif guid_id.startswith('tvdb://'):
                tvdb_id = guid_id.replace('tvdb://', '')
            elif guid_id.startswith('imdb://'):
                imdb_id = guid_id.replace('imdb://', '')
        
        return MediaItem(
            media_id=data.get('ratingKey'),
            title=data.get('title'),
            media_type='tv_series',
            year=data.get('year'),
            tmdb_id=tmdb_id,
            tvdb_id=tvdb_id,
            imdb_id=imdb_id,
            poster_url=self._get_image_url(data.get('thumb')),
            library_id=library_id,
        )
    
    def _parse_episode(self, data: Dict[str, Any]) -> MediaItem:
        """解析集数据"""
        guids = data.get('Guid', [])
        tmdb_id = None
        tvdb_id = None
        imdb_id = None
        
        for guid in guids:
            guid_id = guid.get('id', '')
            if guid_id.startswith('tmdb://'):
                tmdb_id = guid_id.replace('tmdb://', '')
            elif guid_id.startswith('tvdb://'):
                tvdb_id = guid_id.replace('tvdb://', '')
            elif guid_id.startswith('imdb://'):
                imdb_id = guid_id.replace('imdb://', '')
        
        return MediaItem(
            media_id=data.get('ratingKey'),
            title=data.get('grandparentTitle', data.get('title')),
            media_type='tv_series',
            year=data.get('year'),
            season=data.get('parentIndex'),
            episode=data.get('index'),
            tmdb_id=tmdb_id,
            tvdb_id=tvdb_id,
            imdb_id=imdb_id,
            poster_url=self._get_image_url(data.get('grandparentThumb')),
        )
    
    def _get_image_url(self, thumb_path: Optional[str]) -> Optional[str]:
        """获取图片URL"""
        if not thumb_path:
            return None
        return f"{self.url}{thumb_path}?X-Plex-Token={self.api_token}"

