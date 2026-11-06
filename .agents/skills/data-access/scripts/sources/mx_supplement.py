"""受控妙想补充源：保留表格/原始文章，不用生成摘要替代指标或成员全表。"""
from __future__ import annotations

import os
import re
from urllib.parse import urlparse
from sources import shortline as S
from sources._http import http_post_json
from sources.mappers_shortline import _Acc

BASE = "https://mkapi2.dfcfs.com/finskillshub/api/claw/"


def request(route: str, payload: dict) -> dict:
    key = os.environ.get("MX_APIKEY", "").strip()
    if not key:
        raise ValueError("妙想未配置 MX_APIKEY")
    result = http_post_json(BASE + route, json_body=payload, headers={"apikey": key}, timeout=25)
    node = result
    for _ in range(5):
        if not isinstance(node, dict):
            raise ValueError("妙想响应结构无效")
        if node.get("success") is False or node.get("status", 0) not in (0, "0", None) or node.get("code", 0) not in (0, "0", None):
            raise ValueError("妙想返回失败或配额不足")
        if "searchDataResultDTO" in node:
            return node["searchDataResultDTO"]
        if "llmSearchResponse" in node or "dataTableDTOList" in node:
            return node
        if isinstance(node.get("data"), dict):
            node = node["data"]
        else:
            return node
    raise ValueError("妙想响应层级异常")


def validate(topic: str, date: str | None) -> str:
    if not isinstance(topic, str) or not re.fullmatch(r"[\w\u4e00-\u9fff+（）()· .-]{1,60}", topic):
        raise ValueError("方向名称无效")
    return S.review_day(date)


def data(topic: str, date: str | None = None, codes: list[str] | None = None) -> dict:
    day = validate(topic, date)
    if codes is not None and (not isinstance(codes, list) or len(codes) > 3 or any(not isinstance(c, str) or not re.fullmatch(r"\d{6}", c) for c in codes)):
        raise ValueError("个股补充范围最多三只有效A股代码")
    raw = request("query", {"toolQuery": f"截至{day}，{topic}行业或概念关联的A股公司代码、名称、所属板块、主营业务、关联依据和资料日期；返回结构化表格，不提供投资建议"})
    tables = raw.get("dataTableDTOList") or []
    if not isinstance(tables, list):
        tables = []
    tables = [t for t in tables if isinstance(t, dict) and t.get("table")]
    fallback = False
    if not tables and codes:
        raw = request("query", {"toolQuery": f"截至{day}，{'、'.join(codes)}的收盘价、市盈率TTM、所属行业和主营业务，注明资料日期"})
        tables = [t for t in (raw.get("dataTableDTOList") or []) if isinstance(t, dict) and t.get("table")]
        fallback = bool(tables)
    return {"date": day, "settled": True, "topic": topic, "available": bool(tables), "tables": tables,
            "members": [], "complete": False,
            "note": ("方向成员关系未返回结构表，已补取方向内最多三只公开个股的指标；不据此证明方向关系或完整性。" if fallback else "") + ("查询结果保留原表供核验；未证明日期、单位及成员完整性前，不自动并入计算或候选池" if tables else "接口返回成功，但没有结构化表格；未用于关系或数值计算")}


def news(topic: str, date: str | None = None) -> dict:
    day = validate(topic, date)
    raw = request("news-search", {"query": f"截至{day} {topic} 行业政策、公司公告与风险事件；列出原文链接、发布时间与来源"})
    response = raw.get("llmSearchResponse", {})
    if isinstance(response, dict):
        items = response.get("data") or response.get("items") or []
    elif isinstance(response, list):
        items = response
    else:
        items = []
    articles, seen = [], set()
    for row in items:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or row.get("link") or row.get("sourceUrl") or row.get("jumpUrl") or "")
        parsed = urlparse(url)
        title = str(row.get("title") or "").strip()
        stamp = str(row.get("date") or row.get("publishTime") or "")
        match = re.search(r"\d{4}[-/]\d{2}[-/]\d{2}", stamp)
        published = match.group(0).replace("/", "-") if match else None
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or not title or not published or published > day:
            continue
        identity = (parsed.hostname, parsed.path, title)
        if identity in seen:
            continue
        seen.add(identity)
        articles.append({"title": title, "url": url, "published_at": stamp, "source": str(row.get("insName") or parsed.hostname),
                         "kind": row.get("informationType") or "unknown", "content": str(row.get("content") or "")[:12000]})
    return {"date": day, "settled": True, "topic": topic, "available": bool(articles), "articles": articles,
            "note": "检索线索需核对原文；抓取时间不证明历史时点已知，未用于主线数值规则" if articles else "没有同时具备可用链接、标题和截止日前发布时间的结构化文章"}


def map_result(result: dict, ctx: dict) -> dict:
    a = _Acc(ctx, result["date"])
    field = "mx_table_count" if "tables" in result else "mx_article_count"
    a.num(field, len(result.get("tables", result.get("articles", []))), "个", note=result["note"])
    if not result["available"]:
        a.missing.append({"field": field, "period": result["date"], "reason": result["note"]})
    return a.finish(True, {"result": result}, "妙想补充源不可用")
