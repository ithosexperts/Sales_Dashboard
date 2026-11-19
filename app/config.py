"""
Central application configuration for Sales Dashboard.

Reads values from environment variables or .env file.
Enterprise analytics application configuration.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Sales Dashboard"
    environment: str = "development"
    port: int = 8000
    public_base_url: str = "http://127.0.0.1:8000"

    # Company API Integration
    # REST-style database gateway: https://api.hosexperts.com:85/apiv2.php
    api_base_url: str = "https://api.hosexperts.com:85/apiv2.php"
    api_auth_token: str = ""
    api_username: str = ""
    api_password: str = ""
    api_database: str = "OperationsDB"
    api_timeout: float = 90.0

    # Application Security & Logging
    secret_key: str = "change-me-in-production-sales-dashboard-secret-key-32-chars"
    log_level: str = "INFO"

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod", "live"}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
