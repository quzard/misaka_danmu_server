"""
安全核心模块 - 支持架构识别和动态加载
优先加载架构特定的.so文件，失败时使用Python回退版本
"""
import logging
from typing import Optional, Dict, Any, Union
from .arch_loader import smart_import


logger = logging.getLogger(__name__)


class PythonSecurityCore:
    """Python版本的安全核心模块（回退版本）"""
    
    def __init__(self):
        logger.warning("使用Python回退版本的安全核心模块，功能可能受限")
        self._initialized = False
    
    def initialize(self) -> bool:
        """初始化安全核心"""
        self._initialized = True
        logger.info("Python回退版本安全核心已初始化")
        return True
    
    def verify_signature(self, data: bytes, signature: str, public_key: str, uid: str = "") -> bool:
        """验证数字签名（简化版本）"""
        logger.warning("Python回退版本：签名验证功能未完全实现，总是返回True")
        return True
    
    def decrypt_config(self, encrypted_data: bytes, key: bytes) -> bytes:
        """解密配置数据（简化版本）"""
        logger.warning("Python回退版本：配置解密功能未完全实现，返回原始数据")
        return encrypted_data
    
    def encrypt_config(self, data: bytes, key: bytes) -> bytes:
        """加密配置数据（简化版本）"""
        logger.warning("Python回退版本：配置加密功能未完全实现，返回原始数据")
        return data
    
    def generate_key_pair(self) -> tuple[str, str]:
        """生成密钥对（简化版本）"""
        logger.warning("Python回退版本：密钥对生成功能未实现")
        return ("", "")
    
    def hash_data(self, data: bytes) -> str:
        """计算数据哈希（简化版本）"""
        import hashlib
        return hashlib.sha256(data).hexdigest()
    
    def verify_integrity(self, file_path: str, expected_hash: str) -> bool:
        """验证文件完整性（简化版本）"""
        try:
            with open(file_path, 'rb') as f:
                data = f.read()
            actual_hash = self.hash_data(data)
            return actual_hash == expected_hash
        except Exception as e:
            logger.error(f"文件完整性验证失败: {e}")
            return False
    
    def get_version(self) -> str:
        """获取版本信息"""
        return "Python回退版本 v1.0.0"
    
    def is_compiled(self) -> bool:
        """检查是否为编译版本"""
        return False


# 定义回退类
FALLBACK_CLASSES = {
    'SecurityCore': PythonSecurityCore
}

# 尝试智能导入
try:
    # 首先尝试加载架构特定的security_core模块
    security_core_module = smart_import('security_core', FALLBACK_CLASSES, ['src', '.'])
    
    # 导出所需的类
    SecurityCore = getattr(security_core_module, 'SecurityCore', PythonSecurityCore)
    
    # 检查是否使用了回退版本
    if hasattr(security_core_module, '__is_fallback__'):
        logger.warning("正在使用Python回退版本的安全核心模块")
    else:
        logger.info("成功加载架构特定的安全核心模块")

except ImportError as e:
    logger.error(f"无法加载安全核心模块: {e}")
    # 使用纯Python回退版本
    SecurityCore = PythonSecurityCore

# 导出所有需要的符号
__all__ = ['SecurityCore']


def get_security_info():
    """获取安全模块信息"""
    info = {
        'type': 'fallback' if SecurityCore == PythonSecurityCore else 'compiled',
        'version': None,
        'architecture': None,
        'loaded_file': None
    }
    
    try:
        # 创建实例获取版本信息
        core = SecurityCore()
        if hasattr(core, 'get_version'):
            info['version'] = core.get_version()
        if hasattr(core, 'is_compiled'):
            info['type'] = 'compiled' if core.is_compiled() else 'fallback'
        
        # 获取架构信息
        from .arch_loader import get_system_architecture, find_architecture_specific_module
        info['architecture'] = get_system_architecture()
        
        # 检查实际加载的文件
        file_path, arch = find_architecture_specific_module('security_core', ['src', '.'])
        if file_path:
            info['loaded_file'] = {
                'path': file_path,
                'architecture': arch
            }
    except Exception as e:
        logger.debug(f"获取安全模块信息时出错: {e}")
    
    return info


# 创建全局实例（如果需要）
_global_security_core = None

def get_security_core():
    """获取全局安全核心实例"""
    global _global_security_core
    if _global_security_core is None:
        _global_security_core = SecurityCore()
        if hasattr(_global_security_core, 'initialize'):
            _global_security_core.initialize()
    return _global_security_core


if __name__ == "__main__":
    # 测试模块加载
    print("安全核心模块信息:")
    info = get_security_info()
    for key, value in info.items():
        print(f"  {key}: {value}")
    
    # 测试功能
    print("\n功能测试:")
    core = get_security_core()
    test_data = b"Hello, World!"
    hash_result = core.hash_data(test_data)
    print(f"  数据哈希: {hash_result}")
    print(f"  签名验证: {core.verify_signature(test_data, 'dummy_sig', 'dummy_key')}")
