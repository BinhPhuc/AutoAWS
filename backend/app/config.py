from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "dev"
    cors_origins: str = "http://localhost:5173"

    # Storage: sqlite (default, DB_PATH) | dynamodb (target storage, platform account)
    storage_backend: Literal["sqlite", "dynamodb"] = "sqlite"
    db_path: str = "./autoaws.db"
    dynamodb_table: str = "autoaws"
    dynamodb_region: str = ""
    # Dev only: LocalStack, e.g. http://localhost:4566 (independent of AWS_ENDPOINT_URL)
    dynamodb_endpoint_url: str = ""
    # Create the table on startup if it does not exist (dev / LocalStack)
    dynamodb_create_table: bool = True
    # Customer managed KMS key for table encryption; empty = AWS managed key
    dynamodb_kms_key_id: str = ""

    llm_provider: Literal["mock", "anthropic", "bedrock", "mcp"] = "mock"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5-5"
    # Claude on Bedrock (Mantle client): model ids carry the `anthropic.` prefix
    bedrock_model_id: str = "anthropic.claude-opus-5-5"
    bedrock_region: str = ""
    # Retry a refused request on this model (client-side middleware); empty = off
    bedrock_fallback_model: str = "anthropic.claude-opus-4-8"
    # Both Claude providers: thinking depth (low|medium|high|xhigh|max) and output cap
    llm_effort: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    llm_max_tokens: int = 16000
    # LLM_PROVIDER=mcp: how long one agent turn waits for an MCP client to answer
    mcp_bridge_timeout_seconds: int = 900

    platform_aws_account_id: str = ""
    platform_aws_profile: str = ""
    # Dev only: send every AWS call to an emulator such as LocalStack (http://localhost:4566)
    aws_endpoint_url: str = ""
    # Resolvers used by resolve_dns_public; point at LocalStack's DNS to test Route 53 records
    dns_resolvers: str = "8.8.8.8,1.1.1.1"

    # Limits of one diagnosis turn (docs/API_CONTRACT.md §3). When one is hit the model gets
    # one last round to submit what it confirmed.
    max_agent_iterations: int = 10
    max_agent_seconds: int = 240  # not applied to LLM_PROVIDER=mcp (a human-paced client)
    max_turn_tokens: int = 200_000  # input + output tokens, when the provider reports usage
    max_tool_calls: int = 40
    # Same tool + same input within this many seconds is served from the conversation cache
    tool_cache_ttl_seconds: int = 300
    # Time zone the agent uses to talk about times ("chiều nay", "09:14")
    user_timezone: str = "Asia/Ho_Chi_Minh"
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
