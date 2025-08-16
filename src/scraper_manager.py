import asyncio
import importlib
import pkgutil
import secrets
import inspect
import logging
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from pathlib import Path
from typing import Dict, List, Optional, Any, Type
from urllib.parse import urlparse
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from .scrapers.base import BaseScraper
from .config_manager import ConfigManager
from .models import ProviderSearchInfo
from . import crud

class ScraperManager:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], config_manager: ConfigManager):
        self.scrapers: Dict[str, BaseScraper] = {}
        self._scraper_classes: Dict[str, Type[BaseScraper]] = {}
        self.scraper_settings: Dict[str, Dict[str, Any]] = {}
        self._session_factory = session_factory
        self._domain_map: Dict[str, str] = {}
        self._public_key = None
        self._verified_scrapers: set[str] = set()
        self._verification_enabled: bool = False
        self.config_manager = config_manager
        # 注意：加载逻辑现在是异步的，将在应用启动时调用

    def _load_public_key(self):
        """从 config/public_key.pem 加载公钥。"""
        key_path = Path(__file__).parent.parent / "config" / "public_key.pem"
        if not key_path.exists():
            logging.getLogger(__name__).warning("公钥文件 'config/public_key.pem' 未找到。所有搜索源都将无法通过验证。")
            self._public_key = None
            return
        
        try:
            with open(key_path, "rb") as key_file:
                self._public_key = serialization.load_pem_public_key(key_file.read())
            logging.getLogger(__name__).info("公钥加载成功。")
        except Exception as e:
            logging.getLogger(__name__).error(f"加载公钥失败: {e}", exc_info=True)
            self._public_key = None
    def _load_scrapers(self):
        """
        动态发现并加载 'scrapers' 目录下的所有搜索源类。
        """
        scrapers_dir = Path(__file__).parent / "scrapers"
        for file in scrapers_dir.glob("*.py"):
            if file.name.startswith("_") or file.name == "base.py":
                continue

            module_name = f".scrapers.{file.stem}"
            try:
                module = importlib.import_module(module_name, package="src")
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if issubclass(obj, BaseScraper) and obj is not BaseScraper:
                        scraper_instance = obj()
                        if scraper_instance.provider_name in self.scrapers:
                            print(f"警告: 发现重复的搜索源 '{scraper_instance.provider_name}'。将被覆盖。")
                        self.scrapers[scraper_instance.provider_name] = scraper_instance
                        print(f"搜索源 '{scraper_instance.provider_name}' 已加载。")
            except Exception as e:
                print(f"从 {file.name} 加载搜索源失败: {e}")
    
    async def load_and_sync_scrapers(self):
        """
        动态发现、同步到数据库并根据数据库设置加载搜索源。
        此方法可以被再次调用以重新加载搜索源。
        """
        # 清理现有爬虫以确保全新加载
        await self.close_all()
        self.scrapers.clear()
        self._scraper_classes.clear()
        self.scraper_settings.clear()
        self._verified_scrapers.clear()

        self._domain_map.clear()
        discovered_providers = []
        scraper_classes = {}

        # 使用 pkgutil 发现模块，这对于 .py, .pyc, .so 文件都有效
        scrapers_package_path = [str(Path(__file__).parent / "scrapers")]
        for finder, name, ispkg in pkgutil.iter_modules(scrapers_package_path):
            if name.startswith("_") or name == "base":
                continue
            try:
                module_name = f"src.scrapers.{name}"
                module = importlib.import_module(module_name)
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if issubclass(obj, BaseScraper) and obj is not BaseScraper:
                        provider_name = obj.provider_name # 直接访问类属性，避免实例化
                        discovered_providers.append(provider_name)
                        # (新增) 注册该刮削器能处理的域名
                        for domain in getattr(obj, 'handled_domains', []):
                            self._domain_map[domain] = provider_name
                        self._scraper_classes[provider_name] = obj

                        # --- 验证逻辑 ---
                        if self._verification_enabled:
                            # 实例化以进行验证
                            temp_instance = obj(self._session_factory, self.config_manager)
                            is_verified = await self.verify_scraper(temp_instance)
                            if is_verified:
                                self._verified_scrapers.add(provider_name)
                                logging.getLogger(__name__).info(f"✅ 搜索源 '{provider_name}' 验证成功。")
                            else:
                                logging.getLogger(__name__).warning(f"❌ 搜索源 '{provider_name}' 验证失败！该源将被禁用。")
                            # 验证后可以立即关闭临时实例
                            await temp_instance.close()
                        else:
                            # 如果验证被禁用，则将所有源视为已验证
                            self._verified_scrapers.add(provider_name)
                        # --- 验证逻辑结束 ---

            except TypeError as e:
                if "couldn't parse file content" in str(e).lower():
                    # 这是一个针对 protobuf 版本不兼容的特殊情况。
                    error_msg = (
                        f"加载搜索源模块 {module_name} 失败，疑似 protobuf 版本不兼容。 "
                        f"请确保已将 'protobuf' 版本固定为 '3.20.3' (在 requirements.txt 中), "
                        f"并且已经通过 'docker-compose build' 命令重新构建了您的 Docker 镜像。"
                    )
                    logging.getLogger(__name__).error(error_msg)
                else:
                    # 正常处理其他 TypeError
                    logging.getLogger(__name__).error(f"加载搜索源模块 {module_name} 失败，已跳过。错误: {e}", exc_info=True)
            except Exception as e:
                # 使用标准日志记录器
                logging.getLogger(__name__).error(f"加载搜索源模块 {module_name} 失败，已跳过。错误: {e}", exc_info=True)
        
        # 新增：在同步新搜索源之前，先从数据库中移除不再存在的过时搜索源。
        async with self._session_factory() as session:
            await crud.remove_stale_scrapers(session, discovered_providers)
        
        async with self._session_factory() as session:
            await crud.sync_scrapers_to_db(session, discovered_providers)
            settings_list = await crud.get_all_scraper_settings(session)
        self.scraper_settings = {s['provider_name']: s for s in settings_list}

        # Instantiate all discovered scrapers
        for provider_name, scraper_class in self._scraper_classes.items():
            self.scrapers[provider_name] = scraper_class(self._session_factory, self.config_manager)
            setting = self.scraper_settings.get(provider_name, {})
            
            # 如果源未通过验证，则强制禁用它
            is_verified = provider_name in self._verified_scrapers
            is_enabled_by_user = setting.get('is_enabled', True)
            
            final_status = "已启用" if is_enabled_by_user and is_verified else "已禁用"
            verification_status = "已验证" if is_verified else "未验证"
            
            if setting:
                order = setting.get('display_order', 'N/A')
                logging.getLogger(__name__).info(f"已加载搜索源 '{provider_name}' (状态: {final_status}, 顺序: {order}, 验证: {verification_status})。")
            else:
                logging.getLogger(__name__).warning(f"已加载搜索源 '{provider_name}'，但在数据库中未找到其设置。")

    async def initialize(self):
        """
        初始化管理器，包括加载公钥和同步搜索源。
        """
        self._load_public_key()
        # 从配置中读取验证开关的状态
        verification_enabled_str = await self.config_manager.get("scraper_verification_enabled", "false")
        self._verification_enabled = verification_enabled_str.lower() == 'true'
        if not self._verification_enabled:
            logging.getLogger(__name__).info("搜索源签名验证已禁用。所有搜索源将被视为已验证。")

        await self.load_and_sync_scrapers()

    @property
    def has_enabled_scrapers(self) -> bool:
        """检查是否有任何已启用的爬虫。"""
        return any(s.get('is_enabled') for s in self.scraper_settings.values())

    async def search_all(self, keywords: List[str], episode_info: Optional[Dict[str, Any]] = None) -> List[ProviderSearchInfo]:
        """
        在所有已启用的搜索源上并发搜索关键词列表。
        """
        enabled_scrapers = [
            scraper for name, scraper in self.scrapers.items()
            if self.scraper_settings.get(name, {}).get('is_enabled') and name in self._verified_scrapers
        ]

        if not enabled_scrapers:
            return []

        tasks = []
        for keyword in keywords:
            for scraper in enabled_scrapers:
                tasks.append(scraper.search(keyword, episode_info=episode_info))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_search_results = []
        seen_results = set() # 用于去重

        for result in results:
            if isinstance(result, Exception):
                logging.getLogger(__name__).error(f"搜索任务中出现错误: {result}")
            elif result:
                for item in result:
                    # 使用 (provider, mediaId) 作为唯一标识符
                    unique_id = (item.provider, item.mediaId)
                    if unique_id not in seen_results:
                        all_search_results.append(item)
                        seen_results.add(unique_id)

        return all_search_results

    async def search_sequentially(self, keyword: str, episode_info: Optional[Dict[str, Any]] = None) -> Optional[tuple[str, List[ProviderSearchInfo]]]:
        """
        按用户定义的顺序，在已启用的搜索源上顺序搜索。
        一旦找到任何结果，立即停止并返回提供方名称和结果列表。
        """
        if not self.scrapers:
            return None, None

        # 使用缓存的设置来获取有序且已启用的搜索源列表
        ordered_providers = sorted(
            # 修正：只有已启用且已验证的源才能参与顺序搜索
            [p for p, s in self.scraper_settings.items() if s.get('is_enabled') and p in self._verified_scrapers],
            key=lambda p: self.scraper_settings[p].get('display_order', 99)
        )

        for provider_name in ordered_providers:
            scraper = self.scrapers.get(provider_name)
            if not scraper: continue

            try:
                results = await scraper.search(keyword, episode_info=episode_info)
                if results:
                    return provider_name, results
            except Exception as e:
                logging.getLogger(__name__).error(f"顺序搜索时，提供方 '{provider_name}' 发生错误: {e}", exc_info=True)
        
        return None, None

    async def close_all(self):
        """关闭所有搜索源的客户端。"""
        tasks = [scraper.close() for scraper in self.scrapers.values()]
        await asyncio.gather(*tasks, return_exceptions=True)

    def get_scraper(self, provider: str) -> BaseScraper:
        """通过名称获取指定的搜索源实例。"""
        scraper = self.scrapers.get(provider)
        if not scraper:
            raise ValueError(f"未找到提供方为 '{provider}' 的搜索源")
        return scraper

    def get_scraper_class(self, provider_name: str) -> Optional[Type[BaseScraper]]:
        """获取刮削器的类，而不实例化它。"""
        return self._scraper_classes.get(provider_name)

    def get_scraper_by_domain(self, url: str) -> Optional[BaseScraper]:
        """
        (新增) 通过URL的域名查找合适的刮削器实例。
        """
        try:
            domain = urlparse(url).netloc
            provider_name = self._domain_map.get(domain)
            return self.get_scraper(provider_name) if provider_name else None
        except Exception:
            return None

    async def verify_scraper(self, scraper: BaseScraper) -> bool:
        """对单个搜索源实例执行挑战-响应签名验证。"""
        if not self._verification_enabled:
            return True # 如果功能被禁用，则所有源都通过验证

        if not self._public_key:
            return False # 如果没有公钥，所有验证都失败
        
        challenge = secrets.token_hex(32)
        try:
            signature = scraper.sign_challenge(challenge)
            if signature is None:
                return False
            
            self._public_key.verify(
                signature,
                challenge.encode('utf-8'),
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
            return True
        except Exception:
            return False
