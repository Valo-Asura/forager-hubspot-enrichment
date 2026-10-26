"""Application domain exceptions."""

from typing import Any, Dict, Optional


class AppException(Exception):
    """Base exception for application errors."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ProviderAPIError(AppException):
    """Exception raised when an external provider API call fails."""

    def __init__(
        self,
        message: str,
        provider: str,
        status_code: Optional[int] = None,
        response_body: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message, details)
        self.provider = provider
        self.status_code = status_code
        self.response_body = response_body


class ForagerAPIError(ProviderAPIError):
    """Raised on Forager API failure."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response_body: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            provider="Forager",
            status_code=status_code,
            response_body=response_body,
            details=details,
        )


class HubSpotAPIError(ProviderAPIError):
    """Raised on HubSpot API failure."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response_body: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            provider="HubSpot",
            status_code=status_code,
            response_body=response_body,
            details=details,
        )


class WebhookSignatureVerificationError(AppException):
    """Raised when webhook signature verification fails."""
    pass


class RecordNotFoundError(AppException):
    """Raised when a requested record is not found in HubSpot or Forager."""
    pass


class ConfigurationError(AppException):
    """Raised on invalid or missing required configuration."""
    pass
