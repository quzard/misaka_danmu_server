"""
检查预下载相关配置的脚本
用于诊断预下载机制是否正确配置
"""
import asyncio
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select, text
from src.orm_models import Config
from src.config import get_settings

async def check_config():
    """检查预下载相关配置"""
    settings = get_settings()
    
    # 创建数据库引擎
    engine = create_async_engine(
        settings.database.url,
        echo=False,
        pool_pre_ping=True
    )
    
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    
    async with async_session() as session:
        print("=" * 60)
        print("预下载配置检查")
        print("=" * 60)
        
        # 检查的配置项
        config_keys = [
            "preDownloadNextEpisodeEnabled",
            "matchFallbackEnabled", 
            "searchFallbackEnabled"
        ]
        
        for key in config_keys:
            stmt = select(Config).where(Config.configKey == key)
            result = await session.execute(stmt)
            config = result.scalar_one_or_none()
            
            if config:
                value = config.configValue
                status = "✓ 已启用" if value.lower() == "true" else "✗ 未启用"
                print(f"\n{key}:")
                print(f"  值: {value}")
                print(f"  状态: {status}")
                if config.description:
                    print(f"  说明: {config.description}")
            else:
                print(f"\n{key}:")
                print(f"  状态: ⚠ 配置项不存在")
        
        print("\n" + "=" * 60)
        print("诊断结果:")
        print("=" * 60)
        
        # 获取配置值
        configs = {}
        for key in config_keys:
            stmt = select(Config.configValue).where(Config.configKey == key)
            result = await session.execute(stmt)
            value = result.scalar_one_or_none()
            configs[key] = value.lower() == "true" if value else False
        
        predownload = configs.get("preDownloadNextEpisodeEnabled", False)
        match_fallback = configs.get("matchFallbackEnabled", False)
        search_fallback = configs.get("searchFallbackEnabled", False)
        
        if not predownload:
            print("✗ 预下载功能未启用")
            print("  建议: 在Web界面的 '弹幕源设置 > 匹配后备设置' 中启用预下载")
        elif not match_fallback and not search_fallback:
            print("✗ 预下载已启用，但未启用任何后备机制")
            print("  建议: 至少启用以下之一:")
            print("    - 匹配后备 (matchFallbackEnabled)")
            print("    - 后备搜索 (searchFallbackEnabled)")
        else:
            print("✓ 预下载配置正确!")
            print(f"  - 预下载: 已启用")
            if match_fallback:
                print(f"  - 匹配后备: 已启用")
            if search_fallback:
                print(f"  - 后备搜索: 已启用")
        
        print("\n" + "=" * 60)
        
        # 检查数据库中是否有分集数据
        episode_count_stmt = text("SELECT COUNT(*) FROM episodes")
        result = await session.execute(episode_count_stmt)
        episode_count = result.scalar()
        print(f"数据库中的分集数量: {episode_count}")
        
        if episode_count == 0:
            print("⚠ 数据库中没有分集数据，预下载无法工作")
        
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(check_config())

