# built-in
from datetime import datetime
from zoneinfo import ZoneInfo

APP_TIME_ZONE = ZoneInfo("Asia/Kolkata")


def now_ist() -> datetime:
    return datetime.now(APP_TIME_ZONE)
