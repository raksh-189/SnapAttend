"""Create the first admin user (idempotent).

Usage:
    python -m app.cli.create_admin --email admin@example.com --full-name "Admin" \
        [--password <pw>]          # omit to be prompted
"""

import argparse
import asyncio
import getpass
import sys

from pydantic import EmailStr, TypeAdapter, ValidationError

from app.db.session import async_session_factory, engine
from app.models.enums import UserRole
from app.repositories.user_repo import UserRepository
from app.services.auth_service import AuthService


async def _run(email: str, full_name: str, password: str) -> int:
    async with async_session_factory() as session:
        existing = await UserRepository(session).get_by_email(email)
        if existing is not None:
            print(f"User {email} already exists — nothing to do.")
            return 0
        user = await AuthService(session).create_user(
            email=email, password=password, full_name=full_name, role=UserRole.ADMIN
        )
        print(f"Created admin {user.email} ({user.id})")
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the first admin user")
    parser.add_argument("--email", required=True)
    parser.add_argument("--full-name", required=True)
    parser.add_argument("--password")
    args = parser.parse_args()

    # Same validation the login endpoint applies — otherwise the created
    # admin could never log in.
    try:
        TypeAdapter(EmailStr).validate_python(args.email)
    except ValidationError as exc:
        print(f"Invalid email: {exc.errors()[0]['msg']}", file=sys.stderr)
        raise SystemExit(2) from None

    password = args.password or getpass.getpass("Admin password: ")
    if len(password) < 8:
        print("Password must be at least 8 characters.", file=sys.stderr)
        raise SystemExit(2)

    async def _wrapped() -> int:
        try:
            return await _run(args.email, args.full_name, password)
        finally:
            await engine.dispose()

    raise SystemExit(asyncio.run(_wrapped()))


if __name__ == "__main__":
    main()
