"""Shared FastAPI dependencies: current user resolution and RBAC guards."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import AuthenticationError, PermissionDeniedError
from app.core.security import decode_token
from app.models.enums import UserRole
from app.models.user import User

# auto_error=False so a missing header flows through our own error envelope.
bearer_scheme = HTTPBearer(auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    db: DbSession,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ] = None,
) -> User:
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Authentication credentials were not provided.")

    try:
        payload = decode_token(credentials.credentials, "access")
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Access token has expired.") from exc
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid access token.") from exc

    try:
        user_id = uuid.UUID(str(payload.get("sub")))
    except (TypeError, ValueError) as exc:
        raise AuthenticationError("Invalid access token.") from exc

    user = db.get(User, user_id)
    if user is None:
        raise AuthenticationError("Account no longer exists.")
    if not user.is_active:
        raise PermissionDeniedError("This account has been deactivated.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole) -> Callable[[User], User]:
    """Dependency factory guarding a route to specific roles (PRD B.4.1)."""

    allowed = set(roles)

    def _guard(user: CurrentUser) -> User:
        if user.role not in allowed:
            raise PermissionDeniedError(
                "Your role does not have permission to perform this action."
            )
        return user

    return _guard


require_admin = require_roles(UserRole.ADMIN)
require_hr = require_roles(UserRole.ADMIN, UserRole.HR)

AdminUser = Annotated[User, Depends(require_admin)]
HrUser = Annotated[User, Depends(require_hr)]
