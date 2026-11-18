import json
from pathlib import Path
from secrets import token_urlsafe

from pydantic import Field, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def validated_alpha(data: Path = DATA) -> float:
    path = data / "benchmark.json"
    if path.is_file():
        value = json.loads(path.read_text(encoding="utf-8")).get("alpha")
        if isinstance(value, (int, float)) and 0 < value < 1:
            return float(value)
    return 0.5


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./matchbench.db"
    session_secret: SecretStr = Field(default_factory=lambda: SecretStr(token_urlsafe(48)))
    secure_cookies: bool = False
    model_dir: Path = ROOT / ".models"
    openai_api_key: SecretStr | None = None
    llm_base_url: HttpUrl | None = None
    llm_model: str = "gpt-4.1-mini"
    llm_timeout_seconds: float = 8
    allow_demo_llm: bool = False
    max_upload_bytes: int = 4 * 1024 * 1024
    seed_demo: bool = True
    create_schema: bool = False
    cors_origins: list[str] = []
    rerank_timeout_seconds: float = 2.5

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openai_api_key or self.llm_base_url)
