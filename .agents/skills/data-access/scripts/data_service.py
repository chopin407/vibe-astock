"""Shared local data-service policy and credential-free attempt diagnostics."""
from __future__ import annotations

import json
import math
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
CONFIG_PATH = ROOT / ".local" / "data-service.json"
DEFAULTS = {
    "connect_timeout_sec": 3,
    "http_read_timeout_cap_sec": 30,
    "tdx_read_timeout_sec": 8,
    "tdx_kline_timeout_sec": 60,
    "tdx_health_ttl_sec": 15,
    "tdx_failure_ttl_sec": 10,
    "review_live_cache_sec": 60,
    "review_cache": True,
}
_attempts: ContextVar[list | None] = ContextVar("data_attempts", default=None)


def settings():
    values = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
            if not isinstance(raw, dict):
                raise ValueError()
            for key, default in DEFAULTS.items():
                if key not in raw:
                    continue
                value = raw[key]
                if isinstance(default, bool):
                    if not isinstance(value, bool):
                        raise ValueError()
                elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= 600:
                    raise ValueError()
                values[key] = value
        except (ValueError, OSError):
            raise ValueError(".local/data-service.json 配置无效：时间须为 0~600 秒内的正数，review_cache 须为布尔值") from None
    return values


def request_timeout(value, scalar=False):
    """Bound transport waits without expanding a source's shorter timeout."""
    policy = settings()
    connect, read = value if isinstance(value, tuple) else (value, value)
    read = min(float(read), policy["http_read_timeout_cap_sec"])
    return read if scalar else (min(float(connect), policy["connect_timeout_sec"]), read)


@contextmanager
def diagnostics():
    attempts: list = []
    token = _attempts.set(attempts)
    try:
        yield attempts
    finally:
        _attempts.reset(token)


@contextmanager
def attempt(source, operation):
    started = time.monotonic()
    row = {"source": source, "operation": operation, "status": "ok"}
    try:
        yield
    except Exception as exc:
        row.update(status="failed", error=type(exc).__name__)
        raise
    finally:
        row["duration_ms"] = round((time.monotonic() - started) * 1000)
        records = _attempts.get()
        if records is not None:
            records.append(row)
