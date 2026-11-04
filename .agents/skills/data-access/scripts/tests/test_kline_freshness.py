"""The real source mapper must emit dated volume, not just a last-bar date."""
import sys
from pathlib import Path

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fetch_kline


@pytest.mark.parametrize("volume", [0, 123.5])
def test_mapper_preserves_dated_volume(monkeypatch, volume):
    from sources import tdx_lan
    monkeypatch.setattr(tdx_lan, "settings", lambda: {"base_url": ""})
    monkeypatch.setattr(sys, "argv", ["fetch_kline.py", "--symbol", "300308"])
    row = ["2026-09-04", "10", "10", "10", "10", str(volume)]
    monkeypatch.setattr(fetch_kline, "src_tencent", lambda *a: ([row], {"raw_ref": "raw/kline.json"}, "tencent", "fixture"))
    output = {}
    monkeypatch.setattr(fetch_kline, "finish", lambda res, _: output.update(res))
    fetch_kline.main()
    evidence = next(e for e in output["evidence"] if e["field"] == "volume_latest")
    assert evidence["value"] == volume
    assert evidence["period"] == "2026-09-04"
    assert evidence["raw_ref"] == "raw/kline.json"


def test_bad_local_config_is_reported_and_public_source_still_runs(monkeypatch):
    from sources import tdx_lan
    def bad_config():
        raise ValueError("配置无效")
    monkeypatch.setattr(tdx_lan, "settings", bad_config)
    monkeypatch.setattr(sys, "argv", ["fetch_kline.py", "--symbol", "300308"])
    row = ["2026-09-04", "10", "10", "10", "10", "42"]
    monkeypatch.setattr(fetch_kline, "src_tencent", lambda *a: ([row], {"raw_ref":"raw/kline.json"}, "tencent", "fixture"))
    output = {}
    monkeypatch.setattr(fetch_kline, "finish", lambda res, _: output.update(res))
    fetch_kline.main()
    assert output["status"] == "partial"
    assert output["primary_source"] == "tencent"
    assert output["errors"][0]["source"] == "tdx-lan"
