import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common
import data_service
from sources import quotes_service, tdx_lan, tencent, mappers_cn


def test_policy_file_validation(tmp_path, monkeypatch):
    file = tmp_path / "policy.json"
    monkeypatch.setattr(data_service, "CONFIG_PATH", file)
    assert data_service.settings()["review_cache"] is True
    file.write_text(json.dumps({"review_cache": False, "tdx_read_timeout_sec": 4}))
    assert data_service.settings()["tdx_read_timeout_sec"] == 4
    for value in [0, -1, True, "secret-example", 601, float("inf")]:
        file.write_text(json.dumps({"tdx_read_timeout_sec": value}))
        with pytest.raises(ValueError, match="配置无效") as err:
            data_service.settings()
        assert "secret-example" not in str(err.value)


def test_batch_partial_fallback_preserves_whole_rows_and_sources(monkeypatch):
    monkeypatch.setattr(tencent, "tencent_quotes", lambda _: {"usDJI": {"price": 4, "quote_time": "verified"}})
    monkeypatch.setattr(tdx_lan, "available", lambda: True)
    seen = []
    def local(codes):
        seen.extend(codes)
        return {c: {"price": 10, "quote_time": None, "source": "tdx-lan", "_raw": "raw/tdx.json"} for c in codes}
    monkeypatch.setattr(tdx_lan, "quotes", local)
    with data_service.diagnostics() as attempts:
        rows = quotes_service.quotes(["usDJI", "sh600519", "hkHSI"])
    assert seen == ["sh600519"]
    assert rows["usDJI"]["quote_time"] == "verified"
    assert rows["sh600519"]["quote_time"] is None
    assert len(attempts) == 2
    ctx = {"script": "tx_quotes_batch", "symbol": "MARKET", "market": "CN", "source": "tencent", "endpoint": "quotes", "args": {"codes": ["usDJI", "sh600519", "hkHSI"]}}
    mapped = mappers_cn.tencent_quotes_map(rows, ctx)
    local_price = next(e for e in mapped["evidence"] if e["record_key"] == "sh600519" and e["field"] == "price")
    assert local_price["source"] == "tdx-lan"
    assert local_price["raw_ref"] == "raw/tdx.json"
    assert any(m["record_key"] == "hkHSI" and m["field"] == "price" for m in mapped["missing"])
    assert any(m["record_key"] == "sh600519" and m["field"] == "quote_time" for m in mapped["missing"])


def test_failed_batch_reports_failure_and_diagnostics(monkeypatch):
    def fail(_):
        raise RuntimeError("upstream secret must not be logged")
    monkeypatch.setattr(tencent, "tencent_quotes", fail)
    monkeypatch.setattr(tdx_lan, "available", lambda: False)
    with data_service.diagnostics() as rows:
        with pytest.raises(RuntimeError, match="均未取得报价"):
            quotes_service.quotes(["sh600519"])
    assert rows[0]["error"] == "RuntimeError"
    assert "secret" not in json.dumps(rows)


def test_health_cache_coalesces_and_recovers(tmp_path, monkeypatch):
    monkeypatch.setattr(tdx_lan, "HEALTH_DIR", tmp_path)
    monkeypatch.setattr(tdx_lan, "settings", lambda: {"base_url": "http://lan", "token": "private-test"})
    clock = [1000]
    monkeypatch.setattr(tdx_lan.time, "time", lambda: clock[0])
    calls = []
    def probe(*a, **k):
        calls.append(1)
        return {"status": "running" if len(calls) > 1 else "offline"}
    monkeypatch.setattr(tdx_lan, "request", probe)
    assert not tdx_lan.available()
    assert not tdx_lan.available()
    assert len(calls) == 1
    clock[0] += 11
    assert tdx_lan.available()
    assert tdx_lan.available()
    assert len(calls) == 2
    assert all("private-test" not in f.read_text() for f in tmp_path.glob("*.json"))


@pytest.mark.parametrize("value", ["NaN", "inf", "-inf", float("inf")])
def test_nonfinite_numbers_are_missing(value):
    assert common.to_float(value) is None
    assert tencent._f([value], 0) is None


def test_transport_timeout_never_expands_shorter_source_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(data_service, "CONFIG_PATH", tmp_path/"absent.json")
    assert data_service.request_timeout(60) == (3, 30)
    assert data_service.request_timeout(2) == (2, 2)
    assert data_service.request_timeout((1, 10)) == (1, 10)
    assert data_service.request_timeout(60, scalar=True) == 30


@pytest.mark.parametrize("payload", [{"rc":1,"data":{"pool":[1]}}, {"data":{"pool":"bad"}}, {"data":{"pool":[]}}, {"data":{"pool":[1],"qdate":"20261103"}}])
def test_invalid_or_older_session_pool_cannot_be_archived(payload):
    assert not common._valid_review_pool(payload,{"date":"20261104"})
