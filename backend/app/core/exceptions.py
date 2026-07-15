"""Domain exceptions and their translation to HTTP responses.

Services raise these; routers never construct HTTPException themselves.
The global handlers registered in `main.py` produce a consistent error
envelope: {"detail": str, "code": str}.
"""

from fastapi import Request, status
from fastapi.responses import JSONResponse


class DomainError(Exception):
    """Base for all domain errors."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "domain_error"

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class NotFoundError(DomainError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class ConflictError(DomainError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class AuthenticationError(DomainError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "authentication_failed"


class PermissionDeniedError(DomainError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "permission_denied"


class ValidationFailedError(DomainError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "validation_failed"


class InvalidStateError(DomainError):
    """Raised on illegal attendance-session state transitions."""

    status_code = status.HTTP_409_CONFLICT
    code = "invalid_state"


async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": exc.code},
    )
