"""Batch quote routing shared by pages, monitoring and endpoint consumers.

Tencent provides verified quote times and valuation fields. TDX can recover
missing CN prices, but cannot attest exchange quote time or replace valuations.
"""
from data_service import attempt
from sources import tencent, tdx_lan
from sources._http import last_raw_ref


def quotes(codes):
    if isinstance(codes, str):
        codes = [x.strip() for x in codes.split(",") if x.strip()]
    codes = list(dict.fromkeys(codes))
    result = {}
    try:
        with attempt("tencent", "quotes"):
            result = tencent.tencent_quotes(codes)
            ref = last_raw_ref()
            for row in result.values():
                row.update(source="tencent", _raw=ref)
    except Exception:
        pass
    missing = [c for c in codes if c not in result or result[c].get("price") is None]
    cn = [c for c in missing if tencent.tencent_prefix(c).startswith(("sh", "sz", "bj"))]
    if cn and tdx_lan.available():
        try:
            with attempt("tdx-lan", "quotes"):
                # Replace entire rows: timestamps/valuation must never be mixed
                # with a different source's prices.
                result.update(tdx_lan.quotes(cn))
        except Exception:
            pass
    if not result:
        raise RuntimeError("批量行情所有可用数据源均未取得报价")
    return result


def quote(code):
    return quotes([code])
