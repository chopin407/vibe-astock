from copy import deepcopy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sources import mainline as M
from test_registry_sources import _ctx


def day(date="2026-11-06", n=4, complete=True, broken=None):
    members = {str(600001+i): {"code": str(600001+i), "name": f"样本{i}", "tags": ["算力"],
               "boards": 1, "amount": 1e8, "turnover": 5, "ret": 10, "close": 12} for i in range(n)}
    return {"date": date, "available": True, "members": members, "complete": complete,
            "broken": broken if broken is not None else [], "reasons": {}, "covered": n, "total": n, "gaps": []}


def test_full_members_not_display_top_eight():
    r = M.analyze([day(n=20)])[0]
    assert len(r["members"]) == 20
    assert r["checks"]["active"] is True
    assert r["checks"]["persistent"] is None


def test_persistence_and_divergence_can_coexist():
    days = [day("2026-11-04"), day("2026-11-05"), day()]
    days[-1]["broken"] = [{"code": str(601001+i)} for i in range(4)]
    days[-1]["reasons"] = {str(601001+i): "算力" for i in range(4)}
    r = M.analyze(days)[0]
    assert r["checks"]["persistent"] is True
    assert r["checks"]["divergent"] is True
    assert r["broken_rate"] == .5


def test_unknown_broken_relations_do_not_make_zero_rate():
    r = M.analyze([day(broken=[{"code": "601111"}])])[0]
    assert r["broken_rate"] is None
    assert r["checks"]["divergent"] is None


def test_other_missing_relations_do_not_erase_positive_fixed_sample():
    days = [day("2026-11-04", complete=False), day("2026-11-05", complete=False), day()]
    result = M.analyze(days)[0]
    assert result["checks"]["persistent"] is True
    assert result["checks"]["absent"] is None


def test_incomplete_absence_not_zero_or_fading():
    d = day(n=0, complete=False)
    r = M.analyze([day("2026-11-05"), d])[0]
    assert r["series"][-1] is None
    assert r["checks"]["absent"] is None
    assert len(r["members"]) == 4  # 昨日未延续成员仍在队列中
    assert all(m["observation_date"] == "2026-11-05" for m in r["members"])


def test_duplicate_tags_are_deduplicated(monkeypatch):
    row = day()["members"]["600001"]
    monkeypatch.setattr(M.S, "pool", lambda kind, d: [row] if kind == "zt" else [])
    monkeypatch.setattr(M, "limit_reasons", lambda d: ({"600001": "算力+算力"}, "test"))
    got = M.collect("2026-11-06")
    assert got["members"]["600001"]["tags"] == ["算力"]
    assert M.analyze([got])[0]["limit_up"] == 1


def test_broken_failure_does_not_remove_zt(monkeypatch):
    def pool(kind, d):
        if kind == "zb":
            raise TimeoutError()
        return list(day()["members"].values())
    monkeypatch.setattr(M.S, "pool", pool)
    monkeypatch.setattr(M, "limit_reasons", lambda d: ({k: "算力" for k in day()["members"]}, "test"))
    d = M.collect("2026-11-06")
    assert d["available"] and d["broken"] is None
    assert M.analyze([d])[0]["checks"]["active"] is True


def test_historical_intraday_and_unsettled_close_rejected(monkeypatch):
    monkeypatch.setattr(M.S, "review_day", lambda d: d)
    monkeypatch.setattr(M.S, "today_sh", lambda: "2026-11-06")
    monkeypatch.setattr(M.S, "is_settled", lambda d: False)
    with pytest.raises(ValueError, match="历史盘中"):
        M.build("2026-11-05", "intraday")
    with pytest.raises(ValueError, match="尚未收盘"):
        M.build("2026-11-06", "close")


def test_no_future_rows_in_build(monkeypatch):
    monkeypatch.setattr(M.S, "review_day", lambda d: "2026-11-06")
    monkeypatch.setattr(M.S, "is_settled", lambda d: True)
    monkeypatch.setattr(M.S, "prev_trade_date", lambda d: {"2026-11-06": "2026-11-05", "2026-11-05": "2026-11-04"}[d])
    seen = []
    def collect(d):
        seen.append(d)
        return deepcopy(day(d))
    monkeypatch.setattr(M, "collect", collect)
    r = M.build("2026-11-06")
    assert seen == ["2026-11-04", "2026-11-05", "2026-11-06"]
    mapped = M.map_result(r, _ctx(market="CN"))
    assert mapped["evidence"]
    assert mapped["extra"]["result"]["directions"][0]["checks"]["persistent"]
