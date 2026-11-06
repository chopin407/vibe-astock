/** 方向补充与独立验证；不读私人台账，也不改原市场验证战绩。 */
import fs from "node:fs";
import { randomUUID } from "node:crypto";
import { fetchEndpoint, safePath, ServiceError, type ServiceContext } from "../service.ts";
import { loadMainline, mainlineHistory, type MainlineSnapshot } from "./mainline.ts";

export interface Supplement { id: string; snapshot_id: string; direction_id: string; created_at: string; results: { kind: string; status: string; result?: unknown; out_dir?: string; reason?: string }[] }
function dir(ctx: Pick<ServiceContext, "dataRoot">, name: string) { return safePath(ctx, name); }
function save(ctx: Pick<ServiceContext, "dataRoot">, name: string, record: { id: string }) {
  fs.mkdirSync(dir(ctx, name), { recursive: true });
  fs.writeFileSync(safePath(ctx, name, record.id + ".json"), JSON.stringify(record), { encoding: "utf8", flag: "wx" });
}
function records(ctx: Pick<ServiceContext, "dataRoot">, name: string): any[] {
  if (!fs.existsSync(dir(ctx, name))) return [];
  return fs.readdirSync(dir(ctx, name)).filter(f => /^[a-f0-9-]{36}\.json$/.test(f)).flatMap(f => {
    try { return [JSON.parse(fs.readFileSync(safePath(ctx, name, f), "utf8"))]; } catch { return []; }
  }).filter(r => r && typeof r.id === "string" && typeof r.created_at === "string").sort((a, b) => b.created_at.localeCompare(a.created_at));
}
export async function supplementView(ctx: ServiceContext, query: Record<string, string>) {
  return records(ctx, "mainline-supplements").filter(r => !query.snapshot_id || r.snapshot_id === query.snapshot_id).slice(0, 30);
}
export async function supplementAction(ctx: ServiceContext, body: Record<string, unknown>, signal: AbortSignal): Promise<Supplement> {
  const snapshot = loadMainline(ctx, String(body.snapshot_id ?? ""));
  const direction = snapshot.data.directions.find(d => d.id === body.direction_id);
  if (!direction) throw new ServiceError("bad_query", "方向不存在");
  const record: Supplement = { id: randomUUID(), snapshot_id: snapshot.id, direction_id: direction.id, created_at: new Date().toISOString(), results: [] };
  for (const kind of ["data", "news"]) {
    try {
      const r = await fetchEndpoint(ctx, { endpoint: `mx_direction_${kind}`, args: { topic: direction.tag, date: snapshot.data.date, ...(kind === "data" ? { codes: direction.members.slice(0, 3).map(m => m.code) } : {}) }, session: `mx-${randomUUID()}`, timeout_ms: kind === "data" ? 60_000 : 30_000, signal });
      const e = r.envelope as { status?: string; extra?: { result?: unknown } };
      record.results.push({ kind, status: e.status ?? "failed", result: e.extra?.result, out_dir: r.out_dir, ...(!e.extra?.result ? { reason: "补充接口未返回有效结构，请检查凭据、额度、请求范围和网络" } : {}) });
    } catch {
      signal.throwIfAborted();
      record.results.push({ kind, status: "failed", reason: "补充源不可用，请检查妙想凭据、额度和网络；原观察保留" });
    }
  }
  signal.throwIfAborted();
  save(ctx, "mainline-supplements", record);
  return record;
}

export interface DirectionPlan { id: string; snapshot_id: string; direction_id: string; metric: "active" | "persistent"; expected: boolean; created_at: string }
export function evaluatePlan(plan: DirectionPlan, baseline: MainlineSnapshot, target: MainlineSnapshot | null) {
  if (!target) return { state: "pending", reason: "尚无下一个交易日收盘观察" };
  if (target.data.mode !== "close" || !target.data.settled || target.data.previous_date !== baseline.data.date) return { state: "missing", reason: "必须是相邻交易日的收盘观察" };
  if (!Number.isFinite(Date.parse(plan.created_at)) || !Number.isFinite(Date.parse(baseline.generated_at)) || Date.parse(plan.created_at) >= Date.parse(`${target.data.date}T09:15:00+08:00`) || Date.parse(baseline.generated_at) >= Date.parse(`${target.data.date}T09:15:00+08:00`)) return { state: "posthoc", reason: "计划或基准时间无效，或在下一交易日09:15之后形成，不计入验证" };
  if (baseline.data.algorithm_version !== target.data.algorithm_version || (baseline.data.membership_version && baseline.data.industry_available && baseline.data.membership_version !== target.data.membership_version)) return { state: "missing", reason: "算法或行业成员版本变化，不能直接比较" };
  const actual = target.data.directions.find(d => d.id === plan.direction_id)?.checks[plan.metric];
  if (actual == null) return { state: "missing", reason: "该方向目标读数缺失，不能当成不活跃" };
  return { state: actual === plan.expected ? "met" : "unmet", actual, target_id: target.id, reason: "固定基准与预先记录条件，按下一交易日收盘观察核对" };
}
export async function verificationView(ctx: ServiceContext) {
  const history = mainlineHistory(ctx, undefined, "close").map(h => loadMainline(ctx, h.id));
  return records(ctx, "mainline-plans").map((p: DirectionPlan) => {
    try {
      const baseline = loadMainline(ctx, p.snapshot_id);
      const target = history.find(h => h.data.previous_date === baseline.data.date && h.data.algorithm_version === baseline.data.algorithm_version && (!baseline.data.industry_available || h.data.directions.some(d => d.id === p.direction_id))) ?? null;
      return { ...p, direction: baseline.data.directions.find(d => d.id === p.direction_id)?.tag, result: evaluatePlan(p, baseline, target) };
    } catch { return { ...p, result: { state: "missing", reason: "基准快照不可读" } }; }
  });
}
export async function verificationAction(ctx: ServiceContext, body: Record<string, unknown>) {
  const baseline = loadMainline(ctx, String(body.snapshot_id ?? ""));
  const metric = body.metric ?? "persistent";
  if (baseline.data.mode !== "close" || !baseline.data.settled || !baseline.data.directions.some(d => d.id === body.direction_id) || !["active", "persistent"].includes(String(metric)) || typeof body.expected !== "boolean") throw new ServiceError("bad_query", "请选择有效收盘方向、指标和预期布尔值");
  const record: DirectionPlan = { id: randomUUID(), snapshot_id: baseline.id, direction_id: String(body.direction_id), metric: metric as DirectionPlan["metric"], expected: body.expected, created_at: new Date().toISOString() };
  save(ctx, "mainline-plans", record);
  return record;
}
