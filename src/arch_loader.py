"""
架构识别和动态加载模块
支持根据系统架构自动选择对应的.so文件
"""
import platform
import sys
import os
from pathlib import Path
import importlib.util
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

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


def smart_import_with_extraction(module_name, fallback_classes=None, search_paths=None):
    """
    智能导入：优先本地加载，失败时尝试解压zip，最后使用回退版本
    
    Args:
        module_name: 模块名称
        fallback_classes: 回退类的字典
        search_paths: 搜索路径列表
    
    Returns:
        module: 加载的模块对象
    """
    if search_paths is None:
        search_paths = ['src', '.']
    
    print(f"[DEBUG] 开始智能导入模块: {module_name}")
    print(f"[DEBUG] 搜索路径: {search_paths}")
    
    # 首先尝试本地加载
    module = load_architecture_specific_module(module_name, search_paths)
    
    if module is not None:
        print(f"[DEBUG] 成功从本地加载模块: {module_name}")
        return module
    
    # 如果本地加载失败，尝试解压zip包
    print(f"[DEBUG] 本地未找到 {module_name}，尝试从zip包解压...")
    logger.info(f"本地未找到 {module_name}，尝试从zip包解压...")
    
    if auto_extract_so_modules():
        print(f"[DEBUG] zip解压成功，重新尝试加载模块: {module_name}")
        # 解压成功后重新尝试加载
        module = load_architecture_specific_module(module_name, search_paths)
        if module is not None:
            print(f"[DEBUG] 解压后成功加载模块: {module_name}")
            return module
        else:
            print(f"[DEBUG] 解压后仍无法加载模块: {module_name}")
    
    # 如果仍然失败，使用回退版本
    if fallback_classes:
        print(f"[DEBUG] 使用回退版本: {module_name}")
        return create_fallback_module(module_name, fallback_classes)
    
    raise ImportError(f"无法加载模块 {module_name}，且未提供回退版本")


# 使用示例和测试函数
def test_architecture_detection():
    """测试架构检测功能"""
    print(f"系统架构: {get_system_architecture()}")
    print(f"平台信息: {platform.platform()}")
    print(f"机器类型: {platform.machine()}")
    print(f"处理器: {platform.processor()}")


def extract_architecture_specific_modules(zip_path, extract_to=None, modules=None):
    """
    从zip包中解压架构特定的.so文件
    
    Args:
        zip_path: zip文件路径
        extract_to: 解压目标目录，默认为zip文件所在目录
        modules: 要解压的模块列表，默认为所有支持的模块
    
    Returns:
        dict: {module_name: extracted_path} 解压结果
    """
    import zipfile
    from pathlib import Path
    
    if modules is None:
        modules = ['security_core', 'rate_limiter']
    
    zip_path = Path(zip_path)
    if not zip_path.exists():
        logger.error(f"zip文件不存在: {zip_path}")
        return {}
    
    if extract_to is None:
        extract_to = zip_path.parent
    else:
        extract_to = Path(extract_to)
    
    current_arch = get_system_architecture()
    extracted_files = {}
    
    print(f"[DEBUG] 开始解压zip包: {zip_path}")
    print(f"[DEBUG] 解压目标目录: {extract_to}")
    print(f"[DEBUG] 要查找的模块: {modules}")
    print(f"[DEBUG] 当前架构: {current_arch}")
    
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_file:
            file_list = zip_file.namelist()
            print(f"[DEBUG] zip文件包含的所有文件:")
            for f in file_list:
                print(f"[DEBUG]   - {f}")
            
            logger.debug(f"zip文件包含: {file_list}")
            
            for module_name in modules:
                print(f"[DEBUG] 正在查找模块: {module_name}")
                
                # 查找当前架构的文件 - 支持多种命名格式
                possible_names = [
                    f"{module_name}.{current_arch}.so",
                    f"{module_name}_{current_arch}.so", 
                    f"{module_name}-{current_arch}.so"
                ]
                
                print(f"[DEBUG] 可能的文件名:")
                for name in possible_names:
                    print(f"[DEBUG]   - {name}")
                
                found_file = None
                for filename in file_list:
                    for possible_name in possible_names:
                        if filename.endswith(possible_name) or filename == possible_name:
                            found_file = filename
                            print(f"[DEBUG] 找到匹配文件: {filename}")
                            break
                    if found_file:
                        break
                
                if found_file:
                    # 解压并重命名为标准格式: module_name_arch.so
                    standard_name = f"{module_name}_{current_arch}.so"
                    target_path = extract_to / standard_name
                    
                    print(f"[DEBUG] 解压文件: {found_file} -> {target_path}")
                    
                    # 确保目标目录存在
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    # 解压文件
                    with zip_file.open(found_file) as source:
                        with open(target_path, 'wb') as target:
                            target.write(source.read())
                    
                    # 设置执行权限
                    import os
                    os.chmod(target_path, 0o755)
                    
                    extracted_files[module_name] = str(target_path)
                    logger.info(f"成功解压并重命名: {found_file} -> {standard_name}")
                    print(f"[DEBUG] 成功解压: {found_file} -> {standard_name}")
                else:
                    logger.warning(f"未在zip中找到模块 {module_name} 的 {current_arch} 架构版本")
                    print(f"[DEBUG] 未找到模块 {module_name} 的 {current_arch} 架构版本")
    
    except Exception as e:
        logger.error(f"解压zip文件时出错: {e}")
        print(f"[DEBUG] 解压zip文件时出错: {e}")
        return {}
    
    return extracted_files


def auto_extract_so_modules():
    """
    自动查找并解压src/so/so_modules.zip中的.so模块
    
    Returns:
        bool: 是否成功解压任何文件
    """
    zip_path = Path("src/so/so_modules.zip")
    
    print(f"[DEBUG] 正在查找zip包: {zip_path}")
    print(f"[DEBUG] zip包绝对路径: {zip_path.absolute()}")
    print(f"[DEBUG] zip包是否存在: {zip_path.exists()}")
    
    if not zip_path.exists():
        print(f"[DEBUG] 未找到.so模块包: {zip_path}")
        logger.debug(f"未找到.so模块包: {zip_path}")
        return False
    
    logger.info(f"发现.so模块包: {zip_path}")
    current_arch = get_system_architecture()
    logger.info(f"当前系统架构: {current_arch}")
    
    print(f"[DEBUG] 发现.so模块包: {zip_path}")
    print(f"[DEBUG] 当前系统架构: {current_arch}")
    
    # 解压到src目录
    extracted = extract_architecture_specific_modules(
        zip_path, 
        extract_to=Path("src")
    )
    
    if extracted:
        logger.info(f"从 {zip_path} 解压了 {len(extracted)} 个 {current_arch} 架构的模块")
        for module_name, file_path in extracted.items():
            logger.info(f"  - {module_name}: {file_path}")
        return True
    else:
        logger.warning(f"未找到适合 {current_arch} 架构的.so文件")
        print(f"[DEBUG] 未找到适合 {current_arch} 架构的.so文件")
    
    return False


if __name__ == "__main__":
    test_architecture_detection()
    auto_extract_so_modules()
