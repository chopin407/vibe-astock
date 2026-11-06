import { useEffect, useRef, useState } from "react";
import { backend } from "@/lib/backend";
import type { MainlineSnapshot, MainlineView } from "@/lib/mainline";
import { DirectionActions, DirectionVerification, IndustryExplorer } from "./MainlineTools";

const LABELS: Record<string, string> = { active: "当日活跃", persistent: "样本持续活跃", expanded: "首板扩散", divergent: "分歧明显", absent: "昨日活跃、今日未延续" };
const button = "rounded border border-border px-3 py-1 text-xs disabled:opacity-50";
const pct = (n: number | null) => n == null ? "缺数据" : `${(n * 100).toFixed(1)}%`;

/** 纯展示组件同时用于真实页面和可见内容测试。 */
export function MainlineResult({ snapshot }: { snapshot: MainlineSnapshot }) {
  const d = snapshot.data;
  const [search, setSearch] = useState("");
  const [limit, setLimit] = useState(12);
  const rows = d.directions.filter(t => (t.kind === "industry" || t.limit_up > 0 || t.previous > 0) && t.tag.includes(search.trim()));
  return <div className="space-y-3">
    <p className="text-xs text-muted-foreground">{d.date} · {d.mode === "close" ? "收盘观察" : "盘中观察"} · 采集于 {d.observed_at} · {snapshot.cached ? "复用输入" : "本次取数"}</p>
    <p className="text-xs">{d.scope}。已保存版本不表示当前仍然有效。盘中确认：{snapshot.confirmation === "confirmed" ? "存在通过双时点核验的方向" : snapshot.confirmation === "pending" ? "等待第二次独立有效观察" : "没有足够真实市场时间证据"}。</p>
    {d.industry_reason && <p className="text-xs text-warning">本快照未含行业通道：{d.industry_reason}；可在下方另行核对行业完整成分。</p>}
    <div className="flex flex-wrap gap-3 text-xs">{d.coverage.map(c => <span key={c.date}>{c.date} {d.directions[0]?.kind === "industry" ? "有效行情" : "归因"} {c.covered ?? "—"}/{c.total ?? "—"}</span>)}</div>
    {!d.directions.some(x => x.checks.persistent) && <p role="status" className="text-sm">未确认持续主线；可查看单日样本和缺口。</p>}
    <label className="block text-xs">查找方向 <input aria-label="查找方向" className="ml-2 rounded border border-border bg-background px-2 py-1" value={search} onChange={e => { setSearch(e.target.value); setLimit(12); }} /></label>
    <p className="text-xs text-muted-foreground">{d.directions[0]?.kind === "industry" ? "所选行业完整成分观察；行业指数扫描次序不等于完整成分表现排名。" : `按当日已归因涨停数量排列；显示今日或昨日有样本的 ${rows.length} 个方向。标签来自源站归因，近义词暂不自动合并。`}</p>
    <div className="grid gap-3 lg:grid-cols-2">{rows.slice(0, limit).map(t => <article key={t.id} className="rounded-lg border border-border p-3">
      <h3 className="font-semibold">{t.tag}</h3>
      {t.kind === "industry" ? <p className="my-1 text-xs">有效覆盖 {pct(t.metrics?.coverage ?? null)} · 上涨占比 {pct(t.metrics?.up_share ?? null)} · 成分涨幅中位数 {t.metrics?.median_pct?.toFixed(2) ?? "缺数据"}% · 基准 {t.metrics?.benchmark_pct?.toFixed(2) ?? "缺数据"}%<br />行业指数相对基准：{t.metrics?.index_relative?.map(x => `${x.date} ${x.relative_pct.toFixed(2)}%`).join("；") || "缺数据"}。指数持续性与成分广度分别核对。</p> : <p className="my-1 text-xs">涨停 {t.limit_up} · 首板 {t.first_boards} · 昨日样本 {t.previous} · 延续 {pct(t.continuation)} · 炸板样本率 {pct(t.broken_rate)}</p>}
      <p className="text-xs">{Object.entries(LABELS).map(([k, label]) => `${label}：${t.checks[k] == null ? "缺数据" : t.checks[k] ? "满足" : "不满足"}`).join("；")}</p>
      {t.kind !== "industry" && <p className="my-2 text-xs text-muted-foreground">三日涨停样本：{t.series.map(v => v ?? "—").join(" → ")}；一股可属于多题材，不能相加。</p>}
      {snapshot.confirmation_details?.filter(c => c.direction_id === t.id).map(c => <p key={c.direction_id} className="text-xs">盘中确认 {c.state}：{c.reason}</p>)}
      <details><summary className="cursor-pointer text-xs">查看全部关联观察股（{t.members.length} 只{t.kind === "industry" ? "，行业全成员" : "，含昨日未延续成员"}）</summary>
        <ul className="mt-2 space-y-1 text-xs">{t.members.map(m => <li key={m.code}>
          <a className="text-primary" href={`/research?symbol=${encodeURIComponent(m.code)}`}>{m.code} {m.name}</a> · {m.role} · 数据日 {m.observation_date} · 涨幅 {m.ret == null ? "缺数据" : `${m.ret}%`}
          <a className="ml-2 text-primary" href={`/debate?symbol=${encodeURIComponent(m.code)}`}>多空核验</a>
        </li>)}</ul>
      </details>
      <a className="mt-2 inline-block text-xs text-primary" href={`/candidates?snapshot_id=${encodeURIComponent(snapshot.id)}&direction_id=${encodeURIComponent(t.id)}`}>进入候选池核对本快照成员</a>
      <DirectionActions snapshot={snapshot} directionId={t.id} />
    </article>)}</div>
    {rows.length > limit && <button className={button} onClick={() => setLimit(n => n + 12)}>再显示 12 个方向</button>}
    {d.gaps.length > 0 && <details open><summary className="text-xs text-warning">数据缺口（{d.gaps.length}）</summary><ul className="text-xs">{d.gaps.map((g, i) => <li key={i}>{g}</li>)}</ul></details>}
    <details><summary className="text-xs">规则与证据</summary><p className="text-xs">{d.directions[0]?.kind === "industry" ? "行业活跃：有效行情覆盖≥90%、至少10只，上涨占比≥60%，成分涨幅中位数高于上证指数；持续性另要求行业指数最近3个完成交易日相对基准均为正。" : "当日活跃：至少3只涨停；持续性：连续3日有样本、昨日至少3只且延续率≥30%；扩散：至少2只首板且样本增加。"}缺数独立标记。固定规则用于研究观察，未验证为收益预测。导出包含原始输入引用及逐维度结果。</p></details>
  </div>;
}

export function MainlinePanel({ date, mode = "close" }: { date?: string | null; mode?: "close" | "intraday" }) {
  const [view, setView] = useState<MainlineView>({ snapshot: null, history: [] });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [auto, setAuto] = useState(false);
  const control = useRef<AbortController | null>(null);
  const seq = useRef(0);
  const loading = useRef(false);
  const [revision, setRevision] = useState(0);
  const [industryId, setIndustryId] = useState<string | undefined>();
  useEffect(() => {
    const c = new AbortController(); control.current = c;
    const version = ++seq.current;
    setView({ snapshot: null, history: [] }); setBusy(false); loading.current = false; setError("");
    const q = new URLSearchParams({ mode, channel: "event", ...(date ? { date } : {}) });
    setIndustryId(undefined);
    backend.mainline(q.toString(), c.signal).then(v => { if (seq.current === version) setView(v); }).catch(e => { if (!c.signal.aborted) setError(String(e)); });
    return () => { c.abort(); control.current?.abort(); ++seq.current; };
  }, [date, mode, revision]);
  async function refresh() {
    if (loading.current) return;
    const version = seq.current;
    const c = new AbortController(); control.current = c;
    setBusy(true); loading.current = true; setError("");
    try {
      const snapshot = await backend.mainlineRefresh({ ...(date ? { date } : {}), mode, refresh: true, ...(industryId ? { industry_id: industryId } : {}) }, c.signal);
      if (version !== seq.current) return;
      const history = await backend.mainline(new URLSearchParams({ date: snapshot.data.date, mode }).toString(), c.signal);
      if (version === seq.current) setView({ ...history, snapshot });
    } catch (e) { if (!c.signal.aborted && version === seq.current) setError(String(e)); }
    finally { if (version === seq.current) { setBusy(false); loading.current = false; } }
  }
  useEffect(() => {
    if (!auto || mode !== "intraday") return;
    const timer = window.setInterval(() => { if (!document.hidden) void refresh(); }, 60_000);
    return () => window.clearInterval(timer);
  });
  const exportData = () => {
    if (!view.snapshot) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(view.snapshot, null, 2)], { type: "application/json" }));
    const a = document.createElement("a"); a.href = url; a.download = `mainline-${view.snapshot.id}.json`; a.click(); URL.revokeObjectURL(url);
  };
  return <section aria-label="主线方向与观察股" className="my-6 space-y-3 rounded-xl border border-border p-4">
    <div className="flex flex-wrap items-center gap-3"><h2 className="font-semibold">主线方向与关联观察股</h2>
      <button className={button} disabled={busy} onClick={() => void refresh()}>{busy ? "取数中…" : "生成新观察"}</button>
      {busy && <button className={button} onClick={() => { control.current?.abort(); setAuto(false); ++seq.current; loading.current = false; setBusy(false); }}>取消</button>}
      <button className={button} disabled={!view.snapshot} onClick={exportData}>导出证据</button>
      {mode === "intraday" && <label className="text-xs"><input type="checkbox" checked={auto} onChange={e => setAuto(e.target.checked)} /> 每分钟更新（页面开启期间）</label>}
      <button className={button} onClick={() => setRevision(n => n + 1)}>重读存档</button>
    </div>
    {error && <p role="alert" className="text-xs text-warning">{error}；已有成功版本保留。</p>}
    {view.history.length > 0 && <select aria-label="观察历史版本" className="max-w-full bg-background text-xs" value={view.snapshot?.id ?? ""} onChange={async e => {
      control.current?.abort(); const version = ++seq.current; setAuto(false); loading.current = false; setBusy(false);
      try { const v = await backend.mainline(new URLSearchParams({ snapshot_id: e.target.value, ...(date ? { date } : {}) }).toString()); if (seq.current === version) { setView(v); setIndustryId(v.snapshot?.data.directions[0]?.kind === "industry" ? v.snapshot.data.directions[0].id : undefined); } } catch (e) { if (seq.current === version) setError(String(e)); }
    }}>{view.history.filter(h => h.mode === mode).map(h => <option key={h.id} value={h.id}>{h.date} · {h.mode} · {h.generated_at}</option>)}</select>}
    <IndustryExplorer mode={mode} date={date} onSnapshot={snapshot => { setAuto(false); setIndustryId(snapshot.data.directions[0]?.id); setView(v => ({ snapshot, history: [{ id: snapshot.id, date: snapshot.data.date, mode: snapshot.data.mode, generated_at: snapshot.generated_at }, ...v.history] })); }} />
    {industryId && <button className={button} onClick={() => { setIndustryId(undefined); setAuto(false); setRevision(n => n + 1); }}>切回事件题材通道</button>}
    {view.snapshot ? <MainlineResult key={view.snapshot.id} snapshot={view.snapshot} /> : <p className="text-xs text-muted-foreground">暂无保存的观察。点击生成；首次需获取三个交易日的完整样本，可能需要较长时间。结果允许无主线或数据不足。</p>}
    <DirectionVerification />
  </section>;
}
