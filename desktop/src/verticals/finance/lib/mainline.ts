export interface MainlineDirection {
  id: string; tag: string; limit_up: number; first_boards: number; previous: number;
  continuation: number | null; broken_rate: number | null; series: (number | null)[];
  checks: Record<string, boolean | null>;
  members: { code: string; name: string; role: string; observation_date: string; ret: number | null }[];
  kind?: "industry";
  metrics?: { coverage: number; median_pct?: number | null; up_share?: number | null; benchmark_pct?: number | null; index_relative?: { date: string; relative_pct: number }[] };
}
export interface MainlineSnapshot {
  id: string; generated_at: string; status: string; cached: boolean; confirmation: string;
  confirmation_details?: { direction_id: string; state: string; reason: string }[];
  data: { date: string; mode: string; observed_at: string; scope: string; directions: MainlineDirection[];
    industry_reason: string; gaps: string[]; coverage: { date: string; covered: number | null; total: number | null }[] };
}
export interface MainlineView { snapshot: MainlineSnapshot | null; history: { id: string; date: string; mode: string; generated_at: string }[] }
export interface IndustryCatalog { date: string; groups: { id: string; name: string; member_count: number; trend?: { date: string; relative_pct: number }[] }[]; point_in_time: string }
export interface Supplement { id: string; snapshot_id: string; direction_id: string; results: { kind: string; status: string; reason?: string; result?: { note?: string; tables?: unknown[]; articles?: { title: string; url: string; published_at: string; source: string }[] } }[] }
export interface DirectionPlan { id: string; direction: string; metric: string; expected: boolean; created_at: string; result: { state: string; reason: string; target_id?: string } }
