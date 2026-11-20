from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import InviteCode, User
from ..schemas import LoginRequest, RegisterRequest, TokenResponse, UserOut
from ..security import create_access_token, get_current_user, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="Email already registered")

    code = payload.invite_code.strip().upper()
    if settings.invite_only:
        if not code:
            raise HTTPException(status_code=403, detail="Invite code required")
        invite = db.get(InviteCode, code)
        if invite is None or invite.used_by is not None:
            raise HTTPException(status_code=403, detail="Invite code invalid or already used")

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name or email.split("@")[0],
    )
    db.add(user)
    db.flush()

    if settings.invite_only:
        # атомарно "сжигаем" инвайт: две одновременные регистрации одним кодом не пройдут
        claimed = db.execute(
            update(InviteCode)
            .where(InviteCode.code == code, InviteCode.used_by.is_(None))
            .values(used_by=user.id, used_at=datetime.now(timezone.utc))
        )
        if claimed.rowcount == 0:
            db.rollback()
            raise HTTPException(status_code=403, detail="Invite code already used")

    db.commit()
    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return TokenResponse(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user
