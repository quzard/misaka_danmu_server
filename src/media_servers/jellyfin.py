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
    
    async def test_connection(self) -> Dict[str, Any]:
        """测试连接"""
        try:
            data = await self._request('GET', '/System/Info')
            # Jellyfin返回的字段与Emby相同
            if data and 'ServerName' in data:
                return {
                    "ServerName": data.get('ServerName'),
                    "Version": data.get('Version'),
                    "Id": data.get('Id')
                }
            raise Exception("无法获取服务器信息")
        except Exception as e:
            self.logger.error(f"Jellyfin连接测试失败: {e}")
            raise
    
    def _get_headers(self):
        """Jellyfin使用相同的认证头"""
        return {
            'X-Emby-Token': self.api_token,  # Jellyfin兼容Emby的Token头
            'Accept': 'application/json',
        }

