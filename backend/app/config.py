from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "dev"
    db_path: str = "./autoaws.db"
    cors_origins: str = "http://localhost:5173"

    llm_provider: Literal["mock", "anthropic", "bedrock"] = "mock"
    anthropic_api_key: str = ""
    anthropic_model: str = ""
    bedrock_model_id: str = ""
    bedrock_region: str = ""

    platform_aws_account_id: str = ""
    platform_aws_profile: str = ""

    max_agent_iterations: int = 8
    assume_role_duration_seconds: int = 900

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
