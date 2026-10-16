from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.core.security import create_access_token, hash_password, verify_password
from app.core.time import utcnow
from app.db.models import User
from app.schemas.auth import PasswordChange, TokenOut, UserOut
from app.services import audit

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/login",
    response_model=TokenOut,
    summary="Log in with email and password",
    responses={401: {"description": "Wrong email or password, or the account is deactivated."}},
)
async def login(db: DB, form: Annotated[OAuth2PasswordRequestForm, Depends()]) -> TokenOut:
    """Exchange email + password for a JWT access token.

    The body is `application/x-www-form-urlencoded` (OAuth2 password flow) so
    the **Authorize** button in this page works:

    - `username` — the user's **email**
    - `password`

    Send the returned `access_token` as `Authorization: Bearer <token>` on
    every other request, and as `?token=` when opening the `/ws` WebSocket.
    """
    email = form.username.strip().lower()
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(form.password, user.password_hash):
        if user is not None:
            audit.record(db, "auth.login_failed", user_id=user.id, entity_type="user", entity_id=str(user.id))
            await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password",
                            headers={"WWW-Authenticate": "Bearer"})
    user.last_login_at = utcnow()
    audit.record(db, "auth.login", user_id=user.id, entity_type="user", entity_id=str(user.id))
    await db.commit()
    token, expires_in = create_access_token(user.id, user.role)
    return TokenOut(access_token=token, expires_in=expires_in, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut, summary="Current user")
async def me(user: CurrentUser) -> User:
    """The account the bearer token belongs to."""
    return user


@router.post(
    "/me/password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Change own password",
    responses={400: {"description": "Current password is wrong."}},
)
async def change_password(body: PasswordChange, user: CurrentUser, db: DB) -> None:
    """Change your own password. Existing tokens stay valid until they expire."""
    db_user = await db.get(User, user.id)
    if not verify_password(body.current_password, db_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    db_user.password_hash = hash_password(body.new_password)
    audit.record(db, "user.password_changed", user_id=user.id, entity_type="user", entity_id=str(user.id))
    await db.commit()
