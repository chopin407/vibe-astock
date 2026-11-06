import sys
from pathlib import Path
from datetime import datetime
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sources import industry_observation as I
from sources import mx_supplement as M
from common import TZ_SH


def test_catalog_groups_full_members_and_nested_industries(monkeypatch):
    stocks = [{"Code": f"600{i:03}", "TdxHy": "T010101"} for i in range(20)]
    indices = [{"Name": "煤炭", "Code": "880301", "Type": 2, "Ref": "T0101"}, {"Name": "开采", "Code": "880302", "Type": 2, "Ref": "T010101"}]
    monkeypatch.setattr(I.T, "request", lambda p: stocks if p == "/tdx/hy" else indices)
    r = I.catalog()
    assert len(r["groups"]) == 1 and len(r["groups"][0]["members"]) == 20
    assert r["membership_version"]


def test_index_relative_requires_matching_adjacent_days():
    base = [{"date": f"2026-11-0{i}", "close": 100+i} for i in range(3, 7)]
    assert len(I.relative_series(base, base, "2026-11-06")) == 3
    assert len(I.relative_series([base[0], *base[2:]], base, "2026-11-06")) == 1
    assert I.relative_series(base, base, "2026-11-09") == []


@pytest.mark.parametrize("time,mode,ok", [("20261106161445", "close", True), ("20261105150000", "close", False), ("20261106100000", "intraday", False), ("bad", "close", False), ("20261106161600", "close", False)])
def test_quote_time_validation(time, mode, ok):
    now = datetime(2026, 11, 6, 16, 15, tzinfo=TZ_SH)
    assert I.valid_quote({"quote_time": time}, "2026-11-06", mode, now) is ok


def test_observe_retains_missing_members_and_checks_coverage(monkeypatch):
    codes = [f"600{i:03}" for i in range(12)]
    monkeypatch.setattr(I, "catalog", lambda: {"groups": [{"id": "T0101", "name": "煤炭", "members": codes, "index_code": "880301"}], "membership_version": "v1", "observed_at": "2026-11-06"})
    monkeypatch.setattr(I.S, "review_day", lambda d: "2026-11-06")
    monkeypatch.setattr(I.S, "today_sh", lambda: "2026-11-06")
    monkeypatch.setattr(I.S, "prev_trade_date", lambda d: "2026-11-05")
    monkeypatch.setattr(I.S, "is_settled", lambda d: True)
    monkeypatch.setattr(I.S, "now_sh", lambda: datetime(2026, 11, 6, 20, 0, tzinfo=TZ_SH))
    rows = {c: {"price": 10, "change_pct": 2, "quote_time": "20261106161445"} for c in codes[:10]}
    rows["sh000001"] = {"price": 10, "change_pct": -1, "quote_time": "20261106161445"}
    monkeypatch.setattr(I.Q, "quotes", lambda c: rows)
    monkeypatch.setattr(I.T, "index_daily", lambda c, d: [])
    r = I.observe("T0101")
    assert len(r["directions"][0]["members"]) == 12
    assert r["directions"][0]["checks"]["active"] is None
    assert r["directions"][0]["metrics"]["coverage"] == 10/12


def test_mx_empty_success_is_not_complete_members(monkeypatch):
    monkeypatch.setattr(M, "request", lambda *a: {"dataTableDTOList": []})
    monkeypatch.setattr(M.S, "review_day", lambda d: d)
    r = M.data("煤炭", "2026-11-06")
    assert not r["available"] and r["members"] == [] and not r["complete"]


def test_mx_articles_need_safe_url_and_nonfuture_date(monkeypatch):
    good = {"title": "公告", "jumpUrl": "https://example.org/report", "date": "2026-11-06 10:00:00"}
    monkeypatch.setattr(M, "request", lambda *a: {"llmSearchResponse": {"data": [good, good, {**good, "date": "2026-11-09"}, {**good, "jumpUrl": "javascript:evil"}]}})
    monkeypatch.setattr(M.S, "review_day", lambda d: d)
    r = M.news("煤炭", "2026-11-06")
    assert len(r["articles"]) == 1
    assert r["articles"][0]["url"].startswith("https:")


def test_mx_no_key_fails_before_network(monkeypatch):
    monkeypatch.delenv("MX_APIKEY", raising=False)
    with pytest.raises(ValueError, match="未配置"):
        M.request("query", {})


def test_mx_fallback_is_public_metrics_not_membership(monkeypatch):
    monkeypatch.setattr(M.S, "review_day", lambda d: d)
    seen = []
    def request(route, payload):
        seen.append(payload)
        return {"dataTableDTOList": [] if len(seen) == 1 else [{"table": {"headName": ["2026-11-06"], "price": ["12元"]}}]}
    monkeypatch.setattr(M, "request", request)
    r = M.data("煤炭", "2026-11-06", ["601088"])
    assert r["available"] and r["members"] == [] and not r["complete"]
    assert "不据此证明方向关系" in r["note"]
    assert len(seen) == 2
    with pytest.raises(ValueError):
        M.data("煤炭", "2026-11-06", ["../../private"])
