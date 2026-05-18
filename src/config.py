from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
import os


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    gigachat_credentials: str
    gigachat_model: str
    gigachat_scope: str | None
    gigachat_verify_ssl_certs: bool
    services_csv: Path
    salon_timezone: str
    salon_name: str
    address: str
    work_start_hour: int
    work_end_hour: int
    # Yandex Disk - client storage
    yandex_disk_token: str
    yandex_disk_file_path: str
    # Yandex Calendar - CalDAV
    yandex_caldav_url: str
    yandex_caldav_username: str
    yandex_caldav_password: str


def _require(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val


def load_config() -> Config:
    load_dotenv()

    services_csv = Path(os.getenv("SERVICES_CSV", "services_pricelist.csv"))

    return Config(
        telegram_bot_token=_require("TELEGRAM_BOT_TOKEN"),
        gigachat_credentials=_require("GIGACHAT_CREDENTIALS"),
        gigachat_model=os.getenv("GIGACHAT_MODEL", "GigaChat"),
        gigachat_scope=(os.getenv("GIGACHAT_SCOPE") or "").strip() or None,
        gigachat_verify_ssl_certs=(os.getenv("GIGACHAT_VERIFY_SSL_CERTS", "true").strip().lower() != "false"),
        services_csv=services_csv,
        salon_timezone=os.getenv("SALON_TIMEZONE", "Europe/Moscow"),
        salon_name=os.getenv("SALON_NAME", "Аарон"),
        address=os.getenv("ADDRESS", ""),
        work_start_hour=int(os.getenv("WORK_START_HOUR", "10")),
        work_end_hour=int(os.getenv("WORK_END_HOUR", "20")),
        yandex_disk_token=_require("YANDEX_DISK_TOKEN"),
        yandex_disk_file_path=os.getenv("YANDEX_DISK_FILE_PATH", "/salon-bot/clients.xlsx"),
        yandex_caldav_url=_require("YANDEX_CALDAV_URL"),
        yandex_caldav_username=_require("YANDEX_CALDAV_USERNAME"),
        yandex_caldav_password=_require("YANDEX_CALDAV_PASSWORD"),
    )
