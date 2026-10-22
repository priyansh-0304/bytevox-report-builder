"""Settings, read once at startup. Tests build their own Settings with small limits."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    db_path: str = "data/app.db"
    max_upload_bytes: int = 5 * 1024 * 1024  # 5 MB
    max_rows: int = 100_000
    cookie_secure: bool = False  # set RB_COOKIE_SECURE=1 when served over HTTPS
    session_days: int = 7

    @staticmethod
    def from_env() -> "Settings":
        return Settings(
            db_path=os.getenv("RB_DB_PATH", "data/app.db"),
            max_upload_bytes=int(os.getenv("RB_MAX_UPLOAD_MB", "5")) * 1024 * 1024,
            max_rows=int(os.getenv("RB_MAX_ROWS", "100000")),
            cookie_secure=os.getenv("RB_COOKIE_SECURE", "0") == "1",
        )
