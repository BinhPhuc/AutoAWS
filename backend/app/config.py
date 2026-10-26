from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "dev"
    db_path: str = "./autoaws.db"
    cors_origins: str = "http://localhost:5173"

    llm_provider: Literal["mock", "anthropic", "bedrock", "mcp"] = "mock"
    anthropic_api_key: str = ""
    anthropic_model: str = ""
    bedrock_model_id: str = ""
    bedrock_region: str = ""
    # LLM_PROVIDER=mcp: how long one agent turn waits for an MCP client to answer
    mcp_bridge_timeout_seconds: int = 900

    platform_aws_account_id: str = ""
    platform_aws_profile: str = ""
    # Dev only: send every AWS call to an emulator such as LocalStack (http://localhost:4566)
    aws_endpoint_url: str = ""
    # Resolvers used by resolve_dns_public; point at LocalStack's DNS to test Route 53 records
    dns_resolvers: str = "8.8.8.8,1.1.1.1"

    max_agent_iterations: int = 8
    assume_role_duration_seconds: int = 900

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def dns_resolver_list(self) -> list[str]:
        return [r.strip() for r in self.dns_resolvers.split(",") if r.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
