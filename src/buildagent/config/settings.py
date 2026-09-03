from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed application settings.

    Loaded from process env with .env as fallback. All fields except
    optional runtime knobs are required; missing values raise at import
    of get_settings() rather than at first use, so misconfiguration
    fails fast.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    openai_api_key: str = Field(min_length=1)
    tavily_api_key: str = Field(min_length=1)

    langfuse_host: str = "http://localhost:3000"
    langfuse_public_key: str = Field(min_length=1)
    langfuse_secret_key: str = Field(min_length=1)

    openai_model: str = "gpt-5.6-luna"
    openai_extra_models: str = ""
    openai_request_timeout_s: float = 60.0

    max_loop_iterations: int = 10
    tavily_max_results: int = 5

    filesystem_root: str = "./data/workspace"

    # Browser tool: comma-separated URL prefix allowlist. Empty in dev means
    # allow-all; production should set it to a locked-down list.
    browser_allowed_url_prefixes: str = ""
    browser_headless: bool = True
    browser_nav_timeout_s: float = 30.0

    system_prompt_name: str = "main_agent"
    system_prompt_label: str = "production"

    @property
    def openai_model_whitelist(self) -> list[str]:
        extras = [m.strip() for m in self.openai_extra_models.split(",") if m.strip()]
        return list(dict.fromkeys([self.openai_model, *extras]))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
