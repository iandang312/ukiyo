from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ukiyo_service.infrastructure.db.session import DEV_USER_ID, get_db
from ukiyo_service.infrastructure.db.models import User


__all__ = ["get_db", "get_current_user"]


async def get_current_user(db: AsyncSession = Depends(get_db)) -> User:
    user = await db.get(User, DEV_USER_ID)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="dev user not seeded; lifespan startup did not complete",
        )
    return user
