import { useEffect, useRef, useState } from "react";
import { backend } from "@/lib/backend";
import type { DirectionPlan, IndustryCatalog, MainlineSnapshot, Supplement } from "@/lib/mainline";

const cls = "rounded border border-border px-2 py-1 text-xs disabled:opacity-50";
const percent = (n: number | null | undefined) => n == null ? "缺数据" : `${n.toFixed(2)}%`;

export function IndustryExplorer({ mode, date, onSnapshot }: { mode: string; date?: string | null; onSnapshot: (s: MainlineSnapshot) => void }) {
  const [catalog, setCatalog] = useState<IndustryCatalog | null>(null);
  const [chosen, setChosen] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const ctl = useRef<AbortController | null>(null);
  useEffect(() => { setCatalog(null); setChosen(""); setBusy(false); return () => ctl.current?.abort(); }, [date, mode]);
  async function load(scan: boolean) {
    const c = new AbortController(); ctl.current = c; setBusy(true); setError("");
    try { const r = await backend.mainlineIndustries(scan, c.signal); c.signal.throwIfAborted(); setCatalog(r); setChosen(r.groups[0]?.id ?? ""); }
    catch (e) { if (!c.signal.aborted) setError(String(e)); }
    finally { if (!c.signal.aborted) setBusy(false); }
  }
  async function observe() {
    const c = new AbortController(); ctl.current = c; setBusy(true); setError("");
    try { const result = await backend.mainlineRefresh({ date: date || catalog?.date, mode, industry_id: chosen, refresh: true }, c.signal); c.signal.throwIfAborted(); onSnapshot(result); }
    catch (e) { if (!c.signal.aborted) setError(String(e)); }
    finally { if (!c.signal.aborted) setBusy(false); }
  }
  return <details className="rounded border border-border p-3"><summary className="cursor-pointer text-sm">行业趋势与完整成分（TDX）</summary>
    <p className="my-2 text-xs text-muted-foreground">先扫描行业指数，再对所选方向核对完整成分广度；指数强不等于全成分强。当前分类不回填历史。</p>
    <div className="flex flex-wrap gap-2"><button className={cls} disabled={busy} onClick={() => void load(false)}>加载行业目录</button><button className={cls} disabled={busy} onClick={() => void load(true)}>扫描行业指数</button>
      {busy && <button className={cls} onClick={() => { ctl.current?.abort(); setBusy(false); }}>取消行业取数</button>}
      {catalog && <><select aria-label="选择行业" className="max-w-full bg-background text-xs" value={chosen} onChange={e => setChosen(e.target.value)}>{catalog.groups.map(g => <option key={g.id} value={g.id}>{g.name} · {g.member_count}只 · 指数相对涨幅 {percent(g.trend?.at(-1)?.relative_pct)}</option>)}</select>
        <button className={cls} disabled={busy || !chosen} onClick={() => void observe()}>核对行业完整成分</button></>}
    </div>
    {catalog && <p className="mt-2 text-xs">{catalog.groups.length} 个行业 · {catalog.point_in_time}</p>}
    {error && <p role="alert" className="text-xs text-warning">{error}</p>}
    {busy && <p role="status" className="text-xs">行业取数中；目录和指数扫描不代表成分行情已覆盖。</p>}
  </details>;
}

export function SupplementResult({ record }: { record: Supplement }) {
  return <div className="space-y-2 text-xs">{record.results.map(r => <div key={r.kind}>
    <p>{r.kind === "data" ? "妙想结构化补充" : "妙想事件检索"}：{r.status} · {r.result?.note || r.reason || "暂无有效结果"}</p>
    {r.result?.tables?.length ? <details><summary>查看原始结构化表（未自动用于计算）</summary><pre className="max-h-64 overflow-auto whitespace-pre-wrap">{JSON.stringify(r.result.tables, null, 2)}</pre></details> : null}
    <ul>{r.result?.articles?.map(a => <li key={a.url + a.title}><a href={a.url} target="_blank" rel="noopener noreferrer" className="text-primary">{a.title}</a> · {a.published_at} · {a.source}</li>)}</ul>
  </div>)}</div>;
}

export function DirectionActions({ snapshot, directionId }: { snapshot: MainlineSnapshot; directionId: string }) {
  const [record, setRecord] = useState<Supplement | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [expected, setExpected] = useState(true);
  const [metric, setMetric] = useState("persistent");
  const ctl = useRef<AbortController | null>(null);
  useEffect(() => { setRecord(null); setNote(""); return () => ctl.current?.abort(); }, [snapshot.id, directionId]);
  async function supplement(live: boolean) {
    setBusy(true); setNote(""); const c = new AbortController(); ctl.current = c;
    try {
      if (live) setRecord(await backend.mainlineSupplement(snapshot.id, directionId, c.signal));
      else { const rows = await backend.mainlineSupplements(snapshot.id, c.signal); setRecord(rows.find(r => r.direction_id === directionId) ?? null); setNote(rows.some(r => r.direction_id === directionId) ? "" : "暂无此方向补充存档"); }
    } catch (e) { if (!c.signal.aborted) setNote(String(e)); }
    finally { if (!c.signal.aborted) setBusy(false); }
  }
  return <details className="mt-3 border-t border-border pt-2"><summary className="cursor-pointer text-xs">补充关系、事件与下日验证</summary>
    <p className="my-2 text-xs text-muted-foreground">只发送本方向名称和业务日给妙想；补充结果独立归档，未核验表格不进入主线计算。</p>
    <div className="flex flex-wrap gap-2"><button className={cls} disabled={busy} onClick={() => void supplement(true)}>查询妙想补充</button><button className={cls} disabled={busy} onClick={() => void supplement(false)}>读取补充存档</button>
      {busy && <button className={cls} onClick={() => { ctl.current?.abort(); setBusy(false); }}>取消补充</button>}</div>
    {record && <SupplementResult record={record} />}
    {snapshot.data.mode === "close" && <div className="mt-2 flex flex-wrap gap-2">
      <select aria-label="验证指标" className="bg-background text-xs" value={metric} onChange={e => setMetric(e.target.value)}><option value="persistent">下日持续活跃</option><option value="active">下日当日活跃</option></select>
      <select aria-label="验证预期" className="bg-background text-xs" value={String(expected)} onChange={e => setExpected(e.target.value === "true")}><option value="true">预期满足</option><option value="false">预期不满足</option></select>
      <button className={cls} disabled={busy} onClick={async () => { setBusy(true); try { await backend.mainlinePlan(snapshot.id, directionId, metric, expected); setNote("已独立记录；下一交易日09:15后形成的记录标事后。请重读下方方向验证。"); } catch (e) { setNote(String(e)); } finally { setBusy(false); } }}>记录方向验证</button>
    </div>}
    {note && <p role="status" className="mt-2 text-xs text-warning">{note}</p>}
  </details>;
}

export function VerificationResults({ plans }: { plans: DirectionPlan[] }) {
  const labels: Record<string, string> = { pending: "待验证", missing: "缺数据", posthoc: "事后记录", met: "满足预期", unmet: "不满足预期" };
  return <ul className="space-y-2 text-xs">{plans.map(p => <li key={p.id}>{p.direction} · {p.metric === "persistent" ? "持续活跃" : "当日活跃"} · 预期{p.expected ? "满足" : "不满足"} · {labels[p.result.state] || p.result.state}：{p.result.reason}</li>)}</ul>;
}
export function DirectionVerification() {
  const [plans, setPlans] = useState<DirectionPlan[]>([]);
  const [error, setError] = useState("");
  return <details className="rounded border border-border p-3"><summary className="cursor-pointer text-sm">方向独立验证（不计入原明日验证战绩）</summary>
    <button className={`${cls} my-2`} onClick={async () => { try { setPlans(await backend.mainlinePlans()); setError(""); } catch (e) { setError(String(e)); } }}>重读方向验证</button>
    <VerificationResults plans={plans} />{!plans.length && <p className="text-xs">暂无读取的方向验证记录。</p>}{error && <p role="alert" className="text-xs text-warning">{error}</p>}
  </details>;
}
