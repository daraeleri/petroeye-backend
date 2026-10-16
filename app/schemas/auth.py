import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.db.models import UserRole

PASSWORD_MIN = 8


class TokenOut(BaseModel):
    access_token: str = Field(description="JWT to send as `Authorization: Bearer <token>`.")
    token_type: str = Field(default="bearer", examples=["bearer"])
    expires_in: int = Field(description="Seconds until the token expires.", examples=[43200])
    user: "UserOut"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str = Field(examples=["ops@petroeye.example"])
    full_name: str = Field(examples=["Amina Ngono"])
    role: UserRole = Field(description="`admin`, `operator` or `viewer`.")
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


class UserCreate(BaseModel):
    email: EmailStr = Field(examples=["driver.lead@petroeye.example"])
    full_name: str = Field(min_length=1, max_length=120, examples=["Paul Mbarga"])
    password: str = Field(min_length=PASSWORD_MIN, max_length=128, description=f"At least {PASSWORD_MIN} characters.")
    role: UserRole = Field(default=UserRole.viewer)


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    role: UserRole | None = None
    is_active: bool | None = Field(default=None, description="Set false to block login (users are never deleted).")
    password: str | None = Field(
        default=None, min_length=PASSWORD_MIN, max_length=128, description="Admin password reset."
    )


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=PASSWORD_MIN, max_length=128)


TokenOut.model_rebuild()
