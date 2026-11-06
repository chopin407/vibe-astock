import assert from "node:assert/strict";
import { test } from "node:test";
import { withRenderer, textOf } from "./helpers/render.ts";

test("方向观察显示缺口、共存状态、全部成员与快照候选入口", async () => {
  await withRenderer(async r => {
    const { MainlineResult } = await r.load("/src/verticals/finance/components/MainlinePanel.tsx");
    const html = r.html(MainlineResult, { snapshot: { id: "version-1", cached: true, data: {
      date: "2026-11-06", mode: "close", observed_at: "2026-11-06 16:00", scope: "事件样本", coverage: [{ date: "2026-11-06", covered: 3, total: 5 }],
      industry_reason: "成分尚未验证", gaps: ["缺少两只归因"], directions: [{ id: "tag-1", tag: "算力", limit_up: 3, first_boards: 2, previous: 3, continuation: .5, broken_rate: null, series: [1, 2, 3],
        checks: { active: true, persistent: true, expanded: true, divergent: null, absent: false },
        members: Array.from({ length: 12 }, (_, i) => ({ code: String(600000+i), name: `样本${i}`, role: "今日首板", observation_date: "2026-11-06", ret: 10 })) }] } } });
    const text = textOf(html);
    assert.match(text, /持续活跃：满足/);
    assert.match(text, /分歧明显：缺数据/);
    assert.match(text, /本快照未含行业通道/);
    assert.match(text, /样本11/);
    assert.match(text, /缺少两只归因/);
    assert.match(html, /snapshot_id=version-1/);
    assert.match(html, /direction_id=tag-1/);
  });
});

test("补充源空表说明和事后验证状态如实显示", async () => {
  await withRenderer(async r => {
    const { SupplementResult, VerificationResults } = await r.load("/src/verticals/finance/components/MainlineTools.tsx");
    const supplement = textOf(r.html(SupplementResult, { record: { results: [{ kind: "data", status: "partial", result: { note: "没有结构化表格，未用于计算", tables: [] } }, { kind: "news", status: "ok", result: { articles: [{ title: "公司公告", url: "https://example.org/report", published_at: "2026-11-06", source: "公告" }] } }] } }));
    assert.match(supplement, /没有结构化表格/);
    assert.match(supplement, /公司公告/);
    const verification = textOf(r.html(VerificationResults, { plans: [{ id: "p1", direction: "煤炭", metric: "persistent", expected: true, result: { state: "posthoc", reason: "09:15之后形成" } }] }));
    assert.match(verification, /事后记录/);
    assert.doesNotMatch(verification, /满足预期/);
  });
});
