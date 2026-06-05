from functools import lru_cache
from pathlib import Path
import os


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


class Settings:
    def __init__(self) -> None:
        _load_dotenv(PROJECT_ROOT / ".env")

        api_key = os.environ.get("SEATS_AERO_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("SEATS_AERO_API_KEY is required. Add it to .env or your shell environment.")

        self.seats_aero_api_key = api_key
        self.seats_aero_base_url = os.environ.get("SEATS_AERO_BASE_URL", "https://seats.aero").rstrip("/")
        self.request_timeout_seconds = float(os.environ.get("SEATS_AERO_REQUEST_TIMEOUT_SECONDS", "30"))
        self.enable_live_search = _as_bool(os.environ.get("SEATS_AERO_ENABLE_LIVE_SEARCH", "false"))


@lru_cache
def get_settings() -> Settings:
    return Settings()
