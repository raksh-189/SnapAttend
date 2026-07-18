"""Authentication service: login, refresh rotation, revocation.

Refresh-token model: opaque secrets, SHA-256 hashed at rest, single-use.
On refresh the presented token is revoked and a new one issued (rotation).
Presenting an already-revoked token is treated as theft — every live token
for that user is revoked (reuse detection).
"""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.exceptions import AuthenticationError
from app.core.logging import get_logger
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.user_repo import RefreshTokenRepository, UserRepository

logger = get_logger(__name__)


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.tokens = RefreshTokenRepository(session)

    async def login(self, email: str, password: str) -> tuple[str, str]:
        """Returns (access_token, refresh_token). Uniform error on any failure
        so responses don't reveal whether the email exists."""
        user = await self.users.get_by_email(email)
        if user is None or not security.verify_password(password, user.hashed_password):
            raise AuthenticationError("Incorrect email or password")
        if not user.is_active:
            raise AuthenticationError("Account is disabled")

        pair = self._issue_tokens(user)
        await self.session.commit()
        logger.info("login", user_id=str(user.id))
        return pair

    async def refresh(self, refresh_token: str) -> tuple[str, str]:
        """Rotate: revoke the presented token, issue a new pair."""
        token_hash = security.hash_refresh_token(refresh_token)
        stored = await self.tokens.get_by_hash(token_hash)
        if stored is None:
            raise AuthenticationError("Invalid refresh token")

        if stored.revoked_at is not None:
            # Reuse of a rotated token — assume theft, kill the whole family.
            await self.tokens.revoke_all_for_user(stored.user_id)
            await self.session.commit()
            logger.warning("refresh_token_reuse_detected", user_id=str(stored.user_id))
            raise AuthenticationError("Invalid refresh token")

        if stored.expires_at <= datetime.now(UTC):
            raise AuthenticationError("Refresh token expired")

        user = await self.users.get(stored.user_id)
        if user is None or not user.is_active:
            raise AuthenticationError("Account is disabled")

        await self.tokens.revoke(stored)
        pair = self._issue_tokens(user)
        await self.session.commit()
        return pair

    async def logout(self, refresh_token: str, *, everywhere: bool = False) -> None:
        """Revoke the presented refresh token (or all of the user's tokens).
        Idempotent: unknown tokens are ignored."""
        stored = await self.tokens.get_by_hash(security.hash_refresh_token(refresh_token))
        if stored is None:
            return
        if everywhere:
            await self.tokens.revoke_all_for_user(stored.user_id)
        else:
            await self.tokens.revoke(stored)
        await self.session.commit()

    async def create_user(
        self,
        *,
        email: str,
        password: str,
        full_name: str,
        role: UserRole,
        is_active: bool = True,
    ) -> User:
        """Used by the admin bootstrap CLI and (later) admin user management."""
        user = User(
            email=email.lower(),
            hashed_password=security.hash_password(password),
            full_name=full_name,
            role=role,
            is_active=is_active,
        )
        self.users.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    def _issue_tokens(self, user: User) -> tuple[str, str]:
        access = security.create_access_token(user.id, user.role.value)
        refresh = security.generate_refresh_token()
        self.tokens.create(
            user_id=user.id,
            token_hash=security.hash_refresh_token(refresh),
            expires_at=security.refresh_token_expiry(),
        )
        return access, refresh
