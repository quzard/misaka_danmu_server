"""
架构识别和动态加载模块
支持根据系统架构自动选择对应的.so文件
"""
import platform
import sys
import os
from pathlib import Path
import importlib.util


def get_system_architecture():
    """获取系统架构信息"""
    machine = platform.machine().lower()
    
    # 标准化架构名称
    if machine in ['x86_64', 'amd64']:
        return 'amd64'
    elif machine in ['aarch64', 'arm64']:
        return 'arm64'
    elif machine in ['i386', 'i686', 'x86']:
        return 'i386'
    elif machine.startswith('arm'):
        return 'arm'
    else:
        return machine


def find_architecture_specific_module(module_name, search_paths=None):
    """
    查找架构特定的模块文件
    
    Args:
        module_name: 模块名称（不含扩展名）
        search_paths: 搜索路径列表，默认为当前目录和src目录
    
    Returns:
        tuple: (found_path, architecture) 或 (None, None)
    """
    if search_paths is None:
        search_paths = ['.', 'src']
    
    current_arch = get_system_architecture()
    
    # 按优先级搜索架构特定文件
    arch_priorities = [
        current_arch,  # 当前架构优先
        'amd64',       # 通用x64
        'arm64',       # 通用ARM64
        ''             # 无架构后缀的通用版本
    ]
    
    for search_path in search_paths:
        search_dir = Path(search_path)
        if not search_dir.exists():
            continue
            
        for arch in arch_priorities:
            if arch:
                # 带架构后缀的文件名
                filename = f"{module_name}_{arch}.so"
            else:
                # 无后缀的通用文件名
                filename = f"{module_name}.so"
            
            file_path = search_dir / filename
            if file_path.exists():
                return str(file_path), arch if arch else 'generic'
    
    return None, None


def load_architecture_specific_module(module_name, search_paths=None):
    """
    加载架构特定的模块
    
    Args:
        module_name: 模块名称
        search_paths: 搜索路径列表
    
    Returns:
        module: 加载的模块对象，失败时返回None
    """
    module_path, arch = find_architecture_specific_module(module_name, search_paths)
    
    if not module_path:
        print(f"警告: 未找到模块 {module_name} 的任何架构版本")
        return None
    
    try:
        # 使用importlib动态加载模块
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None:
            print(f"错误: 无法创建模块规范 {module_path}")
            return None
        
        module = importlib.util.module_from_spec(spec)
        if module is None:
            print(f"错误: 无法创建模块对象 {module_path}")
            return None
        
        # 将模块添加到sys.modules中
        sys.modules[module_name] = module
        
        # 执行模块
        spec.loader.exec_module(module)
        
        print(f"成功加载模块: {module_name} (架构: {arch}, 路径: {module_path})")
        return module
        
    except Exception as e:
        print(f"错误: 加载模块 {module_path} 失败: {e}")
        return None


def create_fallback_module(module_name, fallback_classes=None):
    """
    创建回退模块，当无法加载.so文件时使用
    
    Args:
        module_name: 模块名称
        fallback_classes: 回退类的字典 {class_name: class_object}
    
    Returns:
        module: 回退模块对象
    """
    import types
    
    fallback_module = types.ModuleType(module_name)
    
    if fallback_classes:
        for class_name, class_obj in fallback_classes.items():
            setattr(fallback_module, class_name, class_obj)
    
    # 添加标识，表明这是回退版本
    fallback_module.__is_fallback__ = True
    
    print(f"使用回退模块: {module_name}")
    return fallback_module


def smart_import(module_name, fallback_classes=None, search_paths=None):
    """
    智能导入：优先尝试加载架构特定的.so文件，失败时使用回退版本
    
    Args:
        module_name: 模块名称
        fallback_classes: 回退类的字典
        search_paths: 搜索路径列表
    
    Returns:
        module: 加载的模块对象
    """
    # 首先尝试加载架构特定的.so文件
    module = load_architecture_specific_module(module_name, search_paths)
    
    if module is not None:
        return module
    
    # 如果加载失败，使用回退版本
    if fallback_classes:
        return create_fallback_module(module_name, fallback_classes)
    
    # 如果没有回退版本，抛出异常
    raise ImportError(f"无法加载模块 {module_name}，且未提供回退版本")


# 使用示例和测试函数
def test_architecture_detection():
    """测试架构检测功能"""
    print(f"系统架构: {get_system_architecture()}")
    print(f"平台信息: {platform.platform()}")
    print(f"机器类型: {platform.machine()}")
    print(f"处理器: {platform.processor()}")


if __name__ == "__main__":
    test_architecture_detection()
