from typing import Optional
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from database import SessionLocal
from auth_utils import decode_token
import models

bearer = HTTPBearer(auto_error=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _user_from_credentials(
    credentials: Optional[HTTPAuthorizationCredentials],
    x_api_key: Optional[str],
    db: Session,
) -> Optional[models.User]:
    """Bearer JWT 优先，fallback 到 X-API-Key。返回 None 表示未认证。"""
    if credentials:
        payload = decode_token(credentials.credentials)
        if payload:
            try:
                user_id = int(payload.get("sub"))
            except (TypeError, ValueError):
                return None
            return db.query(models.User).filter(models.User.id == user_id).first()

    if x_api_key:
        return db.query(models.User).filter(models.User.api_key == x_api_key).first()

    return None


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
    db: Session = Depends(get_db),
) -> models.User:
    user = _user_from_credentials(credentials, x_api_key, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    return user


def get_admin_user(user: models.User = Depends(get_current_user)) -> models.User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user


def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
    db: Session = Depends(get_db),
) -> Optional[models.User]:
    return _user_from_credentials(credentials, x_api_key, db)
