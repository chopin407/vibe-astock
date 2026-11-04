import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import requests
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common
from sources import tdx_lan

class TdxTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[5] / ".local")
        self.addCleanup(folder.cleanup)
        health=patch.object(tdx_lan,"HEALTH_DIR",Path(folder.name)/"health")
        health.start()
        self.addCleanup(health.stop)

    def test_units_and_bare_exchange_code(self):
        wire = [{"Code":"600519", "Exchange":1,"Kline":{"Close":1439100,"Last":1392050,"Amount":11849257984000,"Time":"2026-11-02T21:00:00"}}]
        with patch.object(tdx_lan, "request", return_value=wire):
            q = tdx_lan.quotes(["600519"])["600519"]
        self.assertEqual(q["price"],1439.1)
        self.assertEqual(q["amount_wan"],1184925.7984)
        self.assertIsNone(q["quote_time"])
        self.assertIsNone(q["open"])

    def test_empty_is_failure(self):
        with patch.object(tdx_lan,"request",return_value=[]):
            with self.assertRaises(ValueError): tdx_lan.quotes(["600519"])

    def test_kline_legacy_sequence(self):
        wire={"List":[{"Time":"2026-11-02T00:00:00","Open":1000,"Close":2000,"High":3000,"Low":1000,"Volume":42,"Amount":9000}]}
        with patch.object(tdx_lan,"available",return_value=True), patch.object(tdx_lan,"request",return_value=wire):
            rows, raw, source, _ = tdx_lan.kline("600519","SH",None,250,3,{})
        self.assertEqual(rows[0], ["2026-11-02",1,2,3,1,42,9])
        self.assertEqual(source,"tdx-lan")
        self.assertEqual(raw["kind"],"extracted")

    def test_shared_cache_reuses_success(self):
        r=requests.Response();r.status_code=200;r._content=b'{"rc":0,"data":{"pool":[{"c":"600519"}]}}';r.url="https://push2ex.eastmoney.com/getYesterdayZTPool"
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[5] / ".local") as folder, patch.object(common.tempfile,"gettempdir",return_value=folder), patch.object(common,"REVIEW_POOL_CACHE",Path(folder)/"archive"), patch.object(common,"_em_get_uncached",return_value=r) as fetch:
            a=common.em_get(r.url,params={"date":"20261102"})
            b=common.em_get(r.url,params={"date":"20261102"})
            self.assertEqual(a.content,b.content)
            self.assertEqual(fetch.call_count,1)
            common.em_get(r.url,params={"date":"20261030"})
            self.assertEqual(fetch.call_count,2)

    def test_empty_not_cached(self):
        r=requests.Response();r.status_code=200;r._content=b'{"rc":0,"data":{"pool":[]}}';r.url="https://push2ex.eastmoney.com/getTopicZTPool"
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[5] / ".local") as folder, patch.object(common.tempfile,"gettempdir",return_value=folder), patch.object(common,"REVIEW_POOL_CACHE",Path(folder)/"archive"), patch.object(common,"_em_get_uncached",return_value=r) as fetch:
            common.em_get(r.url);common.em_get(r.url)
            self.assertEqual(fetch.call_count,2)

    def test_expired_cache_refetches(self):
        r=requests.Response();r.status_code=200;r._content=b'{"rc":0,"data":{"pool":[1]}}';r.url="https://push2ex.eastmoney.com/getTopicZTPool"
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[5] / ".local") as folder, patch.object(common.tempfile,"gettempdir",return_value=folder), patch.object(common,"REVIEW_POOL_CACHE",Path(folder)/"archive"), patch.object(common,"_em_get_uncached",return_value=r) as fetch:
            common.em_get(r.url)
            with patch.object(common.time,"time",return_value=common.time.time()+61): common.em_get(r.url)
            self.assertEqual(fetch.call_count,2)

    def test_settled_archive_survives_restart_and_live_ttl(self):
        r=requests.Response();r.status_code=200;r._content=b'{"rc":0,"data":{"pool":[1]}}';r.url="https://push2ex.eastmoney.com/getTopicZTPool"
        at=common.datetime(2026,11,2,17,tzinfo=common.TZ_SH).timestamp()
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[5] / ".local") as folder, patch.object(common,"REVIEW_POOL_CACHE",Path(folder)), patch.object(common,"_em_get_uncached",return_value=r) as fetch:
            with patch.object(common.time,"time",return_value=at):
                common.em_get(r.url,params={"date":"20261102"})
            with patch.object(common.time,"time",return_value=at+86400):
                self.assertEqual(common.em_get(r.url,params={"date":"20261102"}).content,r.content)
            self.assertEqual(fetch.call_count,1)

    def test_preclose_response_is_not_promoted_to_archive(self):
        r=requests.Response();r.status_code=200;r._content=b'{"rc":0,"data":{"pool":[1]}}';r.url="https://push2ex.eastmoney.com/getTopicZTPool"
        at=common.datetime(2026,11,2,16,29,tzinfo=common.TZ_SH).timestamp()
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[5] / ".local") as folder, patch.object(common.tempfile,"gettempdir",return_value=folder), patch.object(common,"REVIEW_POOL_CACHE",Path(folder)/"archive"), patch.object(common,"_em_get_uncached",return_value=r) as fetch:
            with patch.object(common.time,"time",return_value=at):
                common.em_get(r.url,params={"date":"20261102"})
                self.assertFalse(common.REVIEW_POOL_CACHE.exists())
            with patch.object(common.time,"time",return_value=at+61):
                common.em_get(r.url,params={"date":"20261102"})
                self.assertTrue(common.REVIEW_POOL_CACHE.exists())
            self.assertEqual(fetch.call_count,2)

    def test_settlement_boundary_and_invalid_dates(self):
        at=common.datetime(2026,11,2,16,30,tzinfo=common.TZ_SH).timestamp()
        self.assertFalse(common._review_pool_settled({"date":"20261102"},at-1))
        self.assertTrue(common._review_pool_settled({"date":"20261102"},at))
        for date in ("20261103", "20260230", "", "2026-11-02"):
            self.assertFalse(common._review_pool_settled({"date":date},at))

    def test_index_wire_units_and_missing_price(self):
        wire={"List":[{"Time":"2026-11-04T15:00:00+08:00","Close":3605730,"Amount":852239646720000}]}
        with patch.object(tdx_lan,"request",return_value=wire):
            rows=tdx_lan.index_daily("sh000001",300)
        self.assertEqual(rows[0]["close"],3605.73)
        self.assertEqual(rows[0]["amount"],852239646720)
        with patch.object(tdx_lan,"request",return_value={"List":[{"Time":"2026-11-04"}]}):
            with self.assertRaises(ValueError): tdx_lan.index_daily("sh000001",300)

    def test_trend_prefers_tdx_reuses_sh_and_respects_end(self):
        from sources import eastmoney
        rows=[{"date":"2026-11-03","close":100,"amount":200,"_raw":None},
              {"date":"2026-11-04","close":101,"amount":300,"_raw":None}]
        with patch.object(tdx_lan,"settings",return_value={"base_url":"http://test"}), patch.object(tdx_lan,"request",return_value={"status":"running"}), patch.object(tdx_lan,"index_daily",return_value=rows) as fetch, patch.object(eastmoney,"_index_daily",side_effect=AssertionError("不应请求公网")):
            result=eastmoney.market_index_trend(end="2026-11-03")
        self.assertEqual(len(result["indices"]),8)
        self.assertTrue(all(x["source"]=="tdx-lan" for x in result["indices"]))
        self.assertEqual(result["amount_rows"][0]["total"],400)
        self.assertEqual(len(result["amount_rows"]),1)
        self.assertEqual(fetch.call_count,9)
        self.assertIn("bj899050",[x.args[0] for x in fetch.call_args_list])

    def test_trend_health_failure_falls_back_without_repeated_lan_calls(self):
        from sources import eastmoney, astock_ported
        rows=[{"date":"2026-11-04","close":100,"amount":200,"_raw":None}]
        with patch.object(tdx_lan,"settings",return_value={"base_url":"http://test"}), patch.object(tdx_lan,"request",side_effect=ConnectionError) as health, patch.object(tdx_lan,"index_daily") as local, patch.object(astock_ported,"tencent_kline",side_effect=RuntimeError), patch.object(eastmoney,"_index_daily",return_value=rows):
            result=eastmoney.market_index_trend(end="2026-11-04")
        self.assertEqual(health.call_count,1)
        local.assert_not_called()
        self.assertEqual(len(result["indices"]),8)
        self.assertEqual(result["amount_rows"][0]["source"],"eastmoney")

    def test_one_lan_index_failure_does_not_discard_other_indices(self):
        from sources import eastmoney, astock_ported
        rows=[{"date":"2026-11-04","close":100,"amount":200,"_raw":None}]
        def local(code, count):
            if code=="sz399001": raise ValueError("缺失")
            return rows
        with patch.object(tdx_lan,"settings",return_value={"base_url":"http://test"}), patch.object(tdx_lan,"request",return_value={"status":"running"}), patch.object(tdx_lan,"index_daily",side_effect=local), patch.object(astock_ported,"tencent_kline",side_effect=RuntimeError), patch.object(eastmoney,"_index_daily",return_value=rows):
            result=eastmoney.market_index_trend(end="2026-11-04")
        self.assertEqual(sum(x["source"]=="tdx-lan" for x in result["indices"]),7)
        self.assertEqual(result["failed"],[])

    def test_disable_cache(self):
        with patch.dict(common.os.environ,{"VRA_REVIEW_CACHE":"0"}), patch.object(common,"_em_get_uncached") as fetch:
            common.em_get("https://push2ex.eastmoney.com/getTopicZTPool")
            self.assertEqual(fetch.call_count,1)

    def test_file_settings_and_environment_precedence(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[5] / ".local") as folder:
            config=Path(folder)/"tdx.json"
            config.write_text('{"base_url":"http://lan:8080/","token":"example"}',encoding="utf-8")
            with patch.object(tdx_lan,"CONFIG_PATH",config), patch.dict(tdx_lan.os.environ,{},clear=True):
                self.assertEqual(tdx_lan.settings(),{"base_url":"http://lan:8080","token":"example"})
                with patch.dict(tdx_lan.os.environ,{"VRA_TDX_BASE_URL":""}):
                    self.assertEqual(tdx_lan.settings()["base_url"],"")

    def test_missing_config_is_optional(self):
        with patch.object(tdx_lan,"CONFIG_PATH",Path("nonexistent-config.json")), patch.dict(tdx_lan.os.environ,{},clear=True):
            self.assertEqual(tdx_lan.settings(),{"base_url":"","token":""})

if __name__ == "__main__": unittest.main()
