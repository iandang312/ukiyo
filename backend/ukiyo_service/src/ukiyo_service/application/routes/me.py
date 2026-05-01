"""Current-user endpoint.

Next development phase will swap `get_current_user` to a real auth dependency underneath this route;
the response shape is intentionally minimal so it stays stable across that
swap.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from ukiyo_service.application.deps import get_current_user
from ukiyo_service.infrastructure.db.models import User


router = APIRouter(tags=["me"])


class MeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str


@router.get("/me", response_model=MeOut)
async def get_me(user: User = Depends(get_current_user)) -> User:
    return user
