"""
MFA (多因素认证) 管理 API

包含 TOTP 两步验证和 WebAuthn PassKey 的设置、验证、管理接口。
"""

import json
import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession

from webauthn import (
    generate_registration_options,
    verify_registration_response,
    generate_authentication_options,
    verify_authentication_response,
    options_to_json,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    ResidentKeyRequirement,
    UserVerificationRequirement,
    PublicKeyCredentialDescriptor,
)
from webauthn.helpers import bytes_to_base64url, base64url_to_bytes

from src.db import models, crud, get_db_session
from src.db.crud import passkey as passkey_crud
from src import security
from src.utils.otp import generate_secret, get_totp_uri, verify_otp

logger = logging.getLogger(__name__)
router = APIRouter()

# ======== WebAuthn 配置 ========
# 通过配置或环境变量获取，这里使用合理的默认值
RP_ID = "localhost"  # 会在运行时从请求中动态推断
RP_NAME = "Misaka弹幕库"

# ======== Challenge 临时存储 ========
# key: username, value: (challenge_bytes, timestamp)
_challenge_store: dict[str, tuple[bytes, float]] = {}
CHALLENGE_TTL = 300  # 5分钟过期


def _store_challenge(username: str, challenge: bytes):
    """存储 challenge 并自动清理过期条目"""
    now = time.time()
    # 清理过期的 challenge
    expired_keys = [k for k, (_, t) in _challenge_store.items() if now - t > CHALLENGE_TTL]
    for k in expired_keys:
        del _challenge_store[k]
    _challenge_store[username] = (challenge, now)


def _get_and_consume_challenge(username: str) -> Optional[bytes]:
    """获取并消费 challenge"""
    if username not in _challenge_store:
        return None
    challenge, ts = _challenge_store.pop(username)
    if time.time() - ts > CHALLENGE_TTL:
        return None
    return challenge


def _get_rp_id(request: Request) -> str:
    """从请求中动态推断 RP ID（域名，不含端口）"""
    host = request.headers.get("host", "localhost")
    # 移除端口号
    return host.split(":")[0]



# ======== MFA 状态查询 ========

@router.get("/status", response_model=models.MfaStatusResponse, summary="获取当前用户的 MFA 状态")
async def get_mfa_status(
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """获取当前用户的 MFA 配置状态（TOTP 是否开启、PassKey 列表）"""
    user = await crud.get_user_by_username(session, current_user.username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    passkeys = await passkey_crud.get_passkeys_by_user_id(session, user["id"])
    return {
        "totpEnabled": user.get("isOtp", False),
        "passkeyCount": len(passkeys),
        "passkeys": passkeys,
    }


# ======== TOTP 两步验证 ========

@router.post("/totp/setup", response_model=models.TotpSetupResponse, summary="生成 TOTP 密钥")
async def setup_totp(
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    生成 TOTP 密钥和二维码 URI。
    用户需要用验证器 App 扫描二维码，然后调用 verify-setup 确认。
    """
    user = await crud.get_user_by_username(session, current_user.username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.get("isOtp"):
        raise HTTPException(status_code=400, detail="TOTP 已启用，请先关闭后再重新设置")

    secret = generate_secret()
    uri = get_totp_uri(secret, current_user.username)

    # 临时存储 secret，等待用户确认验证码
    _store_challenge(f"totp_setup_{current_user.username}", secret.encode())

    return {"secret": secret, "uri": uri}


@router.post("/totp/verify-setup", status_code=status.HTTP_200_OK, summary="确认 TOTP 设置")
async def verify_totp_setup(
    data: models.TotpVerifyRequest,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """用户扫码后输入验证码，确认 TOTP 设置"""
    secret_bytes = _get_and_consume_challenge(f"totp_setup_{current_user.username}")
    if not secret_bytes:
        raise HTTPException(status_code=400, detail="TOTP 设置已过期，请重新生成")

    secret = secret_bytes.decode()
    if not verify_otp(secret, data.code):
        # 验证失败，重新存回 challenge 让用户重试
        _store_challenge(f"totp_setup_{current_user.username}", secret_bytes)
        raise HTTPException(status_code=400, detail="验证码错误，请重试")

    # 验证成功，保存到数据库
    await crud.enable_user_otp(session, current_user.username, secret)
    return {"message": "TOTP 两步验证已启用"}


@router.post("/totp/disable", status_code=status.HTTP_200_OK, summary="关闭 TOTP 两步验证")
async def disable_totp(
    data: models.TotpDisableRequest,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """关闭 TOTP 两步验证（需要输入当前密码确认）"""
    user = await crud.get_user_by_username(session, current_user.username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.get("isOtp"):
        raise HTTPException(status_code=400, detail="TOTP 未启用")

    # 验证密码
    if not security.verify_password(data.password, user["hashedPassword"]):
        raise HTTPException(status_code=400, detail="密码错误")

    await crud.disable_user_otp(session, current_user.username)
    return {"message": "TOTP 两步验证已关闭"}


# ======== WebAuthn PassKey ========

@router.post("/passkey/register/options", summary="生成 PassKey 注册选项")
async def passkey_register_options(
    request: Request,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    生成 WebAuthn 注册选项，前端调用 navigator.credentials.create() 时使用。
    前提条件：用户必须先启用 TOTP 两步验证，才能注册 PassKey。
    """
    user = await crud.get_user_by_username(session, current_user.username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # 必须先启用 TOTP 才能注册 PassKey（防止用户失联）
    if not user.get("isOtp"):
        raise HTTPException(status_code=400, detail="请先启用 TOTP 两步验证后再注册 PassKey")

    rp_id = _get_rp_id(request)

    # 获取用户已有的凭证，用于排除重复注册
    existing_passkeys = await passkey_crud.get_passkeys_by_user_id(session, user["id"])
    exclude_credentials = [
        PublicKeyCredentialDescriptor(
            id=base64url_to_bytes(pk["credentialId"]),
            transports=pk["transports"].split(",") if pk.get("transports") else [],
        )
        for pk in existing_passkeys
    ]

    options = generate_registration_options(
        rp_id=rp_id,
        rp_name=RP_NAME,
        user_id=str(user["id"]).encode("utf-8"),
        user_name=user["username"],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        exclude_credentials=exclude_credentials,
    )

    # 存储 challenge 供验证时使用
    _store_challenge(f"passkey_reg_{current_user.username}", options.challenge)

    return {"options": options_to_json(options)}


@router.post("/passkey/register/verify", summary="验证 PassKey 注册")
async def passkey_register_verify(
    data: models.PassKeyRegisterRequest,
    request: Request,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """验证浏览器返回的 WebAuthn 注册凭证并保存"""
    user = await crud.get_user_by_username(session, current_user.username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    challenge = _get_and_consume_challenge(f"passkey_reg_{current_user.username}")
    if not challenge:
        raise HTTPException(status_code=400, detail="注册已过期，请重新开始")

    rp_id = _get_rp_id(request)
    origin = f"{request.url.scheme}://{request.headers.get('host', 'localhost')}"

    try:
        verification = verify_registration_response(
            credential=data.credential,
            expected_challenge=challenge,
            expected_rp_id=rp_id,
            expected_origin=origin,
        )
    except Exception as e:
        logger.warning(f"PassKey 注册验证失败: {e}")
        raise HTTPException(status_code=400, detail=f"PassKey 注册验证失败: {str(e)}")

    # 存储凭证
    credential_id_b64 = bytes_to_base64url(verification.credential_id)
    public_key_b64 = bytes_to_base64url(verification.credential_public_key)

    # 获取传输方式（如果有）
    transports_str = None
    if hasattr(verification, 'credential_device_type'):
        # py_webauthn v2.x
        pass

    passkey_id = await passkey_crud.create_passkey(
        session=session,
        user_id=user["id"],
        credential_id=credential_id_b64,
        public_key=public_key_b64,
        sign_count=verification.sign_count,
        device_name=data.deviceName or "未命名设备",
        transports=transports_str,
    )

    return {"message": "PassKey 注册成功", "id": passkey_id}


@router.post("/passkey/authenticate/options", summary="生成 PassKey 认证选项")
async def passkey_authenticate_options(
    request: Request,
    username: str = "",
    session: AsyncSession = Depends(get_db_session),
):
    """
    生成 WebAuthn 认证选项，前端调用 navigator.credentials.get() 时使用。
    注意：此接口不需要认证（用于登录流程中的 MFA 验证）。
    """
    rp_id = _get_rp_id(request)
    allow_credentials = []

    if username:
        user = await crud.get_user_by_username(session, username)
        if user:
            existing_passkeys = await passkey_crud.get_passkeys_by_user_id(session, user["id"])
            allow_credentials = [
                PublicKeyCredentialDescriptor(
                    id=base64url_to_bytes(pk["credentialId"]),
                    transports=pk["transports"].split(",") if pk.get("transports") else [],
                )
                for pk in existing_passkeys
            ]

    options = generate_authentication_options(
        rp_id=rp_id,
        allow_credentials=allow_credentials if allow_credentials else None,
        user_verification=UserVerificationRequirement.PREFERRED,
    )

    # 存储 challenge
    challenge_key = f"passkey_auth_{username}" if username else f"passkey_auth__anon"
    _store_challenge(challenge_key, options.challenge)

    return {"options": options_to_json(options)}


@router.post("/passkey/authenticate/verify", summary="验证 PassKey 认证")
async def passkey_authenticate_verify(
    data: models.PassKeyAuthenticateRequest,
    request: Request,
    username: str = "",
    session: AsyncSession = Depends(get_db_session),
):
    """
    验证 WebAuthn 认证断言。
    注意：此接口不需要认证（用于登录流程中的 MFA 验证）。
    返回验证是否成功。
    """
    challenge_key = f"passkey_auth_{username}" if username else "passkey_auth__anon"
    challenge = _get_and_consume_challenge(challenge_key)
    if not challenge:
        raise HTTPException(status_code=400, detail="认证已过期，请重新开始")

    rp_id = _get_rp_id(request)
    origin = f"{request.url.scheme}://{request.headers.get('host', 'localhost')}"

    # 解析凭证以获取 credential_id，查找对应的 passkey
    try:
        cred_data = json.loads(data.credential)
        raw_id = cred_data.get("rawId") or cred_data.get("id", "")
    except (json.JSONDecodeError, AttributeError):
        raise HTTPException(status_code=400, detail="无效的凭证数据")

    passkey_record = await passkey_crud.get_passkey_by_credential_id(session, raw_id)
    if not passkey_record:
        raise HTTPException(status_code=400, detail="未找到对应的 PassKey")

    try:
        verification = verify_authentication_response(
            credential=data.credential,
            expected_challenge=challenge,
            expected_rp_id=rp_id,
            expected_origin=origin,
            credential_public_key=base64url_to_bytes(passkey_record["publicKey"]),
            credential_current_sign_count=passkey_record["signCount"],
        )
    except Exception as e:
        logger.warning(f"PassKey 认证验证失败: {e}")
        raise HTTPException(status_code=400, detail=f"PassKey 认证验证失败: {str(e)}")

    # 更新签名计数器
    await passkey_crud.update_passkey_sign_count(session, raw_id, verification.new_sign_count)

    return {"verified": True, "userId": passkey_record["userId"]}


# ======== PassKey 管理 ========

@router.put("/passkey/{passkey_id}/rename", summary="重命名 PassKey")
async def rename_passkey(
    passkey_id: int,
    data: models.PassKeyRenameRequest,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """重命名指定的 PassKey"""
    user = await crud.get_user_by_username(session, current_user.username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    success = await passkey_crud.rename_passkey(session, passkey_id, user["id"], data.deviceName)
    if not success:
        raise HTTPException(status_code=404, detail="PassKey not found")
    return {"message": "重命名成功"}


@router.delete("/passkey/{passkey_id}", status_code=status.HTTP_200_OK, summary="删除 PassKey")
async def delete_passkey(
    passkey_id: int,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """删除指定的 PassKey"""
    user = await crud.get_user_by_username(session, current_user.username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    success = await passkey_crud.delete_passkey(session, passkey_id, user["id"])
    if not success:
        raise HTTPException(status_code=404, detail="PassKey not found")
    return {"message": "PassKey 已删除"}