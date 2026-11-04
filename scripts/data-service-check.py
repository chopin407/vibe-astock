#!/usr/bin/env python3
"""Read-only registry contract checks and optional local TDX route probes."""
from __future__ import annotations

import argparse
import importlib
import inspect
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".agents/skills/data-access/scripts"))
from core.stdio_utf8 import force_utf8_stdio
from data_service import settings


def check_registry():
    endpoints = json.loads((ROOT / "datasources/registry.json").read_text(encoding="utf-8"))["endpoints"]
    issues = []
    seen = set()
    for ep in endpoints:
        name = ep["id"]
        if name in seen:
            issues.append({"endpoint": name, "error": "duplicate_id"})
        seen.add(name)
        try:
            if ep["module"] == "legacy":
                if not (ROOT / ".agents/skills/data-access/scripts" / ep["function"]).is_file():
                    raise ValueError("missing_script")
                continue
            fn = getattr(importlib.import_module("sources." + ep["module"]), ep["function"])
            mapper = getattr(importlib.import_module("sources." + ep.get("mapper_module", "mappers")), ep["mapper"])
            if not callable(fn) or not callable(mapper):
                raise ValueError("not_callable")
            args = {k: v for k, v in (ep.get("args") or {}).items() if v is not None}
            if ep.get("symbol_kind", "cn6") != "none":
                args[ep.get("symbol_param", "code")] = "MARKET"
            for flag, arg in (("pass_market", "market"), ("pass_timeout", "timeout"), ("pass_out_dir", "out_dir")):
                if ep.get(flag):
                    args[arg] = None
            inspect.signature(fn).bind(**args)
        except Exception as exc:
            issues.append({"endpoint": name, "error": type(exc).__name__})
    return {"endpoint_count": len(endpoints), "modules": dict(Counter(e["module"] for e in endpoints)), "issues": issues}


def main():
    force_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="只读探测已配置 TDX 的健康、报价、指数及前复权日线")
    args = parser.parse_args()
    result = {"registry": check_registry(), "policy": settings(), "live": []}
    if args.live:
        from sources import tdx_lan
        if not tdx_lan.settings()["base_url"]:
            result["live"].append({"source": "tdx-lan", "status": "unconfigured"})
        else:
            for route, params in [("/", {}), ("/quote", {"codes": "sh600519,sh000001"}),
                                  ("/index/day", {"code": "sh000001", "start": 0, "count": 300}),
                                  ("/kline/day/qfq", {"code": "sh600519", "start": 0, "count": 5})]:
                started = time.monotonic()
                row = {"source": "tdx-lan", "route": route}
                try:
                    payload = tdx_lan.request(route, _timeout=60 if "qfq" in route else 8, **params)
                    if route == "/" and (not isinstance(payload, dict) or payload.get("status") != "running"):
                        raise ValueError("not_ready")
                    rows = payload if isinstance(payload, list) else payload.get("List", []) if isinstance(payload, dict) else []
                    if route != "/" and not rows:
                        raise ValueError("empty_response")
                    row.update(status="ok", rows=len(rows))
                except Exception as exc:
                    row.update(status="failed", error=type(exc).__name__)
                row["duration_ms"] = round((time.monotonic() - started) * 1000)
                result["live"].append(row)
                if route == "/" and row["status"] != "ok":
                    break
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(bool(result["registry"]["issues"]) or any(r["status"] == "failed" for r in result["live"]))


if __name__ == "__main__":
    raise SystemExit(main())
