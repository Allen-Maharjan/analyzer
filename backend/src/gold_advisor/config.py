from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PACKAGE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GA_", env_file=".env", extra="ignore")

    database_url: str

    @field_validator("database_url")
    @classmethod
    def _use_psycopg(cls, value: str) -> str:
        # Neon and most hosts give "postgresql://..." URLs; SQLAlchemy needs the driver named.
        for prefix in ("postgresql://", "postgres://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value[len(prefix):]
        return value
    redis_url: str = "redis://localhost:6379/0"

    http_timeout_seconds: float = 20.0
    http_user_agent: str = "nepal-gold-advisor/0.1 (self-hosted; household use)"

    node_binary: str = "node"
    dukascopy_script: Path = PACKAGE_DIR.parent.parent / "dukascopy" / "fetch.mjs"
    dukascopy_timeout_seconds: int = 900

    backfill_daily_years: int = Field(default=10, ge=1, le=20)
    backfill_hourly_days: int = Field(default=730, ge=1, le=3650)
    backfill_m15_days: int = Field(default=90, ge=1, le=365)
    backfill_nepal_months: int = Field(default=36, ge=1, le=120)
    backfill_fx_days: int = Field(default=3650, ge=1, le=7300)
    backfill_macro_years: int = Field(default=10, ge=1, le=30)

    fred_series: tuple[str, ...] = ("DGS2", "DGS10", "DFII10")

    # Shared secret for the host-side AI runner. Empty disables the runner endpoints.
    runner_token: str = ""

    # Cloud deployment (Vercel). When internal_token is set, every API request except
    # /api/v1/health and the runner endpoints must send it in X-Internal-Token.
    internal_token: str = ""
    # When set, the refresh and "Ask AI" buttons start the GitHub Actions cycle instead of
    # Celery. Fine-grained token with "Actions: read and write" on the repository.
    github_dispatch_token: str = ""
    github_repo: str = ""  # e.g. "Allen-Maharjan/analyzer"
    github_workflow: str = "collect.yml"
    github_ref: str = "main"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
