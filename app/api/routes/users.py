import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import DB, AdminUser
from app.core.security import hash_password
from app.db.models import User
from app.schemas.auth import UserCreate, UserOut, UserUpdate
from app.services import audit

router = APIRouter(prefix="/users", tags=["Users"])

_NOT_FOUND = {404: {"description": "User not found."}}


@router.get("", response_model=list[UserOut], summary="List users (admin)")
async def list_users(db: DB, _: AdminUser) -> list[User]:
    """All dashboard accounts, active and deactivated."""
    return list((await db.execute(select(User).order_by(User.created_at))).scalars())


@router.post(
    "",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a user (admin)",
    responses={409: {"description": "Email already registered."}},
)
async def create_user(body: UserCreate, db: DB, admin: AdminUser) -> User:
    """Create a dashboard account. There is no public sign-up: only admins add users.

    Roles: `admin` (everything), `operator` (geofences + acknowledging alerts),
    `viewer` (read-only + report export).
    """
    email = body.email.strip().lower()
    if (await db.execute(select(User.id).where(User.email == email))).first():
        raise HTTPException(status_code=409, detail="A user with this email already exists")
    user = User(email=email, full_name=body.full_name, password_hash=hash_password(body.password),
                role=body.role.value, is_active=True)
    db.add(user)
    await db.flush()
    audit.record(db, "user.create", user_id=admin.id, entity_type="user", entity_id=str(user.id),
                 details={"email": email, "role": body.role.value})
    await db.commit()
    await db.refresh(user)
    return user


@router.get("/{user_id}", response_model=UserOut, summary="Get a user (admin)", responses=_NOT_FOUND)
async def get_user(user_id: uuid.UUID, db: DB, _: AdminUser) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.patch(
    "/{user_id}",
    response_model=UserOut,
    summary="Update a user (admin)",
    responses={**_NOT_FOUND, 400: {"description": "Admins can't demote or deactivate themselves."}},
)
async def update_user(user_id: uuid.UUID, body: UserUpdate, db: DB, admin: AdminUser) -> User:
    """Change name or role, deactivate/reactivate (`is_active`), or reset the password.

    Users are never deleted, so the activity log keeps pointing at them.
    """
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id and (body.is_active is False or (body.role and body.role.value != "admin")):
        raise HTTPException(status_code=400, detail="You can't demote or deactivate your own account")

    changes: dict = {}
    if body.full_name is not None:
        user.full_name = changes["full_name"] = body.full_name
    if body.role is not None:
        user.role = changes["role"] = body.role.value
    if body.is_active is not None:
        user.is_active = changes["is_active"] = body.is_active
    if body.password is not None:
        user.password_hash = hash_password(body.password)
        changes["password"] = "reset"
    audit.record(db, "user.update", user_id=admin.id, entity_type="user", entity_id=str(user.id), details=changes)
    await db.commit()
    await db.refresh(user)
    return user
