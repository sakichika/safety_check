import uuid
from datetime import datetime, timedelta


def new_token() -> str:
    return uuid.uuid4().hex


def default_expiry(hours: int = 48) -> datetime:
    return datetime.utcnow() + timedelta(hours=hours)