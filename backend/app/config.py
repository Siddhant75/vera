from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    token_factory_api_key: str = ""
    tavily_api_key: str = ""
    token_factory_base_url: str = "https://api.tokenfactory.nebius.com/v1"
    planner_model: str = ""
    verifier_models: Annotated[list[str], NoDecode] = []
    db_path: str = "vera.db"
    daily_token_budget: int = 0  # 0 = unlimited; guards credits on hosted demos
    watch_interval_minutes: int = 0  # watcher cycle; 0 = off. Deployed default: 30
    max_watches: int = 0  # 0 = unlimited; caps watch-slot farming on public demos
    digest_webhook_url: str = ""  # operator-set only (SSRF-safe); Slack/Discord/Zapier compatible

    @field_validator("verifier_models", mode="before")
    @classmethod
    def _split_csv(cls, v):
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    @field_validator("verifier_models")
    @classmethod
    def _validate_verifier_models(cls, v, info):
        if not v:
            return v  # unconfigured; build_app refuses to start without models
        if len(v) < 2:
            raise ValueError("verifier models need at least 2 distinct models")
        planner = info.data.get("planner_model", "")
        if planner in v:
            raise ValueError("verifier models must not include the planner model")
        return v
