"""Local TDX HTTP API; same wire protocol as a-stock-dashboard."""
from __future__ import annotations
import os
import math
import json
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
    with requests.Session() as session:
        session.trust_env = False
        r = session.get(base + path, params=params,
                        headers={"Authorization": "Bearer " + token} if token else {}, timeout=(3, _timeout))
    r.raise_for_status()
    payload = r.json()
    if not isinstance(payload, dict) or payload.get("code") != 0:
        raise ValueError("TDX 返回失败或无效信封")
    record_raw(r.content, "json", base + path)
    if _out_dir:
        from common import save_raw
        save_raw(_out_dir, "tdx-lan", path, r.content, "json")
    return payload.get("data")


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
                "query": symbol, "source": "tdx-lan"}
    if not result:
        raise ValueError("TDX 行情为空")
    return result


def kline(digits, market, out_dir, bars, timeout, res):
    from common import save_raw
    symbol = market.lower() + digits
    data = request("/kline/day/qfq", _out_dir=out_dir, _timeout=max(timeout, 60), code=symbol, start=0, count=min(bars, 800))
    rows = sorted((data or {}).get("List") or [], key=lambda r: str(r.get("Time")))
    if not rows:
        raise ValueError("TDX K 线为空")
    # Keep the legacy raw sequence contract used by calc consumers.
    values = [[str(r["Time"])[:10], number(r,"Open",1000), number(r,"Close",1000),
               number(r,"High",1000), number(r,"Low",1000), number(r,"Volume"), number(r,"Amount",1000)] for r in rows]
    import json
    raw = save_raw(out_dir, "tdx-lan", "kline/day/qfq", json.dumps(values).encode(), "json", "extracted")
    return values, raw, "tdx-lan", "kline/day/qfq"
