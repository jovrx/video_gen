import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field


class SystemSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_concurrent_generations: int = Field(default=3, ge=1, le=100, strict=True)
    client_cooldown_seconds: int = Field(default=60, ge=0, le=86400, strict=True)


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path("data"))
    api_key: str = field(default="", repr=False)
    workflow_id: str = "2108942308824670209"
    base_url: str = "https://www.runninghub.cn"
    poll_seconds: float = 5.0
    max_image_bytes: int = 30 * 1024 * 1024
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = field(default="", repr=False)
    llm_model: str = ""
    llm_timeout_seconds: float = 120.0

    @classmethod
    def from_env(cls):
        load_dotenv()
        return cls(data_dir=Path(os.getenv("VIDEO_DATA_DIR", "data")).resolve(),
                   api_key=os.getenv("RUNNINGHUB_API_KEY", "").strip(),
                   workflow_id=os.getenv("RUNNINGHUB_WORKFLOW_ID", "2108942308824670209").strip(),
                   base_url=os.getenv("RUNNINGHUB_BASE_URL", "https://www.runninghub.cn").rstrip("/"),
                   poll_seconds=max(1, float(os.getenv("VIDEO_POLL_SECONDS", "5"))),
                   llm_base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/"),
                   llm_api_key=os.getenv("LLM_API_KEY", "").strip(),
                   llm_model=os.getenv("LLM_MODEL", "").strip(),
                   llm_timeout_seconds=max(1, min(600, float(os.getenv("LLM_TIMEOUT_SECONDS", "120")))))
