"""
TOTP (Time-Based One-Time Password) 工具模块

基于 pyotp 库实现 RFC 6238 TOTP 两步验证功能。
"""

import logging

import pyotp

logger = logging.getLogger(__name__)

# 应用名称，显示在验证器 App 中
APP_ISSUER = "Misaka弹幕库"


def generate_secret() -> str:
    """
    生成一个随机的 TOTP 密钥 (base32 编码)。

    :return: base32 编码的密钥字符串
    """
    return pyotp.random_base32()


def get_totp_uri(secret: str, username: str, issuer: str = APP_ISSUER) -> str:
    """
    生成 otpauth:// URI，用于生成二维码供验证器 App 扫描。

    :param secret: base32 编码的密钥
    :param username: 用户名（显示在验证器中）
    :param issuer: 应用名称
    :return: otpauth:// URI
    """
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=username, issuer_name=issuer)


def verify_otp(secret: str, code: str, valid_window: int = 1) -> bool:
    """
    验证用户提交的 TOTP 验证码。

    :param secret: base32 编码的密钥
    :param code: 用户提交的 6 位验证码
    :param valid_window: 允许的时间窗口偏差（默认 ±1 个周期，即前后各 30 秒）
    :return: 验证码是否正确
    """
    try:
        totp = pyotp.TOTP(secret)
        return totp.verify(code, valid_window=valid_window)
    except Exception as e:
        logger.warning(f"TOTP 验证异常: {e}")
        return False
