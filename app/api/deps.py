from collections.abc import AsyncGenerator, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db.base import AsyncSessionLocal
from app.db.models import User, UserRole

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/auth/login",
    description="Log in with your email (in the `username` field) and password.",
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


DB = Annotated[AsyncSession, Depends(get_db)]

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated or token expired",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(db: DB, token: Annotated[str, Depends(oauth2_scheme)]) -> User:
    user_id = decode_access_token(token)
    if user_id is None:
        raise _UNAUTHORIZED
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise _UNAUTHORIZED
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole) -> Callable:
    allowed = {r.value for r in roles}

    async def checker(user: CurrentUser) -> User:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role: {' or '.join(sorted(allowed))}",
            )
        return user

    return checker


AdminUser = Annotated[User, Depends(require_roles(UserRole.admin))]
OperatorUser = Annotated[User, Depends(require_roles(UserRole.admin, UserRole.operator))]
