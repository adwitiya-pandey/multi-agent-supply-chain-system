"""Application configuration settings using pydantic-settings."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment or .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM Settings
    llm_mode: Literal["scripted", "gemini"] = Field(default="scripted", alias="LLM_MODE")
    gemini_api_key: SecretStr = Field(default=SecretStr(""), alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-3.8-flash", alias="GEMINI_MODEL")
    gemini_max_rpm: int = Field(default=10, alias="GEMINI_MAX_RPM", gt=0)

    # Cost & Budget Guardrails
    cost_budget_usd: float = Field(default=0.50, alias="COST_BUDGET_USD", gt=0.0)
    price_input_per_m: float = Field(default=1.50, alias="PRICE_INPUT_PER_M", ge=0.0)
    price_output_per_m: float = Field(default=7.50, alias="PRICE_OUTPUT_PER_M", ge=0.0)

    # Policy & Thresholds
    senior_po_threshold_usd: float = Field(default=10000.0, alias="SENIOR_PO_THRESHOLD_USD", ge=0.0)
    low_confidence: float = Field(default=0.6, alias="LOW_CONFIDENCE", ge=0.0, le=1.0)
    service_level: float = Field(default=0.95, alias="SERVICE_LEVEL", ge=0.0, le=1.0)

    # Storage Paths
    supply_db: str = Field(default="data/supply.db", alias="SUPPLY_DB")
    app_db: str = Field(default="data/app.db", alias="APP_DB")
    audit_path: str = Field(default="audit/audit.jsonl", alias="AUDIT_PATH")

    # Observability
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    langsmith_tracing: bool = Field(default=False, alias="LANGSMITH_TRACING")
    langsmith_api_key: SecretStr = Field(default=SecretStr(""), alias="LANGSMITH_API_KEY")
    langsmith_project: str = Field(default="supply-chain-agents", alias="LANGSMITH_PROJECT")


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings singleton."""
    return Settings()
