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
        with patch.object(tdx_lan,"request",return_value=wire):
            rows, raw, source, _ = tdx_lan.kline("600519","SH",None,250,3,{})
        self.assertEqual(rows[0], ["2026-11-02",1,2,3,1,42,9])
        self.assertEqual(source,"tdx-lan")
        self.assertEqual(raw["kind"],"extracted")

    def test_shared_cache_reuses_success(self):
        r=requests.Response();r.status_code=200;r._content=b'{"rc":0,"data":{"pool":[{"c":"600519"}]}}';r.url="https://push2ex.eastmoney.com/getYesterdayZTPool"
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[5] / ".local") as folder, patch.object(common.tempfile,"gettempdir",return_value=folder), patch.object(common,"_em_get_uncached",return_value=r) as fetch:
            a=common.em_get(r.url,params={"date":"20261102"})
            b=common.em_get(r.url,params={"date":"20261102"})
            self.assertEqual(a.content,b.content)
            self.assertEqual(fetch.call_count,1)
            common.em_get(r.url,params={"date":"20261030"})
            self.assertEqual(fetch.call_count,2)

    def test_empty_not_cached(self):
        r=requests.Response();r.status_code=200;r._content=b'{"rc":0,"data":{"pool":[]}}';r.url="https://push2ex.eastmoney.com/getTopicZTPool"
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[5] / ".local") as folder, patch.object(common.tempfile,"gettempdir",return_value=folder), patch.object(common,"_em_get_uncached",return_value=r) as fetch:
            common.em_get(r.url);common.em_get(r.url)
            self.assertEqual(fetch.call_count,2)

    def test_expired_cache_refetches(self):
        r=requests.Response();r.status_code=200;r._content=b'{"rc":0,"data":{"pool":[1]}}';r.url="https://push2ex.eastmoney.com/getTopicZTPool"
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[5] / ".local") as folder, patch.object(common.tempfile,"gettempdir",return_value=folder), patch.object(common,"_em_get_uncached",return_value=r) as fetch:
            common.em_get(r.url)
            with patch.object(common.time,"time",return_value=common.time.time()+61): common.em_get(r.url)
            self.assertEqual(fetch.call_count,2)

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
