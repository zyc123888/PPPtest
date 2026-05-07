from datetime import datetime, timezone

def utc_now_naive() -> datetime:
    """返回当前 UTC 的 naive 时间（用于写入 timezone=False 的列）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)

def to_utc_naive(dt: datetime) -> datetime:
    """将任意 datetime 规范为 UTC naive（aware 会先转 UTC 再去 tzinfo；naive 视为 UTC）。"""
    if dt.tzinfo is None:
        return dt  # 约定 naive 即 UTC
    return dt.astimezone(timezone.utc).replace(tzinfo=None)
