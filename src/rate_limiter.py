"""
速率限制器模块 - 支持架构识别和动态加载
优先加载架构特定的.so文件，失败时使用Python回退版本
"""
import logging
from typing import Optional, Dict, Any
from .arch_loader import smart_import


logger = logging.getLogger(__name__)


class RateLimitExceededError(Exception):
    """速率限制超出异常"""
    def __init__(self, message: str, retry_after_seconds: float = 0):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class PythonRateLimiter:
    """Python版本的速率限制器（回退版本）"""
    
    def __init__(self, session_factory, scraper_manager):
        self.session_factory = session_factory
        self.scraper_manager = scraper_manager
        self.enabled = False
        self.global_limit = 50
        self.global_period_seconds = 3600
        self.provider_limits = {}
        self.last_check_time = {}
        self.request_counts = {}
        
        logger.warning("使用Python回退版本的速率限制器，功能可能受限")
    
    async def check(self, provider_name: str) -> None:
        """检查速率限制（简化版本）"""
        if not self.enabled:
            return
        
        # 简单的内存计数器实现
        import time
        current_time = time.time()
        
        # 重置计数器（如果超过周期）
        if provider_name in self.last_check_time:
            if current_time - self.last_check_time[provider_name] > self.global_period_seconds:
                self.request_counts[provider_name] = 0
                self.last_check_time[provider_name] = current_time
        else:
            self.last_check_time[provider_name] = current_time
            self.request_counts[provider_name] = 0
        
        # 检查限制
        current_count = self.request_counts.get(provider_name, 0)
        if current_count >= self.global_limit:
            retry_after = self.global_period_seconds - (current_time - self.last_check_time[provider_name])
            raise RateLimitExceededError(
                f"速率限制超出: {provider_name} ({current_count}/{self.global_limit})",
                retry_after_seconds=max(0, retry_after)
            )
        
        # 增加计数
        self.request_counts[provider_name] = current_count + 1
    
    async def get_status(self) -> Dict[str, Any]:
        """获取速率限制状态"""
        return {
            "globalEnabled": self.enabled,
            "providers": []
        }
    
    async def reload_config(self) -> bool:
        """重新加载配置"""
        logger.info("Python回退版本：配置重载功能未实现")
        return False


class SecurityCore:
    """安全核心模块（回退版本）"""
    
    def __init__(self):
        logger.warning("使用Python回退版本的安全核心模块，功能可能受限")
    
    def verify_signature(self, data: bytes, signature: str, public_key: str) -> bool:
        """验证签名（简化版本）"""
        logger.warning("Python回退版本：签名验证功能未实现")
        return True
    
    def decrypt_config(self, encrypted_data: bytes, key: bytes) -> bytes:
        """解密配置（简化版本）"""
        logger.warning("Python回退版本：配置解密功能未实现")
        return encrypted_data


# 定义回退类
FALLBACK_CLASSES = {
    'RateLimiter': PythonRateLimiter,
    'RateLimitExceededError': RateLimitExceededError,
    'SecurityCore': SecurityCore
}

# 尝试智能导入
try:
    # 首先尝试加载架构特定的rate_limiter模块
    rate_limiter_module = smart_import('rate_limiter', FALLBACK_CLASSES, ['src', '.'])
    
    # 导出所需的类和函数
    RateLimiter = getattr(rate_limiter_module, 'RateLimiter', PythonRateLimiter)
    RateLimitExceededError = getattr(rate_limiter_module, 'RateLimitExceededError', RateLimitExceededError)
    
    # 检查是否使用了回退版本
    if hasattr(rate_limiter_module, '__is_fallback__'):
        logger.warning("正在使用Python回退版本的速率限制器")
    else:
        logger.info("成功加载架构特定的速率限制器模块")

except ImportError as e:
    logger.error(f"无法加载速率限制器模块: {e}")
    # 使用纯Python回退版本
    RateLimiter = PythonRateLimiter
    RateLimitExceededError = RateLimitExceededError

# 尝试加载安全核心模块
try:
    security_core_module = smart_import('security_core', {'SecurityCore': SecurityCore}, ['src', '.'])
    SecurityCore = getattr(security_core_module, 'SecurityCore', SecurityCore)
    
    if hasattr(security_core_module, '__is_fallback__'):
        logger.warning("正在使用Python回退版本的安全核心模块")
    else:
        logger.info("成功加载架构特定的安全核心模块")

except ImportError as e:
    logger.warning(f"无法加载安全核心模块，使用回退版本: {e}")
    SecurityCore = SecurityCore


# 导出所有需要的符号
__all__ = ['RateLimiter', 'RateLimitExceededError', 'SecurityCore']


def get_module_info():
    """获取当前加载的模块信息"""
    info = {
        'rate_limiter_type': 'fallback' if RateLimiter == PythonRateLimiter else 'compiled',
        'security_core_type': 'fallback' if SecurityCore.__name__ == 'SecurityCore' else 'compiled',
        'architecture': None,
        'loaded_files': []
    }
    
    try:
        from .arch_loader import get_system_architecture, find_architecture_specific_module
        info['architecture'] = get_system_architecture()
        
        # 检查实际加载的文件
        for module_name in ['rate_limiter', 'security_core']:
            file_path, arch = find_architecture_specific_module(module_name, ['src', '.'])
            if file_path:
                info['loaded_files'].append({
                    'module': module_name,
                    'path': file_path,
                    'architecture': arch
                })
    except Exception as e:
        logger.debug(f"获取模块信息时出错: {e}")
    
    return info


if __name__ == "__main__":
    # 测试模块加载
    print("速率限制器模块信息:")
    info = get_module_info()
    for key, value in info.items():
        print(f"  {key}: {value}")
