from pydantic import Field

from aegis.core.config import Settings


class ServingSettings(Settings):
    serving_model: str = "fraud-detector"
    metrics_window_seconds: int = Field(default=3600, ge=60, le=604800)
    max_request_bytes: int = Field(default=16384, ge=1024, le=1048576)
    serving_database_timeout_seconds: int = Field(default=5, ge=1, le=30)
    serving_max_concurrency: int = Field(default=32, ge=1, le=256)
