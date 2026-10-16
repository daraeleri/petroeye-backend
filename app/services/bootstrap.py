"""Startup seeding: create the first admin account from env vars."""
import logging

from sqlalchemy import func, select

from app.config import settings
from app.core.security import hash_password
from app.db.base import AsyncSessionLocal
from app.db.models import User, UserRole
from app.services import audit

logger = logging.getLogger("petrotwin.bootstrap")


async def ensure_admin() -> None:
    """Create ADMIN_EMAIL / ADMIN_PASSWORD as admin if there are no users yet."""
    async with AsyncSessionLocal() as session:
        count = await session.scalar(select(func.count()).select_from(User))
        if count:
            return
        if not settings.admin_email or not settings.admin_password:
            logger.warning(
                "No users exist and ADMIN_EMAIL/ADMIN_PASSWORD are not set — nobody can log in. "
                "Set them and restart to create the first admin."
            )
            return
        user = User(
            email=settings.admin_email.strip().lower(),
            full_name="Administrator",
            password_hash=hash_password(settings.admin_password),
            role=UserRole.admin.value,
            is_active=True,
        )
        session.add(user)
        await session.flush()
        audit.record(session, "user.bootstrap_admin", entity_type="user", entity_id=str(user.id),
                     details={"email": user.email})
        await session.commit()
        logger.info("Created first admin user %s", user.email)
