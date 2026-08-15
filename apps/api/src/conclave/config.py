from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[4]  # Conclave/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CONCLAVE_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://conclave:conclave@localhost:5433/conclave"
    secret_key: str = "dev-insecure-change-me"
    data: Path = ROOT / "data"
    embed_runner: bool = True

    # E2E/testing only: enables the deterministic "fake" provider (never shown in the UI).
    enable_fake_provider: bool = False
    fake_turn_delay: float = 0.4

    runner_concurrency: int = 8
    lease_seconds: int = 90
    turn_window: int = 12  # last K verbatim turns in an expert's context
    max_tool_iterations: int = 6
    gist_ledger_chars: int = 6000
    safety_lap_ceiling: int = 40


settings = Settings()
