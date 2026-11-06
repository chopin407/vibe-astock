"""TDX 时点行业成分与完整成员观察；行业指数与成员广度分开留证。"""
from __future__ import annotations

import hashlib
import re
import statistics
import math
from typing import Optional
from datetime import datetime
from sources import shortline as S, tdx_lan as T, quotes_service as Q
from sources.mappers_shortline import _Acc


def catalog(scan: bool = False) -> dict:
    if not isinstance(scan, bool):
        raise ValueError("scan 必须是布尔值")
    stocks, indices = T.request("/tdx/hy"), T.request("/tdx/zs")
    if not isinstance(stocks, list) or not isinstance(indices, list):
        raise ValueError("行业目录结构无效")
    groups: list[dict] = []
    for index in indices:
        ref = str(index.get("Ref", ""))
        if index.get("Type") != 2 or not re.fullmatch(r"T\d{4}", ref):
            continue
        members = sorted({str(r["Code"]) for r in stocks if str(r.get("TdxHy", "")).startswith(ref) and re.fullmatch(r"\d{6}", str(r.get("Code", "")))})
        if not members:
            continue
        groups.append({"id": ref, "name": str(index["Name"]), "index_code": str(index["Code"]), "members": members, "member_count": len(members)})
    if not groups:
        raise ValueError("没有完整行业成员")
    now = S.now_sh().isoformat()
    if scan:
        end = S.review_day(None)
        benchmark = T.index_daily("sh000001", 8)
        for g in groups:
            try:
                g["trend"] = relative_series(T.index_daily("sh" + g["index_code"], 8), benchmark, end)
            except Exception:
                g["trend"] = []
        groups.sort(key=lambda g: -(g["trend"][-1]["relative_pct"] if g["trend"] else -1e10))
    return {"date": S.today_sh(), "settled": False, "observed_at": now, "membership_version": hashlib.sha256(str((stocks, indices)).encode()).hexdigest(),
            "groups": groups, "point_in_time": "本次下载的TDX分类表全成员；源未给分类更新日，不等于交易所最新成分，仅用于本次及以后观察，不回填历史"}


def relative_series(rows: list[dict], benchmark: list[dict], end: str) -> list[dict]:
    def changes(items):
        items = sorted([r for r in items if r["date"] <= end], key=lambda r: r["date"])
        return {(a["date"], b["date"]): (b["close"] / a["close"] - 1) * 100 for a, b in zip(items, items[1:]) if a["close"] > 0}
    a, b = changes(rows), changes(benchmark)
    # 按基准最后三交易日逐日对齐，缺一天即未知，不跨缺口冒充连续。
    days = sorted(b)[-3:]
    if not days or days[-1][1] != end:
        return []
    return [{"date": d[1], "relative_pct": a[d] - b[d]} for d in days if d in a]


def valid_quote(q: dict, day: str, mode: str, now: datetime) -> bool:
    stamp = str(q.get("quote_time", ""))
    if not re.fullmatch(r"\d{14}", stamp) or not stamp.startswith(day.replace("-", "")):
        return False
    try:
        t = datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=S.TZ_SH)
    except ValueError:
        return False
    if mode == "intraday":
        return 0 <= (now - t).total_seconds() <= 60 and (("093000" <= stamp[8:] <= "113000") or ("130000" <= stamp[8:] < "145700"))
    return stamp[8:] >= "150000" and t <= now


def observe(industry_id: str, date: Optional[str] = None, mode: str = "close") -> dict:
    if mode not in {"close", "intraday"}:
        raise ValueError("观察模式无效")
    day = S.review_day(date or S.today_sh())
    if day != S.today_sh():
        raise ValueError("当前成分不能回填历史；请读取保存的行业快照")
    if mode == "close" and not S.is_settled(day):
        raise ValueError("尚未收盘")
    cat = catalog()
    group = next((g for g in cat["groups"] if g["id"] == industry_id), None)
    if not group:
        raise ValueError("行业标识不存在")
    quotes, gaps = {}, []
    codes = [*group["members"], "sh000001"]
    for start in range(0, len(codes), 50):
        try:
            quotes.update(Q.quotes(codes[start:start + 50]))
        except Exception:
            gaps.append("一批行业行情取数失败")
    now = S.now_sh()
    benchmark = quotes.get("sh000001", {})
    benchmark_ret = benchmark.get("change_pct") if valid_quote(benchmark, day, mode, now) and isinstance(benchmark.get("change_pct"), (int, float)) and math.isfinite(benchmark["change_pct"]) else None
    members, valid_returns, times = [], [], []
    for code in group["members"]:
        q = quotes.get(code, {})
        valid = valid_quote(q, day, mode, now) and isinstance(q.get("change_pct"), (float, int)) and math.isfinite(q["change_pct"]) and isinstance(q.get("price"), (int, float)) and q["price"] > 0
        if valid:
            valid_returns.append(q["change_pct"])
            times.append(q["quote_time"])
        members.append({"code": code, "name": q.get("name") or code, "role": "行业完整成分", "observation_date": day,
                        "close": q.get("price") if valid else None, "ret": q.get("change_pct") if valid else None,
                        "amount": q.get("amount_wan") * 1e4 if valid and q.get("amount_wan") is not None else None,
                        "turnover": q.get("turnover_pct") if valid else None, "quote_time": q.get("quote_time"),
                        "source": q.get("source"), "raw_ref": q.get("_raw"),
                        "valuation": {"pe_ttm": q.get("pe_ttm"), "pb": q.get("pb"), "market_cap": q.get("mcap_yi")} if valid else {}})
    n = len(valid_returns)
    if benchmark_ret is not None:
        times.append(benchmark["quote_time"])
    coverage = n / len(members)
    median = statistics.median(valid_returns) if n else None
    breadth = sum(v > 0 for v in valid_returns) / n if n else None
    complete = coverage >= .9 and n >= 10 and benchmark_ret is not None
    if not complete:
        gaps.append(f"有效同日行情 {n}/{len(members)}；广度需覆盖至少90%、至少10只及有效基准")
    active = bool(breadth >= .6 and median > benchmark_ret) if complete and breadth is not None and median is not None and benchmark_ret is not None else None
    trend = []
    try:
        trend = relative_series(T.index_daily("sh" + group["index_code"], 8), T.index_daily("sh000001", 8), day if mode == "close" else S.review_day(None))
    except Exception:
        gaps.append("行业指数持续性缺数据")
    persistent = bool(active and all(r["relative_pct"] > 0 for r in trend)) if complete and len(trend) == 3 else None
    return {"schema_version": 1, "algorithm_version": "industry-v1", "date": day, "mode": mode, "settled": S.is_settled(day),
            "observed_at": now.isoformat(), "previous_date": S.prev_trade_date(day), "scope": "TDX 当前行业完整成分观察；持续性使用行业指数，非逐日成分中位数", "time_basis": "exchange_quotes",
            "coverage": [{"date": day, "available": True, "covered": n, "total": len(members), "complete": complete}],
            "directions": [{"id": industry_id, "tag": group["name"], "kind": "industry", "limit_up": 0, "first_boards": 0, "previous": 0,
                            "continuation": None, "broken_rate": None, "series": [], "members": members,
                            "checks": {"active": active, "persistent": persistent, "expanded": None, "divergent": None, "absent": None},
                            "metrics": {"coverage": coverage, "median_pct": median, "up_share": breadth, "benchmark_pct": benchmark_ret, "index_relative": trend},
                            "quote_times": {"min": min(times) if times else None, "max": max(times) if times else None}}],
            "gaps": gaps, "industry_available": True, "industry_reason": "", "membership_version": cat["membership_version"], "catalog_observed_at": cat["observed_at"]}


def map_catalog(result: dict, ctx: dict) -> dict:
    a = _Acc(ctx, result["date"])
    a.num("industry_catalog_count", len(result["groups"]), "个")
    return a.finish(False, {"result": result}, "行业目录不可用")


def map_observation(result: dict, ctx: dict) -> dict:
    a = _Acc(ctx, result["date"])
    for d in result["directions"]:
        for key, unit in [("median_pct", "%"), ("up_share", "小数"), ("coverage", "小数"), ("benchmark_pct", "%")]:
            a.num("industry_" + key, d["metrics"][key], unit, key=d["id"])
    for gap in result["gaps"]:
        a.missing.append({"field": "industry_input", "period": result["date"], "reason": gap})
    return a.finish(result["settled"], {"result": result}, "行业观察缺少有效行情")
