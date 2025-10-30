"""
Jellyfin媒体服务器实现
Jellyfin API与Emby基本兼容,继承Emby实现
"""

from .emby import EmbyMediaServer


class JellyfinMediaServer(EmbyMediaServer):
    """
    Jellyfin媒体服务器
    API与Emby基本兼容,直接继承
    """
    
    async def test_connection(self) -> bool:
        """测试连接"""
        try:
            data = await self._request('GET', '/System/Info')
            # Jellyfin返回的字段与Emby相同
            return data is not None and 'ServerName' in data
        except Exception as e:
            self.logger.error(f"Jellyfin连接测试失败: {e}")
            return False
    
    def _get_headers(self):
        """Jellyfin使用相同的认证头"""
        return {
            'X-Emby-Token': self.api_token,  # Jellyfin兼容Emby的Token头
            'Accept': 'application/json',
        }

