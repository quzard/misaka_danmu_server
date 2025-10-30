"""
Emby媒体服务器实现
"""

from typing import List, Dict, Any, Optional
from .base import BaseMediaServer, MediaLibrary, MediaItem


class EmbyMediaServer(BaseMediaServer):
    """Emby媒体服务器"""
    
    async def test_connection(self) -> bool:
        """测试连接"""
        try:
            data = await self._request('GET', '/System/Info')
            return data is not None and 'ServerName' in data
        except Exception as e:
            self.logger.error(f"Emby连接测试失败: {e}")
            return False
    
    async def get_libraries(self) -> List[MediaLibrary]:
        """获取所有媒体库"""
        try:
            data = await self._request('GET', '/Library/VirtualFolders')
            libraries = []
            
            for item in data or []:
                lib_type = item.get('CollectionType', 'mixed')
                # 转换Emby的类型到统一类型
                if lib_type == 'movies':
                    unified_type = 'movies'
                elif lib_type == 'tvshows':
                    unified_type = 'tvshows'
                else:
                    unified_type = 'mixed'
                
                libraries.append(MediaLibrary(
                    id=item.get('ItemId'),
                    name=item.get('Name'),
                    type=unified_type
                ))
            
            return libraries
        except Exception as e:
            self.logger.error(f"获取Emby媒体库失败: {e}")
            return []
    
    async def get_library_items(
        self,
        library_id: str,
        media_type: Optional[str] = None
    ) -> List[MediaItem]:
        """获取媒体库中的所有项"""
        try:
            params = {
                'ParentId': library_id,
                'Recursive': 'true',
                'Fields': 'ProviderIds,ProductionYear,Overview',
            }
            
            # 根据类型过滤
            if media_type == 'movie':
                params['IncludeItemTypes'] = 'Movie'
            elif media_type == 'tv_series':
                params['IncludeItemTypes'] = 'Series'
            
            data = await self._request('GET', '/Items', params=params)
            items = []
            
            for item in data.get('Items', []):
                item_type = item.get('Type')
                
                if item_type == 'Movie':
                    items.append(self._parse_movie(item, library_id))
                elif item_type == 'Series':
                    items.append(self._parse_series(item, library_id))
            
            return items
        except Exception as e:
            self.logger.error(f"获取Emby媒体库项失败: {e}")
            return []
    
    async def get_item_details(self, item_id: str) -> Optional[MediaItem]:
        """获取单个媒体项详情"""
        try:
            data = await self._request('GET', f'/Users/{{UserId}}/Items/{item_id}')
            if not data:
                return None
            
            item_type = data.get('Type')
            if item_type == 'Movie':
                return self._parse_movie(data)
            elif item_type == 'Series':
                return self._parse_series(data)
            elif item_type == 'Episode':
                return self._parse_episode(data)
            
            return None
        except Exception as e:
            self.logger.error(f"获取Emby媒体项详情失败: {e}")
            return None
    
    async def get_tv_seasons(self, series_id: str) -> List[Dict[str, Any]]:
        """获取电视节目的所有季度"""
        try:
            params = {
                'ParentId': series_id,
                'Fields': 'ChildCount',
            }
            data = await self._request('GET', '/Items', params=params)
            
            seasons = []
            for item in data.get('Items', []):
                if item.get('Type') == 'Season':
                    seasons.append({
                        'season_id': item.get('Id'),
                        'season_number': item.get('IndexNumber', 0),
                        'episode_count': item.get('ChildCount', 0),
                    })
            
            return sorted(seasons, key=lambda x: x['season_number'])
        except Exception as e:
            self.logger.error(f"获取Emby季度信息失败: {e}")
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
            
            params = {
                'ParentId': season_id,
                'Fields': 'ProviderIds,ProductionYear',
            }
            data = await self._request('GET', '/Items', params=params)
            
            episodes = []
            for item in data.get('Items', []):
                if item.get('Type') == 'Episode':
                    episodes.append(self._parse_episode(item))
            
            return sorted(episodes, key=lambda x: x.episode or 0)
        except Exception as e:
            self.logger.error(f"获取Emby集数信息失败: {e}")
            return []
    
    def _parse_movie(self, data: Dict[str, Any], library_id: Optional[str] = None) -> MediaItem:
        """解析电影数据"""
        provider_ids = data.get('ProviderIds', {})
        
        return MediaItem(
            media_id=data.get('Id'),
            title=data.get('Name'),
            media_type='movie',
            year=data.get('ProductionYear'),
            tmdb_id=provider_ids.get('Tmdb'),
            tvdb_id=provider_ids.get('Tvdb'),
            imdb_id=provider_ids.get('Imdb'),
            poster_url=self._get_image_url(data.get('Id'), 'Primary'),
            library_id=library_id,
        )
    
    def _parse_series(self, data: Dict[str, Any], library_id: Optional[str] = None) -> MediaItem:
        """解析剧集数据"""
        provider_ids = data.get('ProviderIds', {})
        
        return MediaItem(
            media_id=data.get('Id'),
            title=data.get('Name'),
            media_type='tv_series',
            year=data.get('ProductionYear'),
            tmdb_id=provider_ids.get('Tmdb'),
            tvdb_id=provider_ids.get('Tvdb'),
            imdb_id=provider_ids.get('Imdb'),
            poster_url=self._get_image_url(data.get('Id'), 'Primary'),
            library_id=library_id,
        )
    
    def _parse_episode(self, data: Dict[str, Any]) -> MediaItem:
        """解析集数据"""
        provider_ids = data.get('ProviderIds', {})
        
        return MediaItem(
            media_id=data.get('Id'),
            title=data.get('SeriesName', data.get('Name')),
            media_type='tv_series',
            year=data.get('ProductionYear'),
            season=data.get('ParentIndexNumber'),
            episode=data.get('IndexNumber'),
            tmdb_id=provider_ids.get('Tmdb'),
            tvdb_id=provider_ids.get('Tvdb'),
            imdb_id=provider_ids.get('Imdb'),
            poster_url=self._get_image_url(data.get('SeriesId'), 'Primary'),
        )
    
    def _get_image_url(self, item_id: str, image_type: str = 'Primary') -> Optional[str]:
        """获取图片URL"""
        if not item_id:
            return None
        return f"{self.url}/Items/{item_id}/Images/{image_type}"

