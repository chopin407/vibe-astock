import assert from "node:assert/strict";
import { test } from "node:test";
import { confirmDirections, type MainlineSnapshot } from "../src/finance/mainline.ts";
import { evaluatePlan, type DirectionPlan } from "../src/finance/mainline_followup.ts";

const snapshot = (stamp: string): MainlineSnapshot => ({ id: stamp, cached: false, generated_at: "2026-11-06T01:40:00Z", status: "ok", confirmation: "pending", evidence: [], source_out_dir: "", input_refs: [],
  data: { schema_version: 1, algorithm_version: "industry-v1", mode: "intraday", date: "2026-11-06", previous_date: "2026-11-05", observed_at: "2026-11-06T09:40:00+08:00", time_basis: "exchange_quotes", membership_version: "v1", settled: false, scope: "", gaps: [], industry_available: true, industry_reason: "", coverage: [],
    directions: [{ id: "T0101", tag: "煤炭", limit_up: 0, first_boards: 0, previous: 0, continuation: null, broken_rate: null, series: [], checks: { active: true, persistent: true, expanded: null, divergent: null, absent: null },
      quote_times: { min: stamp, max: stamp }, metrics: { coverage: 1, median_pct: 1, up_share: 1, benchmark_pct: 0, index_relative: [] }, members: [{ code: "600001", name: "", role: "", observation_date: "2026-11-06", close: 1, ret: 1, amount: 1, turnover: 1 }] }] } });

test("严格确认要求时间推进、同一成员版本、无重放、不跨午休", () => {
  const a = snapshot("20261106093500"), b = snapshot("20261106094000");
  assert.equal(confirmDirections(b, [a], new Date("2026-11-06T01:40:30Z"))[0].state, "confirmed");
  assert.equal(confirmDirections(b, [b], new Date("2026-11-06T01:40:30Z"))[0].state, "pending");
  assert.equal(confirmDirections({ ...b, cached: true }, [a], new Date("2026-11-06T01:40:30Z"))[0].state, "pending");
  const changed = structuredClone(b); changed.data.membership_version = "v2";
  assert.equal(confirmDirections(changed, [a], new Date("2026-11-06T01:40:30Z"))[0].state, "pending");
  const afternoon = snapshot("20261106130500"), morning = snapshot("20261106113000");
  assert.equal(confirmDirections(afternoon, [morning], new Date("2026-11-06T05:05:30Z"))[0].state, "pending");
  assert.equal(confirmDirections(b, [a], new Date("2026-11-06T01:42:00Z"))[0].state, "unverified");
});

test("独立验证拒绝事后条件、隔日缺口、未知方向和版本漂移", () => {
  const base = snapshot("base"); base.data.mode = "close"; base.data.settled = true; base.data.date = "2026-11-05"; base.generated_at = "2026-11-05T08:00:00Z";
  const target = snapshot("target"); target.data.mode = "close"; target.data.settled = true;
  const plan: DirectionPlan = { id: "p1", snapshot_id: "base", direction_id: "T0101", metric: "persistent", expected: true, created_at: "2026-11-05T09:00:00Z" };
  assert.equal(evaluatePlan(plan, base, target).state, "met");
  assert.equal(evaluatePlan({ ...plan, expected: false }, base, target).state, "unmet");
  assert.equal(evaluatePlan({ ...plan, created_at: "2026-11-06T01:15:00Z" }, base, target).state, "posthoc");
  assert.equal(evaluatePlan({ ...plan, direction_id: "missing" }, base, target).state, "missing");
  const changed = structuredClone(target); changed.data.membership_version = "v2";
  assert.equal(evaluatePlan(plan, base, changed).state, "missing");
  changed.data.previous_date = "2026-11-04";
  assert.equal(evaluatePlan(plan, base, changed).state, "missing");
  assert.equal(evaluatePlan(plan, base, null).state, "pending");
});
