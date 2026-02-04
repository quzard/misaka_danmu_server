"""
Auth_extra相关的API端点 - 用户认证和密码管理
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from src import security
from src.db import crud, models, get_db_session

logger = logging.getLogger(__name__)

auth_router = APIRouter()

@auth_router.post("/token", response_model=models.Token, summary="用户登录获取令牌")
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_db_session)
):
    user = await crud.get_user_by_username(session, form_data.username)
    if not user or not security.verify_password(form_data.password, user["hashedPassword"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = await security.create_access_token(
        data={"sub": user["username"]}, session=session
    )
    # 更新用户的登录信息
    await crud.update_user_login_info(session, user["username"], access_token)

    return {"accessToken": access_token, "tokenType": "bearer"}




@auth_router.get("/users/me", response_model=models.User, summary="获取当前用户信息")
async def read_users_me(current_user: models.User = Depends(security.get_current_user)):
    return current_user



@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="用户登出")
async def logout():
    """
    用户登出。前端应清除本地存储的token。
    """
    return



@auth_router.put("/users/me/password", status_code=status.HTTP_204_NO_CONTENT, summary="修改当前用户密码")
async def change_current_user_password(
    password_data: models.PasswordChange,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session)
):
    # 1. 从数据库获取完整的用户信息，包括哈希密码
    user_in_db = await crud.get_user_by_username(session, current_user.username)
    if not user_in_db:
        # 理论上不会发生，因为 get_current_user 已经验证过
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # 2. 验证旧密码是否正确
    if not security.verify_password(password_data.oldPassword, user_in_db["hashedPassword"]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect old password")

    # 3. 更新密码
    new_hashed_password = security.get_password_hash(password_data.newPassword)
    await crud.update_user_password(session, current_user.username, new_hashed_password)

# --- Rate Limiter API ---



