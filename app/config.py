"""Configuration settings for the Forager x HubSpot integration."""

import os
from functools import lru_cache
from typing import List, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Forager credentials and endpoints
    FORAGER_API_KEY: str = Field(default="", description="Forager API Key")
    FORAGER_BASE_URL: str = Field(
        default="https://api-v2.forager.ai",
        description="Forager API base URL",
    )
    FORAGER_ACCOUNT_ID: Optional[int] = Field(
        default=None,
        description="Numeric Forager Account ID from the Forager app's My Account page",
    )

    # HubSpot credentials and endpoints
    HUBSPOT_ACCESS_TOKEN: str = Field(
        default="",
        description="HubSpot Private App Access Token (Bearer)",
    )
    HUBSPOT_CLIENT_SECRET: str = Field(
        default="",
        description="HubSpot Client Secret for Webhook Signature Verification",
    )
    HUBSPOT_BASE_URL: str = Field(
        default="https://api.hubapi.com",
        description="HubSpot API base URL",
    )

    # Contact discovery and job-title filtering
    ALLOWED_JOB_TITLES: str = Field(
        default="Software Engineer,Founding Engineer,Staff Engineer,Principal Engineer,VP of Engineering,CTO,Head of Engineering,Product Manager",
        description="Comma-separated allowed job titles or title patterns",
    )
    MAX_CONTACTS_PER_COMPANY: int = Field(
        default=5,
        description="Max contacts to discover and associate per company",
    )

    # Service & runtime configuration
    APP_ENV: str = Field(default="development", description="Environment (development/production/test)")
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")
    PORT: int = Field(default=8000, description="Server listen port")
    REQUEST_TIMEOUT_SECONDS: float = Field(default=30.0, description="HTTP client timeout in seconds")
    MAX_RETRIES: int = Field(default=3, description="Bounded retries for transient provider failures")

    @property
    def allowed_job_titles_list(self) -> List[str]:
        """Return the allowed job titles as a cleaned list."""
        if not self.ALLOWED_JOB_TITLES:
            return []
        return [t.strip() for t in self.ALLOWED_JOB_TITLES.split(",") if t.strip()]

    @property
    def is_production(self) -> bool:
        """Check if environment is production."""
        return self.APP_ENV.lower() == "production"


@lru_cache()
def get_settings() -> Settings:
    """Get cached application settings."""
    return Settings()
