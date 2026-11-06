/** 方向观察：GET 只读不可变快照，POST 受控取数并归档。 */
import fs from "node:fs";
import { randomUUID } from "node:crypto";
import { fetchEndpoint, safePath, ServiceError, type ServiceContext } from "../service.ts";
import { clockOf } from "./shortline/intraday.ts";
import { validDate } from "./shortline/history.ts";
import { phaseOf } from "./shortline/watch.ts";

export interface DirectionMember {
  code: string; name: string; role: string; observation_date: string;
  close: number | null; ret: number | null; amount: number | null; turnover: number | null;
  quote_time?: string | null; source?: string; valuation?: Record<string, number | null>;
}
export interface MainlineDirection {
  id: string; tag: string; limit_up: number; first_boards: number; previous: number;
  continuation: number | null; broken_rate: number | null; series: (number | null)[];
  checks: Record<"active" | "persistent" | "expanded" | "divergent" | "absent", boolean | null>;
  members: DirectionMember[];
  kind?: "industry";
  quote_times?: { min: string | null; max: string | null };
  metrics?: { coverage: number; median_pct: number | null; up_share: number | null; benchmark_pct: number | null; index_relative: { date: string; relative_pct: number }[] };
}
export interface MainlineData {
  schema_version: number; algorithm_version: string; date: string; mode: "close" | "intraday";
  observed_at: string; settled: boolean; scope: string; time_basis: string;
  directions: MainlineDirection[]; coverage: { date: string; available: boolean; covered: number | null; total: number | null; complete: boolean | null }[];
  gaps: string[]; industry_available: boolean; industry_reason: string;
  previous_date?: string; membership_version?: string;
}
export interface MainlineSnapshot {
  id: string; generated_at: string; status: string; data: MainlineData;
  evidence: unknown[]; source_out_dir: string; cached: boolean;
  confirmation: "unverified_time" | "pending" | "confirmed"; input_refs: string[];
  confirmation_details?: { direction_id: string; state: string; reason: string; previous_id?: string }[];
}
const ID = /^\d{13}-[a-f0-9-]{36}$/;
export function loadMainline(ctx: Pick<ServiceContext, "dataRoot">, id: string): MainlineSnapshot {
  if (!ID.test(id)) throw new ServiceError("bad_query", "快照编号无效");
  const file = safePath(ctx, "mainline", `${id}.json`);
  if (!fs.existsSync(file)) throw new ServiceError("not_found", "观察快照不存在");
  const doc = JSON.parse(fs.readFileSync(file, "utf8")) as MainlineSnapshot;
  if (doc.id !== id || doc.data?.schema_version !== 1 || !Array.isArray(doc.data.directions)) throw new ServiceError("bad_query", "观察快照损坏");
  return doc;
}
export function mainlineHistory(ctx: Pick<ServiceContext, "dataRoot">, date?: string, mode?: string): { id: string; date: string; mode: string; generated_at: string }[] {
  const dir = safePath(ctx, "mainline");
  if (!fs.existsSync(dir)) return [];
  const rows = [];
  for (const file of fs.readdirSync(dir).filter(f => ID.test(f.replace(/\.json$/, "")) && f.endsWith(".json")).sort().reverse()) {
    try {
      const doc = loadMainline(ctx, file.slice(0, -5));
      if ((!date || doc.data.date === date) && (!mode || doc.data.mode === mode)) rows.push({ id: doc.id, date: doc.data.date, mode: doc.data.mode, generated_at: doc.generated_at });
    } catch { /* 损坏记录不作为有效快照；显式读取时报告错误。 */ }
    if (rows.length >= 50) break;
  }
  return rows;
}
export async function mainlineView(ctx: ServiceContext, query: Record<string, string>) {
  if (query.date && !validDate(query.date)) throw new ServiceError("bad_query", "日期无效");
  const history = mainlineHistory(ctx, query.date, query.mode);
  const id = query.snapshot_id || history.find(h => (!query.mode || h.mode === query.mode) && (!query.channel || (loadMainline(ctx, h.id).data.industry_available ? "industry" : "event") === query.channel))?.id;
  return { snapshot: id ? loadMainline(ctx, id) : null, history };
}
type Fetch = typeof fetchEndpoint;
export async function refreshMainline(ctx: ServiceContext, body: Record<string, unknown>, signal: AbortSignal, fetch: Fetch = fetchEndpoint, now = new Date()): Promise<MainlineSnapshot> {
  const mode = body.mode ?? "close";
  if (mode !== "close" && mode !== "intraday") throw new ServiceError("bad_query", "观察模式无效");
  const date = typeof body.date === "string" && body.date ? body.date : undefined;
  const industryId = typeof body.industry_id === "string" ? body.industry_id : undefined;
  if (industryId && !/^T\d{4}$/.test(industryId)) throw new ServiceError("bad_query", "行业标识无效");
  if (date && (!validDate(date) || date > clockOf(now).day)) throw new ServiceError("bad_query", "业务日无效或尚未到来");
  if (mode === "intraday" && (date && date !== clockOf(now).day || !["morning", "afternoon"].includes(phaseOf(now)))) throw new ServiceError("bad_query", "盘中观察仅在今天连续竞价时段更新；历史请读取快照");
  const r = await fetch(ctx, { endpoint: industryId ? "cn_industry_observation" : "cn_mainline", session: `mainline-${randomUUID()}`, timeout_ms: industryId ? 90_000 : 45_000,
    args: { ...(date ? { date } : {}), mode, ...(industryId ? { industry_id: industryId } : {}) }, ...(body.refresh === true ? { consistency: { mode: "fresh" as const } } : {}), signal });
  const env = r.envelope as { status?: string; evidence?: unknown[]; extra?: { result?: MainlineData }; reason?: string };
  const data = env.extra?.result;
  if (signal.aborted) throw signal.reason;
  if (env.status === "failed" || !data || data.schema_version !== 1 || !data.coverage.at(-1)?.available) throw new ServiceError("data_unavailable", "方向输入不可用，保留上次成功观察");
  if ((date && data.date !== date) || data.mode !== mode || (mode === "close" && !data.settled)) throw new ServiceError("data_unavailable", "方向输入的业务日或模式不符");
  const id = `${now.getTime()}-${randomUUID()}`;
  const completedAt = new Date(Math.max(now.getTime(), Number.isFinite(Date.parse(data.observed_at)) ? Date.parse(data.observed_at) : now.getTime()));
  const snapshot: MainlineSnapshot = { id, generated_at: completedAt.toISOString(), status: env.status ?? "partial", data,
    evidence: env.evidence ?? [], source_out_dir: r.out_dir, cached: r.cached,
    confirmation: "unverified_time", input_refs: [r.out_dir] };
  if (mode === "intraday") {
    const previous = mainlineHistory(ctx, data.date).filter(h => h.mode === "intraday").map(h => loadMainline(ctx, h.id));
    snapshot.confirmation_details = confirmDirections(snapshot, previous, new Date(data.observed_at));
    snapshot.confirmation = snapshot.confirmation_details.some(d => d.state === "confirmed") ? "confirmed" : snapshot.confirmation_details.some(d => d.state === "pending") ? "pending" : "unverified_time";
  }
  const dir = safePath(ctx, "mainline");
  fs.mkdirSync(dir, { recursive: true });
  // wx 确保观察版本不可覆盖；只在完整 JSON 形成后写入。
  fs.writeFileSync(safePath(ctx, "mainline", `${id}.json`), JSON.stringify(snapshot), { encoding: "utf8", flag: "wx" });
  return snapshot;
}

function marketStamp(value: string | null | undefined): number {
  if (!value || !/^\d{14}$/.test(value)) return NaN;
  const iso = `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}T${value.slice(8, 10)}:${value.slice(10, 12)}:${value.slice(12)}+08:00`;
  return Date.parse(iso);
}

/** 只确认同一范围的独立交易所时间观察；重放、午休跨段及长时间断线不接续。 */
export function confirmDirections(current: MainlineSnapshot, history: MainlineSnapshot[], now: Date) {
  return current.data.directions.map(d => {
    const start = marketStamp(d.quote_times?.min), end = marketStamp(d.quote_times?.max);
    const eligible = current.data.time_basis === "exchange_quotes" && d.checks.persistent === true && (d.metrics?.coverage ?? 0) >= .9 &&
      Number.isFinite(start) && Number.isFinite(end) && end >= start && end - start <= 30_000 && now.getTime() - start <= 60_000 && end <= now.getTime();
    if (!eligible) return { direction_id: d.id, state: "unverified", reason: "需要持续条件满足、有效行情覆盖≥90%、真实市场时间新鲜且相差≤30秒" };
    const previous = history.find(p => {
      if (p.cached || current.cached || p.data.algorithm_version !== current.data.algorithm_version || p.data.date !== current.data.date || (current.data.industry_available && p.data.membership_version !== current.data.membership_version)) return false;
      const a = p.data.directions.find(x => x.id === d.id);
      const t = marketStamp(a?.quote_times?.min), finish = marketStamp(a?.quote_times?.max);
      return a?.checks.persistent === true && (a.metrics?.coverage ?? 0) >= .9 && Number.isFinite(t) && Number.isFinite(finish) &&
        finish - t <= 30_000 && t <= finish && start - finish >= 300_000 && start - t <= 600_000 &&
        phaseOf(new Date(t)) === phaseOf(new Date(start)) && p.data.time_basis === "exchange_quotes" &&
        a.members.map(m => m.code).sort().join(",") === d.members.map(m => m.code).sort().join(",");
    });
    return { direction_id: d.id, state: previous ? "confirmed" : "pending", reason: previous ? "两次同范围、真实报价时间推进且间隔5–10分钟的持续观察" : "等待同一交易时段内第二次独立有效观察", ...(previous ? { previous_id: previous.id } : {}) };
  });
}

export async function industryCatalog(ctx: ServiceContext, query: Record<string, string>, signal: AbortSignal) {
  const r = await fetchEndpoint(ctx, { endpoint: "cn_industry_catalog", args: { scan: query.scan === "1" }, session: `industry-${randomUUID()}`, timeout_ms: 90_000, signal });
  const env = r.envelope as { extra?: { result?: unknown }; status?: string };
  if (!env.extra?.result || env.status === "failed") throw new ServiceError("data_unavailable", "行业目录不可用");
  return env.extra.result;
}
