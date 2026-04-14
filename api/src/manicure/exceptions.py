from fastapi import HTTPException, status


class NotFoundError(HTTPException):
    def __init__(self, detail: str = "Resource not found") -> None:
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


class ConflictError(HTTPException):
    def __init__(self, detail: str = "Resource already exists") -> None:
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)


class UnsupportedProviderError(Exception):
    """Raised when no adapter matches the incoming request."""

    def __init__(self, detail: str = "No adapter matches the request") -> None:
        self.detail = detail
        super().__init__(detail)
