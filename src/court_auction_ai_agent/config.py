from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUCTION_AI_", env_file=".env", extra="ignore")

    crawler_db_path: Path = Path("/var/lib/court-auction-collector/data/court_auction.sqlite3")
    db_path: Path = Path("/var/lib/court-auction-ai-agent/data/auction_ai.sqlite3")
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "gemma4:e4b"
    ollama_timeout_seconds: int = 900
    worker_interval_seconds: int = 5
    max_attempts: int = 3
    prompt_version: str = "investment-risk-v2"
    schema_version: str = "investment-risk-v2"
