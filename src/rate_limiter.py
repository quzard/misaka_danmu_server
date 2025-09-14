import asyncio
import logging
import json
from pathlib import Path
import base64
import re
from datetime import datetime, timezone

from gmssl import sm2, sm3, func

from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from . import crud
from .scraper_manager import ScraperManager
from .timezone import get_now

logger = logging.getLogger(__name__)

class RateLimitExceededError(Exception):
    def __init__(self, message, retry_after_seconds):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds

class ConfigVerificationError(Exception):
    """当配置文件验证失败时引发。"""
    pass

XOR_KEY = b"T3Nn@pT^K!v8&s$U@w#Z&e3S@pT^K!v8&s$U@w#Z&e3S@pT^K!v8&s$U@w#Z&e3S@pT^K!v8&s$U@w#Z&e3S@pT^K!v8&s$U@w#Z&e3S@pT^K!v8&s$U@w#Z&e3S@pT^K!v8&s$U@w#Z&e3S@pT^K!v8&s$U@w#Z&e3S"

def _extract_hex_from_pem(pem_string: str) -> str:
    
    pem_string = re.sub(r'-----(BEGIN|END) PUBLIC KEY-----', '', pem_string)
    pem_string = pem_string.replace('\n', '').replace('\r', '')

    der_data = base64.b64decode(pem_string)

    public_key_bytes = der_data[-65:]
    return public_key_bytes.hex()

class RateLimiter:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], scraper_manager: ScraperManager):
        self._session_factory = session_factory
        self._scraper_manager = scraper_manager
        self._period_map = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
        self.logger = logging.getLogger(self.__class__.__name__)
        self._verification_failed: bool = False

        self.enabled: bool = True
        self.global_limit: int = 50
        self.global_period: str = "hour"

        try:
            config_dir = Path(__file__).parent / "rate_limit"
            config_path = config_dir / "rate_limit.bin"
            sig_path = config_dir / "rate_limit.bin.sig"
            pub_key_path = config_dir / "public_key.pem"

            if not all([config_path.exists(), sig_path.exists(), pub_key_path.exists()]):
                self.logger.critical("!!! 严重安全警告：流控配置文件不完整或缺失。")
                self.logger.critical("!!! 为保证安全，所有弹幕下载请求将被阻止，直到问题解决。")
                self._verification_failed = True
                raise FileNotFoundError("缺少流控配置文件")

            obfuscated_bytes = config_path.read_bytes()
            signature = sig_path.read_bytes().decode('utf-8').strip()
            public_key_pem = pub_key_path.read_text('utf-8')
            public_key_hex = _extract_hex_from_pem(public_key_pem)
            try:
                sm2_crypt = sm2.CryptSM2(public_key=public_key_hex, private_key='')
                sm3_hash = sm3.sm3_hash(func.bytes_to_list(obfuscated_bytes)) # type: ignore
                if not sm2_crypt.verify(signature, sm3_hash.encode('utf-8')):
                    self.logger.critical("!!! 严重安全警告：速率限制配置文件 'rate_limit.bin' 签名验证失败！文件可能已被篡改。")
                    self.logger.critical("!!! 为保证安全，所有弹幕下载请求将被阻止，直到问题解决。")
                    self._verification_failed = True
                    raise ConfigVerificationError("签名验证失败")
                
                self.logger.info("速率限制配置文件签名验证成功。")
            except (ValueError, TypeError, IndexError) as e:
                self.logger.critical(f"签名验证失败：无效的密钥或签名格式。错误: {e}", exc_info=True)
                self._verification_failed = True
                raise ConfigVerificationError("签名验证时发生格式错误")
            except Exception as e:
                self.logger.critical(f"签名验证过程中发生未知严重错误: {e}", exc_info=True)
                self._verification_failed = True
                raise ConfigVerificationError("签名验证时发生未知错误")

            try:
                json_bytes = bytearray()
                for i, byte in enumerate(obfuscated_bytes):
                    json_bytes.append(byte ^ XOR_KEY[i % len(XOR_KEY)])

                config_data = json.loads(json_bytes.decode('utf-8'))
                if config_data:
                    self.enabled = config_data.get("enabled", self.enabled)
                    self.global_limit = config_data.get("global_limit", self.global_limit)
                    self.global_period = config_data.get("global_period", self.global_period)
                    period_map_cn = {"second": "秒", "minute": "分钟", "hour": "小时", "day": "天"}
                    period_cn = period_map_cn.get(self.global_period, self.global_period)
                    self.logger.info(f"成功加载并验证了速率限制配置文件。参数: 启用={self.enabled}, 限制={self.global_limit}次/{period_cn}")
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                self.logger.error(f"解密或解析速率限制配置失败: {e}", exc_info=True)
                raise

        except Exception as e:
            if not self._verification_failed:
                self.logger.warning(f"加载速率限制配置时出错，将使用默认值。错误: {e}")

    async def _get_provider_quota(self, provider_name: str) -> Optional[int]:
        try:
            scraper = self._scraper_manager.get_scraper(provider_name)
            quota = getattr(scraper, 'rate_limit_quota', None)
            if quota is not None and quota > 0:
                return quota
        except (ValueError, AttributeError):
            pass
        return None

    def _get_global_limit(self) -> tuple[int, str]:
        if not self.enabled:
            return 0, "hour"
        return self.global_limit, self.global_period

    async def check(self, provider_name: str):
        if self._verification_failed:
            msg = "配置验证失败，所有请求已被安全阻止。"
            raise RateLimitExceededError(msg, retry_after_seconds=3600)

        global_limit, period_str = self._get_global_limit()
        if global_limit <= 0:
            return
        
        period_seconds = self._period_map.get(period_str, 3600)

        async with self._session_factory() as session:
            global_state = await crud.get_or_create_rate_limit_state(session, "__global__")
            provider_state = await crud.get_or_create_rate_limit_state(session, provider_name)

            now = get_now()
            time_since_reset = now - global_state.lastResetTime
            
            if time_since_reset.total_seconds() >= period_seconds:
                self.logger.info(f"全局速率限制周期已过，正在重置所有计数器。")
                await crud.reset_all_rate_limit_states(session)
                await session.commit()
                
                await session.refresh(global_state)
                await session.refresh(provider_state)
                
                time_since_reset = now - global_state.lastResetTime 

            if global_state.requestCount >= global_limit:
                retry_after = period_seconds - time_since_reset.total_seconds()
                msg = f"已达到全局速率限制 ({global_state.requestCount}/{global_limit})。"
                self.logger.warning(msg)
                raise RateLimitExceededError(msg, retry_after_seconds=max(0, retry_after))

            provider_quota = await self._get_provider_quota(provider_name)
            if provider_quota is not None and provider_state.requestCount >= provider_quota:
                retry_after = period_seconds - time_since_reset.total_seconds()
                msg = f"已达到源 '{provider_name}' 的特定配额 ({provider_state.requestCount}/{provider_quota})。"
                self.logger.warning(msg)
                raise RateLimitExceededError(msg, retry_after_seconds=max(0, retry_after))

    async def increment(self, provider_name: str):
        global_limit, _ = self._get_global_limit()
        if global_limit <= 0:
            return

        async with self._session_factory() as session:
            await crud.increment_rate_limit_count(session, "__global__")
            await crud.increment_rate_limit_count(session, provider_name)
            await session.commit()
            self.logger.debug(f"已为 '__global__' 和 '{provider_name}' 增加下载流控计数。")