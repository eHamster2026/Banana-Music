import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from deps import get_db, get_current_user
from auth_utils import verify_password, get_password_hash, create_access_token
import models, schemas

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/register", response_model=schemas.Token)
def register(body: schemas.UserCreate, db: Session = Depends(get_db)):
    if db.query(models.User).filter(models.User.username == body.username).first():
        raise HTTPException(status_code=400, detail="用户名已存在")
    if db.query(models.User).filter(models.User.email == body.email).first():
        raise HTTPException(status_code=400, detail="邮箱已被注册")
    user = models.User(
        username=body.username,
        email=body.email,
        hashed_password=get_password_hash(body.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token({"sub": str(user.id)})
    return {"access_token": token, "token_type": "bearer", "user": user}


@router.post("/login", response_model=schemas.Token)
def login(body: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == body.username).first()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = create_access_token({"sub": str(user.id)})
    return {"access_token": token, "token_type": "bearer", "user": user}


@router.get("/me", response_model=schemas.UserOut)
def me(user: models.User = Depends(get_current_user)):
    return user


@router.post("/api-key/generate", response_model=schemas.ApiKeyOut)
def generate_api_key(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """为当前用户生成（或重新生成）API Key，用于 LLM / 自动化脚本等程序化访问。"""
    user.api_key = "am_" + secrets.token_hex(32)
    db.commit()
    return {"api_key": user.api_key}


@router.delete("/api-key/revoke", status_code=204)
def revoke_api_key(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """吊销当前用户的 API Key。"""
    user.api_key = None
    db.commit()
