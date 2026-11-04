"""Local TDX HTTP API; same wire protocol as a-stock-dashboard."""
from __future__ import annotations
import os
import math
import json
import hashlib
import time
from pathlib import Path
import requests
from sources._http import record_raw
from sources.tencent import tencent_prefix


CONFIG_PATH = Path(__file__).resolve().parents[5] / ".local" / "tdx.json"


def settings():
    """Load local-only configuration; environment variables override file values."""
    config = {}
    if CONFIG_PATH.exists():
        try:
            config = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
            if not isinstance(config, dict):
                raise ValueError()
        except (ValueError, OSError):
            raise RuntimeError("本地 .local/tdx.json 必须是有效的 JSON 对象") from None
    values = {}
    for field, env in (("base_url", "VRA_TDX_BASE_URL"), ("token", "VRA_TDX_TOKEN")):
        value = os.environ.get(env, config.get(field, ""))
        if not isinstance(value, str):
            raise RuntimeError(f"TDX 配置 {field} 必须是字符串")
        values[field] = value.strip()
    values["base_url"] = values["base_url"].rstrip("/")
    return values


def request(path, _out_dir=None, _timeout=15, **params):
    config = settings()
    base = config["base_url"]
    if not base:
        raise RuntimeError("请在 .local/tdx.json 中配置 base_url 为局域网 TDX HTTP 服务地址")
    token = config["token"]
    if not path.startswith("/") or path.startswith("//") or ".." in path or "://" in path:
        raise ValueError("TDX 路径必须是服务内相对路径")
    from data_service import settings as service_settings, attempt
    policy = service_settings()
    with attempt("tdx-lan", path), requests.Session() as session:
        session.trust_env = False
        r = session.get(base + path, params=params,
                        headers={"Authorization": "Bearer " + token} if token else {}, timeout=(policy["connect_timeout_sec"], _timeout), allow_redirects=False)
        record_raw(r.content, "json", base + path)
        r.raise_for_status()
        payload = r.json()
        if not isinstance(payload, dict) or payload.get("code") != 0:
            raise ValueError("TDX 返回失败或无效信封")
        if _out_dir:
            from common import save_raw
            save_raw(_out_dir, "tdx-lan", path, r.content, "json")
        return payload.get("data")


HEALTH_DIR = CONFIG_PATH.parent / "cache" / "tdx-health"


def available():
    """Share short-lived health probes across fetch workers; never store credentials."""
    from common import _lock_em_file, _unlock_em_file, atomic_write_json
    from data_service import settings as service_settings
    config = settings()
    if not config["base_url"]:
        return False
    policy = service_settings()
    key = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()

    def probe():
        try:
            data = request("/", _timeout=policy["connect_timeout_sec"])
            return isinstance(data, dict) and data.get("status") == "running"
        except Exception:
            return False

    try:
        HEALTH_DIR.mkdir(parents=True, exist_ok=True)
        file = HEALTH_DIR / (key + ".json")
        with open(HEALTH_DIR / (key + ".lock"), "a+") as lock:
            _lock_em_file(lock)
            try:
                try:
                    cached = json.loads(file.read_text(encoding="utf-8"))
                    ttl = policy["tdx_health_ttl_sec"] if cached["ok"] else policy["tdx_failure_ttl_sec"]
                    if isinstance(cached["ok"], bool) and 0 <= time.time() - cached["at"] < ttl:
                        return cached["ok"]
                except (ValueError, OSError, KeyError, TypeError):
                    pass
                ok = probe()
                atomic_write_json(str(file), {"ok": ok, "at": time.time()})
                return ok
            finally:
                _unlock_em_file(lock)
    except OSError:
        return probe()


def number(row, field, scale=1):
    value = row.get(field)
    if value is None:
        return None
    value = float(value) / scale
    return value if math.isfinite(value) else None


def quotes(codes):
    if isinstance(codes, str):
        codes = codes.split(",")
    keys = {tencent_prefix(c): c for c in codes}
    if not keys:
        return {}
    if any(not k.startswith(("sh", "sz", "bj")) for k in keys):
        raise ValueError("TDX 行情仅支持 A 股代码，指数请显式提供市场前缀")
    from sources._http import last_raw_ref
    result = {}
    for offset in range(0, len(keys), 80):
        batch = list(keys)[offset:offset+80]
        for row in request("/quote", codes=",".join(batch)) or []:
            k = row.get("Kline") or {}
            symbol = str(row.get("Code") or k.get("Code") or "").lower()
            if len(symbol) == 6 and symbol.isdigit():
                symbol = {0: "sz", 1: "sh", 2: "bj"}.get(row.get("Exchange"), "") + symbol
            if symbol not in keys:
                continue
            price, last = number(k, "Close", 1000), number(k, "Last", 1000)
            result[keys[symbol]] = {"name": row.get("Name"), "price": price,
                "last_close": last, "open": number(k, "Open", 1000),
                "high": number(k, "High", 1000), "low": number(k, "Low", 1000),
                "amount_wan": number(k, "Amount", 10000000),
                "change_pct": (price / last - 1) * 100 if price is not None and last else None,
                "quote_time": None,  # Response time is not verified exchange quote time.
                "response_time": k.get("Time"),
                "is_stale": price == last and number(k, "Amount") == 0,
                "query": symbol, "source": "tdx-lan", "_raw": last_raw_ref()}
    if not result:
        raise ValueError("TDX 行情为空")
    return result


def kline(digits, market, out_dir, bars, timeout, res):
    from common import save_raw
    from data_service import settings as service_settings
    if not available():
        raise RuntimeError("局域网 TDX 未就绪")
    symbol = market.lower() + digits
    data = request("/kline/day/qfq", _out_dir=out_dir, _timeout=max(timeout, service_settings()["tdx_kline_timeout_sec"]), code=symbol, start=0, count=min(bars, 800))
    rows = sorted((data or {}).get("List") or [], key=lambda r: str(r.get("Time")))
    if not rows:
        raise ValueError("TDX K 线为空")
    # Keep the legacy raw sequence contract used by calc consumers.
    values = [[str(r["Time"])[:10], number(r,"Open",1000), number(r,"Close",1000),
               number(r,"High",1000), number(r,"Low",1000), number(r,"Volume"), number(r,"Amount",1000)] for r in rows]
    import json
    raw = save_raw(out_dir, "tdx-lan", "kline/day/qfq", json.dumps(values).encode(), "json", "extracted")
    return values, raw, "tdx-lan", "kline/day/qfq"


def index_daily(code, days):
    """Unadjusted index bars, using dashboard's /index/day protocol and units."""
    from datetime import datetime
    from sources._http import last_raw_ref
    from data_service import settings as service_settings
    data = request("/index/day", code=code, start=0, count=min(int(days), 800), _timeout=service_settings()["tdx_read_timeout_sec"])
    rows = []
    for row in (data or {}).get("List", []):
        day = str(row.get("Time", ""))[:10]
        datetime.strptime(day, "%Y-%m-%d")
        close = number(row, "Close", 1000)
        amount = number(row, "Amount", 1000)
        if close is None or close <= 0 or (amount is not None and amount < 0):
            raise ValueError("TDX 指数日线包含无效价格或成交额")
        rows.append({"date": day, "close": close, "amount": amount, "_raw": last_raw_ref()})
    if not rows:
        raise ValueError("TDX 指数日线为空")
    return sorted(rows, key=lambda r: r["date"])
