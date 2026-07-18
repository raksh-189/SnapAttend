"""Shared API dependencies: current user, role guard."""

import uuid
from typing import Annotated

import jwt as pyjwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.user_repo import UserRepository

# auto_error=False so a missing header raises our envelope, not FastAPI's 403.
_bearer = HTTPBearer(auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise AuthenticationError("Not authenticated")
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = uuid.UUID(payload["sub"])
    except pyjwt.ExpiredSignatureError:
        raise AuthenticationError("Token expired") from None
    except (pyjwt.InvalidTokenError, KeyError, ValueError):
        raise AuthenticationError("Invalid token") from None

    user = await UserRepository(db).get(user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("Account is disabled")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(*roles: UserRole):
    """Dependency factory: `Depends(require_role(UserRole.ADMIN))`."""

    async def _check(user: CurrentUser) -> User:
        if user.role not in roles:
            raise PermissionDeniedError("Insufficient permissions")
        return user

    return _check


AdminUser = Annotated[User, Depends(require_role(UserRole.ADMIN))]
