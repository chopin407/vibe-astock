import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { refreshMainline, loadMainline, mainlineView, type MainlineData } from "../src/finance/mainline.ts";
import { directionCandidates } from "../src/finance/candidates.ts";
import type { fetchEndpoint, ServiceContext } from "../src/service.ts";

const data: MainlineData = { schema_version: 1, algorithm_version: "event-v1", date: "2026-11-06", mode: "close", observed_at: "2026-11-06T16:00:00+08:00", settled: true,
  scope: "事件样本", time_basis: "fetched_only", gaps: [], industry_available: false, industry_reason: "未启用",
  coverage: [{ date: "2026-11-06", available: true, covered: 1, total: 1, complete: true }],
  directions: [{ id: "abcdef", tag: "算力", limit_up: 1, first_boards: 1, previous: 1, continuation: 1, broken_rate: null, series: [1, 1, 1],
    checks: { active: false, persistent: false, expanded: false, divergent: null, absent: false },
    members: [{ code: "600001", name: "测试", role: "今日首板", observation_date: "2026-11-06", close: 10, ret: 10, amount: 2e8, turnover: 5 },
      { code: "600002", name: "昨日", role: "昨日样本", observation_date: "2026-11-05", close: 9, ret: 10, amount: 3e8, turnover: 9 }] }] };

test("归档不可覆盖，GET 不写盘，历史候选不拿昨天成交额冒充今天", async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "mainline-"));
  const ctx: ServiceContext = { dataRoot: root, repoRoot: root, python: "python", node: process.execPath };
  try {
    const empty = await mainlineView(ctx, {});
    assert.equal(empty.snapshot, null);
    assert.equal(fs.existsSync(path.join(root, "mainline")), false);
    const fetch = (async () => ({ envelope: { status: "ok", extra: { result: data }, evidence: [{ id: "ev-1" }] }, out_dir: "fetch/run", cached: false })) as unknown as typeof fetchEndpoint;
    const a = await refreshMainline(ctx, { date: data.date }, new AbortController().signal, fetch, new Date("2026-11-06T08:00:00Z"));
    const b = await refreshMainline(ctx, { date: data.date }, new AbortController().signal, fetch, new Date("2026-11-06T08:01:00Z"));
    assert.notEqual(a.id, b.id);
    assert.equal((await mainlineView(ctx, {})).history.length, 2);
    assert.deepEqual(loadMainline(ctx, a.id), a);
    assert.throws(() => loadMainline(ctx, "../secret"));
    const c = directionCandidates(ctx, { snapshot_id: a.id, direction_id: "abcdef", amount_min: "1" });
    assert.deepEqual(c.rows.map(r => r.verdict), ["met", "missing"]);
    assert.equal(c.rows[0].checks[0].value, 2);
    const bad = (async () => ({ envelope: { status: "failed" } })) as unknown as typeof fetchEndpoint;
    await assert.rejects(refreshMainline(ctx, {}, new AbortController().signal, bad));
    assert.equal((await mainlineView(ctx, {})).history.length, 2);
    assert.equal(a.confirmation, "unverified_time");
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});

test("未来日期、历史盘中、午休不得更新；取消不能归档", async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "mainline-"));
  const ctx = { dataRoot: root } as ServiceContext;
  try {
    const never = (async () => { throw Error("unexpected fetch"); }) as typeof fetchEndpoint;
    const signal = new AbortController().signal;
    const now = new Date("2026-11-06T04:00:00Z");
    await assert.rejects(refreshMainline(ctx, { date: "2030-01-01" }, signal, never, now), /尚未/);
    await assert.rejects(refreshMainline(ctx, { mode: "intraday" }, signal, never, now), /连续竞价/);
    const c = new AbortController(); c.abort(Error("cancelled"));
    const fake = (async () => ({ envelope: { extra: { result: data } } })) as unknown as typeof fetchEndpoint;
    await assert.rejects(refreshMainline(ctx, {}, c.signal, fake, now), /cancelled/);
    assert.equal(fs.existsSync(path.join(root, "mainline")), false);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});
