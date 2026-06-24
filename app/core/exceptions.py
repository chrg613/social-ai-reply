"""Custom exception hierarchy for SignalFlow API.

These map to structured HTTP responses via the global exception handler in main.py.
"""


class AppError(Exception):
    """Base exception for all application errors."""

    status_code: int = 500
    detail: str = "Internal server error"


class NotFoundError(AppError):
    status_code = 404
    detail = "Resource not found."


class ForbiddenError(AppError):
    status_code = 403
    detail = "You do not have access to this resource."


class ConflictError(AppError):
    status_code = 409
    detail = "Resource already exists."


class AuthenticationError(AppError):
    status_code = 401
    detail = "Authentication required."


class BusinessRuleError(AppError):
    """For state machine violations like invalid opportunity transitions."""

    status_code = 422
    detail = "Operation violates a business rule."


class RateLimitError(AppError):
    status_code = 429
    detail = "Too many requests."


class ValidationError(AppError):
    status_code = 422
    detail = "Validation error."


# Backwards-compatible alias for any external consumers
AppException = AppError
