"""完整事件样本的方向观察；不使用题材树的展示截断名单。"""
from __future__ import annotations

import hashlib
from typing import Optional

from sources import shortline as S
from sources.shortline_themes import limit_reasons, tags_of
from sources.mappers_shortline import _Acc


def live_quote_gate(result: dict) -> None:
    from sources import quotes_service as Q
    from sources.industry_observation import valid_quote
    quotes = {}
    codes = sorted({m["code"] for d in result["directions"] for m in d["members"]})
    for i in range(0, len(codes), 50):
        try:
            quotes.update(Q.quotes(codes[i:i + 50]))
        except Exception:
            result["gaps"].append("盘中样本报价核验缺一批数据")
    now = S.now_sh()
    for d in result["directions"]:
        times, matched = [], True
        for m in d["members"]:
            q = quotes.get(m["code"], {})
            if not valid_quote(q, result["date"], "intraday", now):
                matched = False
                continue
            if m["observation_date"] == result["date"] and (not q.get("limit_up") or not q.get("price") or abs(q["price"] - q["limit_up"]) > .001):
                matched = False
            times.append(q["quote_time"])
            m.update(close=q.get("price"), ret=q.get("change_pct"), quote_time=q["quote_time"], observation_date=result["date"],
                     amount=q.get("amount_wan") * 1e4 if q.get("amount_wan") is not None else None, turnover=q.get("turnover_pct"),
                     source=q.get("source"), valuation={"pe_ttm": q.get("pe_ttm"), "pb": q.get("pb"), "market_cap": q.get("mcap_yi")})
        d["metrics"] = {"coverage": len(times) / len(d["members"]) if d["members"] else 0}
        d["quote_times"] = {"min": min(times) if times and matched else None, "max": max(times) if times and matched else None}
    result["time_basis"] = "exchange_quotes"
    result["membership_version"] = hashlib.sha256(str([(d["id"], [m["code"] for m in d["members"]]) for d in result["directions"]]).encode()).hexdigest()
    result["observed_at"] = now.isoformat()


def collect(day: str) -> dict:
    gaps = []
    try:
        rows = S.pool("zt", day)
        if not rows:
            raise ValueError("涨停池为空，尚不能证明是有效零值")
    except Exception:
        return {"date": day, "available": False, "gaps": [f"{day} 涨停池不可用"]}
    reasons, note = limit_reasons(day)
    members: dict[str, dict] = {}
    for row in rows:
        code = row["code"]
        if code in members:
            continue
        members[code] = {**row, "tags": sorted(set(tags_of(reasons.get(code, ""))))}
    covered = sum(bool(r["tags"]) for r in members.values())
    if covered != len(members):
        gaps.append(f"{day} 事件归因覆盖 {covered}/{len(members)}，数量为已覆盖样本下限")
    # 炸板失败只影响分歧维度，不使涨停事实失效。
    try:
        broken = S.pool("zb", day)
    except Exception:
        broken = None
        gaps.append(f"{day} 炸板池不可用")
    return {"date": day, "available": True, "members": members, "broken": broken,
            "reasons": reasons, "covered": covered, "total": len(members),
            "complete": covered == len(members), "source_note": note, "gaps": gaps}


def analyze(days: list[dict]) -> list[dict]:
    current = days[-1]
    if not current["available"]:
        return []
    prev = days[-2] if len(days) > 1 and days[-2]["available"] else None
    tags = {tag for d in days if d["available"] for r in d["members"].values() for tag in r["tags"]}
    result = []
    for tag in sorted(tags):
        series = []
        for d in days:
            count = sum(tag in r["tags"] for r in d.get("members", {}).values())
            series.append(count if d.get("complete") or count else None)
        members = [r for r in current["members"].values() if tag in r["tags"]]
        yesterday = [r for r in prev["members"].values() if tag in r["tags"]] if prev else []
        size, base = len(members), len(yesterday)
        first = sum(r.get("boards") == 1 for r in members)
        again = sum(r["code"] in current["members"] for r in yesterday)
        continuation = again / base if base else None
        broken = current["broken"]
        broken_codes = set()
        unknown = False
        if broken is not None:
            for r in broken:
                if r["code"] in current["members"]:
                    continue
                reason = current["reasons"].get(r["code"]) or (prev["reasons"].get(r["code"]) if prev else None)
                rt = tags_of(reason)
                if not rt:
                    unknown = True
                if tag in rt:
                    broken_codes.add(r["code"])
        attempts = size + len(broken_codes)
        rate = len(broken_codes) / attempts if broken is not None and not unknown and attempts else None
        active = True if size >= 3 else (False if current["complete"] else None)
        history_known = len(days) == 3 and all(d["available"] and d["complete"] for d in days)
        # 已覆盖固定队列的正向证据可成立；缺失关系不能支持消失/全市场领先。
        observed_persistent = len(days) == 3 and all(d["available"] for d in days) and size >= 3 and all((v or 0) > 0 for v in series) and base >= 3 and continuation is not None and continuation >= .3
        persistent = True if observed_persistent else (False if history_known else None)
        expanded = bool(size >= 3 and first >= 2 and size > base > 0) if prev and prev["complete"] and current["complete"] else None
        checks = {"active": active, "persistent": persistent, "expanded": expanded,
                  "divergent": rate >= .5 if rate is not None and attempts >= 4 else None,
                  "absent": base >= 3 and size == 0 if prev and prev["complete"] and current["complete"] else None}
        # 同方向内部去重，保留昨日未再涨停者，不能仅观察幸存者。
        cohort = {r["code"]: {**r, "role": "昨日样本", "observation_date": prev["date"]} for r in yesterday} if prev else {}
        cohort.update({r["code"]: {**r, "role": "今日首板" if r.get("boards") == 1 else "今日涨停样本", "observation_date": current["date"]} for r in members})
        result.append({"id": hashlib.sha256(tag.encode()).hexdigest()[:16], "tag": tag,
                       "limit_up": size, "first_boards": first, "previous": base,
                       "continuation": continuation, "broken_rate": rate, "series": series,
                       "checks": checks, "members": sorted(cohort.values(), key=lambda r: r["code"])})
    return sorted(result, key=lambda d: (-d["limit_up"], d["tag"]))


def build(date: Optional[str] = None, mode: str = "close") -> dict:
    if mode not in {"close", "intraday"}:
        raise ValueError("mode 必须是 close 或 intraday")
    d = S.review_day(date if mode == "close" else (date or S.today_sh()))
    if mode == "close" and not S.is_settled(d):
        raise ValueError("尚未收盘，请选择盘中观察")
    if mode == "intraday" and d != S.today_sh():
        raise ValueError("历史盘中请读取已保存快照，不能用当前数据回填")
    dates = [d]
    for _ in range(2):
        prev = S.prev_trade_date(dates[0])
        if prev:
            dates.insert(0, prev)
    days = [collect(day) for day in dates]
    now = S.now_sh().isoformat()
    result = {"schema_version": 1, "algorithm_version": "event-v1", "date": d, "mode": mode,
            "settled": S.is_settled(d), "observed_at": now, "previous_date": S.prev_trade_date(d), "time_basis": "fetched_only",
            "scope": "事件涨停样本，非全市场行业趋势", "directions": analyze(days),
            "coverage": [{k: day.get(k) for k in ("date", "available", "covered", "total", "complete")} for day in days],
            "gaps": [gap for day in days for gap in day["gaps"]], "inputs": days,
            "industry_available": False, "industry_reason": "此版本仅包含事件样本，行业完整成分在独立通道生成"}
    if mode == "intraday":
        live_quote_gate(result)
    return result


def map_result(result: dict, ctx: dict) -> dict:
    a = _Acc(ctx, result["date"])
    if result["coverage"][-1]["available"]:
        a.num("mainline_direction_count", len(result["directions"]), "个")
    for d in result["directions"]:
        a.num("mainline_observed_limit_up", d["limit_up"], "只", key=d["id"], note=d["tag"])
        a.num("mainline_continuation", d["continuation"], "小数", key=d["id"])
    for gap in result["gaps"]:
        a.missing.append({"field": "mainline_inputs", "period": result["date"], "reason": gap})
    return a.finish(result["settled"], {"result": result, "computation": {"library": "sources.mainline.build", "version": "event-v1"}}, "事件方向输入不可用")
