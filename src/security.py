from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
import uuid
import ipaddress
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from . import crud, models
from .config import settings
from .database import get_db_session
from .timezone import get_now
from .crud import session as session_crud

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/ui/auth/token")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """生成密码哈希"""
    return pwd_context.hash(password)


async def get_real_client_ip(request: Request, config_manager) -> str:
    """
    获取真实客户端IP，支持信任反代。

    :param request: FastAPI Request 对象
    :param config_manager: 配置管理器
    :return: 客户端真实IP
    """
    trusted_proxies_str = await config_manager.get("trustedProxies", "")
    trusted_networks = []
    if trusted_proxies_str:
        for proxy_entry in trusted_proxies_str.split(','):
            try:
                trusted_networks.append(ipaddress.ip_network(proxy_entry.strip()))
            except ValueError:
                logger.warning(f"无效的受信任代理IP或CIDR: '{proxy_entry.strip()}'，已忽略。")

    client_ip_str = request.client.host if request.client else "127.0.0.1"
    is_trusted = False
    if trusted_networks:
        try:
            client_addr = ipaddress.ip_address(client_ip_str)
            is_trusted = any(client_addr in network for network in trusted_networks)
        except ValueError:
            logger.warning(f"无法将客户端IP '{client_ip_str}' 解析为有效的IP地址。")

    if is_trusted:
        x_forwarded_for = request.headers.get("x-forwarded-for")
        if x_forwarded_for:
            client_ip_str = x_forwarded_for.split(',')[0].strip()
        else:
            client_ip_str = request.headers.get("x-real-ip", client_ip_str)

    return client_ip_str


async def _get_user_from_token(token: str, session: AsyncSession, validate_session: bool = True) -> Tuple[models.User, Optional[str]]:
    """
    核心逻辑：解码JWT，验证其有效性，并获取当前用户。
    这是一个不带FastAPI依赖的辅助函数。

    :param token: JWT 令牌
    :param session: 数据库会话
    :param validate_session: 是否验证会话有效性（检查 jti 是否在会话表中且未撤销）
    :return: (用户对象, jti)
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exception
    try:
        secret_key = await crud.get_config_value(session, 'jwtSecretKey', settings.jwt.secret_key)
        payload = jwt.decode(token, secret_key, algorithms=[settings.jwt.algorithm])
        username: str = payload.get("sub")
        jti: str = payload.get("jti")
        if username is None:
            raise credentials_exception
        token_data = models.TokenData(username=username)
    except JWTError:
        # 这将捕获过期的令牌、无效的签名等
        raise credentials_exception

    # 验证会话是否有效（未撤销且未过期）
    if validate_session and jti:
        is_valid = await session_crud.validate_session(session, jti)
        if not is_valid:
            raise credentials_exception

    user = await crud.get_user_by_username(session, username=token_data.username)
    if user is None:
        raise credentials_exception

    return models.User.model_validate(user), jti


async def create_access_token(data: dict, session: AsyncSession, expires_delta: Optional[timedelta] = None) -> Tuple[str, str, int]:
    """
    创建JWT访问令牌

    :return: (token, jti, expire_minutes)
    """
    to_encode = data.copy()

    # 新增：添加标准声明以增强安全性和互操作性
    now = get_now() # 使用服务器本地时间的 naive datetime
    jti = str(uuid.uuid4())
    to_encode.update({
        "iat": now,  # Issued At: 令牌签发时间
        "jti": jti,  # JWT ID: 每个令牌的唯一标识符，可用于防止重放攻击
    })

    secret_key = await crud.get_config_value(session, 'jwtSecretKey', settings.jwt.secret_key) # type: ignore
    expire_minutes_str = await crud.get_config_value(session, 'jwtExpireMinutes', str(settings.jwt.access_token_expire_minutes)) # type: ignore
    expire_minutes = int(expire_minutes_str)
    # 如果有效期不为-1，则设置过期时间
    if expire_minutes != -1:
        expire = now + timedelta(minutes=expire_minutes)
        to_encode.update({"exp": expire})
    # 如果是-1，则不添加 "exp" 字段，令牌将永不过期
    encoded_jwt = jwt.encode(to_encode, secret_key, algorithm=settings.jwt.algorithm)
    return encoded_jwt, jti, expire_minutes


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_db_session)
) -> models.User:
    """
    依赖项：解码JWT，验证其有效性，并获取当前用户。
    """
    user, _ = await _get_user_from_token(token, session)
    return user


async def get_current_user_with_jti(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_db_session)
) -> Tuple[models.User, Optional[str]]:
    """
    依赖项：解码JWT，验证其有效性，并获取当前用户和 jti。
    用于需要知道当前会话 jti 的场景（如会话管理）。
    """
    return await _get_user_from_token(token, session)