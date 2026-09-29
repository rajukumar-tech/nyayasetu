from __future__ import annotations

from datetime import date
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(REPO_ROOT / ".env", ".env"), env_prefix="NYAYA_", extra="ignore")

    env: str = "development"
    database_url: str = f"sqlite:///{(REPO_ROOT / 'backend' / 'nyayasetu.db').as_posix()}"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "change-me-in-production"
    jwt_expiry_minutes: int = 12 * 60
    legal_data_dir: Path = REPO_ROOT / "data" / "legal"
    judgments_dir: Path = REPO_ROOT / "data" / "judgments"
    prompts_dir: Path = REPO_ROOT / "prompts"
    upload_dir: Path = REPO_ROOT / "backend" / "uploads"
    max_upload_mb: int = 25
    confidence_threshold: float = 0.8
    # Fixed "today" for reproducible demos/tests; None = real date.
    today_override: date | None = None
    # Demo only: marks the legal records used by the demo as verified, clearly labelled.
    demo_mode: bool = False
    llm_provider: str = "none"  # none | anthropic
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5-5"
    ocr_provider: str = "tesseract"
    documents_encryption_key: str | None = None  # Fernet key; documents stored encrypted when set
    cors_origins: list[str] = ["http://localhost:3000"]
    alert_escalation_days: int = 3

    def today(self) -> date:
        return self.today_override or date.today()


settings = Settings()
