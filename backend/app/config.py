from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    token_factory_api_key: str = ""
    tavily_api_key: str = ""
    token_factory_base_url: str = "https://api.tokenfactory.nebius.com/v1"
    planner_model: str = ""
    verifier_models: Annotated[list[str], NoDecode] = []
    db_path: str = "vera.db"
    daily_token_budget: int = 0  # 0 = unlimited; guards credits on hosted demos

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
