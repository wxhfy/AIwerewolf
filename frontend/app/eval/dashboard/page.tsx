"use client";

import React, { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ErrorBar,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import { apiUrl } from "@/lib/api";

/**
 * Track B/C 评估总览页。固定布局，所有图表都从后端聚合 API + experiment JSON 读取。
 * 新一轮实验只需重新刷新页面，不必改前端代码。
 *
 * 数据源:
 *  - GET /api/eval/role-scores        — 真 LLM 评分区分度实验
 *  - GET /api/metrics/aggregate       — Track B/C 持久层聚合
 *  - GET /api/evolution               — DreamJob 轮次 delta_win_rate
 *  - GET /api/evolution/dashboard     — acceptance_metrics + patches[]
 */

type RoleScore = {
  role: string;
  variant: "good" | "bad" | string;
  seed: number | null;
  game_id: string | null;
  adjusted_final_score: number | null;
  role_task_score: number | null;
  mistakes: number;
  fallback: number;
  winner: string | null;
};

type PerRoleSummary = {
  role: string;
  good: ArmStats;
  bad: ArmStats;
  cohens_d_adjusted_final_score: number;
  welch_t_p_adjusted_final_score: number;
  cohens_d_role_task_score: number;
  welch_t_p_role_task_score: number;
  verdict: string;
};

type ArmStats = {
  adjusted_final_score: { n: number; mean: number | null; sd: number | null; min: number | null; max: number | null };
  role_task_score: { n: number; mean: number | null; sd: number | null; min: number | null; max: number | null };
  mistakes_per_game: { n: number; mean: number | null; sd: number | null; min: number | null; max: number | null };
};

type RoleScoresResponse = {
  available: boolean;
  summary: {
    threshold_d: number;
    threshold_roles: number;
    discriminating_count: number;
    total_roles: number;
    overall_pass: boolean;
    per_role: PerRoleSummary[];
  } | null;
  raw_counts: Record<string, Record<string, number>>;
  raw_records: RoleScore[];
  total_records: number;
};

type AggregateMetrics = {
  games: number;
  win_rate_by_role: Record<string, number>;
  track_b: {
    published_total: number;
    approved: number;
    needs_revision: number;
    rejected: number;
    avg_score: number;
  };
  track_c: {
    strategy_docs_total: number;
    by_status: Record<string, number>;
    by_doc_type: Record<string, number>;
    patches_total: number;
    by_patch_status: Record<string, number>;
    tournaments_total: number;
    accepted: number;
    rejected: number;
  };
  runtime?: {
    decision_count: number;
    validity_rate: number;
    llm_call_count: number;
  };
};

type EvolutionRound = {
  id?: string;
  baseline_version?: string;
  candidate_version?: string;
  baseline_wins?: number;
  challenger_wins?: number;
  delta_win_rate?: number;
  accepted?: boolean;
  created_at?: string;
};

type EvolutionDashboard = {
  acceptance_metrics?: Array<{
    track: string;
    step_id: string;
    name: string;
    numerator: number;
    denominator: number;
    success_rate: number;
    threshold: number;
    passed: boolean;
    evidence?: string;
  }>;
};

const COLOR_GOOD = "#22c55e";
const COLOR_BAD = "#ef4444";
const COLOR_NEUTRAL = "#64748b";
const COLOR_ACCENT = "#3b82f6";

export default function EvalDashboardPage() {
  const [roleScores, setRoleScores] = useState<RoleScoresResponse | null>(null);
  const [aggregate, setAggregate] = useState<AggregateMetrics | null>(null);
  const [rounds, setRounds] = useState<EvolutionRound[]>([]);
  const [evolutionDashboard, setEvolutionDashboard] = useState<EvolutionDashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshTick, setRefreshTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function loadAll() {
      setLoading(true);
      setError("");
      try {
        const [scoresRes, aggRes, evoRes, evoDashRes] = await Promise.all([
          fetch(apiUrl("/api/eval/role-scores")),
          fetch(apiUrl("/api/metrics/aggregate?limit_games=500")),
          fetch(apiUrl("/api/evolution?limit=30")),
          fetch(apiUrl("/api/evolution/dashboard")),
        ]);
        if (cancelled) return;
        if (scoresRes.ok) setRoleScores(await scoresRes.json());
        if (aggRes.ok) setAggregate(await aggRes.json());
        if (evoRes.ok) setRounds(await evoRes.json());
        if (evoDashRes.ok) setEvolutionDashboard(await evoDashRes.json());
      } catch (err: any) {
        if (!cancelled) setError(err.message || "load failed");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    loadAll();
    return () => {
      cancelled = true;
    };
  }, [refreshTick]);

  // ------------- chart data builders -------------
  const roleScoreChartData = useMemo(() => {
    const perRole = roleScores?.summary?.per_role || [];
    return perRole.map((row) => {
      const goodMean = row.good.adjusted_final_score.mean ?? 0;
      const goodSd = row.good.adjusted_final_score.sd ?? 0;
      const badMean = row.bad.adjusted_final_score.mean ?? 0;
      const badSd = row.bad.adjusted_final_score.sd ?? 0;
      return {
        role: row.role,
        good_mean: Number(goodMean.toFixed(2)),
        good_sd: Number(goodSd.toFixed(2)),
        bad_mean: Number(badMean.toFixed(2)),
        bad_sd: Number(badSd.toFixed(2)),
        cohens_d: Number((row.cohens_d_adjusted_final_score || 0).toFixed(2)),
        verdict: row.verdict,
      };
    });
  }, [roleScores]);

  const rawScatterData = useMemo(() => {
    const recs = roleScores?.raw_records || [];
    return recs.map((rec) => ({
      role: rec.role,
      variant: rec.variant,
      x: roleScoreChartData.findIndex((r) => r.role === rec.role) + 1,
      y: rec.adjusted_final_score ?? 0,
      mistakes: rec.mistakes,
      seed: rec.seed,
      fill: rec.variant === "good" ? COLOR_GOOD : COLOR_BAD,
    }));
  }, [roleScores, roleScoreChartData]);

  const evolutionDeltaData = useMemo(() => {
    return rounds
      .slice()
      .reverse()
      .map((round, index) => ({
        index: index + 1,
        delta_win_rate: Number(((round.delta_win_rate ?? 0) * 100).toFixed(2)),
        baseline_wins: round.baseline_wins ?? 0,
        candidate_wins: round.challenger_wins ?? 0,
        accepted: round.accepted ? 1 : 0,
        label: round.candidate_version || `r${index + 1}`,
      }));
  }, [rounds]);

  const patchStatusData = useMemo(() => {
    const byStatus = aggregate?.track_c?.by_patch_status || {};
    return Object.entries(byStatus).map(([status, count]) => ({
      status,
      count,
    }));
  }, [aggregate]);

  const gateData = useMemo(() => {
    const metrics = evolutionDashboard?.acceptance_metrics || [];
    return metrics.map((m) => ({
      step: m.step_id,
      success_rate_pct: Number((m.success_rate * 100).toFixed(1)),
      threshold_pct: Number((m.threshold * 100).toFixed(1)),
      passed: m.passed ? 1 : 0,
      name: m.name,
    }));
  }, [evolutionDashboard]);

  // ------------- KPIs -------------
  const kpis = useMemo(() => {
    const tb = aggregate?.track_b;
    const tc = aggregate?.track_c;
    const summary = roleScores?.summary;
    return {
      published: tb?.published_total ?? 0,
      approved: tb?.approved ?? 0,
      avgScore: tb?.avg_score ?? 0,
      knowledgeDocs: tc?.strategy_docs_total ?? 0,
      patches: tc?.patches_total ?? 0,
      tournaments: tc?.tournaments_total ?? 0,
      tournamentsAccepted: tc?.accepted ?? 0,
      discriminating: summary
        ? `${summary.discriminating_count}/${summary.total_roles}`
        : "0/0",
      discriminationPass: summary?.overall_pass ?? false,
      experimentGames: roleScores?.total_records ?? 0,
    };
  }, [aggregate, roleScores]);

  return (
    <div className="min-h-screen bg-[var(--color-bg,#0b0f17)] text-[var(--color-fg,#e2e8f0)] p-6 space-y-6">
      <header className="flex items-center justify-between border-b border-[var(--color-border,#1e293b)] pb-4">
        <div>
          <h1 className="text-2xl font-semibold">Track B/C 评估总览</h1>
          <p className="text-sm text-slate-400 mt-1">
            真 LLM 评分区分度 + 进化效果 — 最新刷新时间: {new Date().toLocaleString()}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Link
            href="/evolution"
            className="px-3 py-2 text-sm rounded-card border border-[var(--color-border,#1e293b)] bg-[var(--color-card,#0f172a)] hover:bg-[var(--color-card-hover,#1e293b)] transition"
          >
            前往 Track C 控制台
          </Link>
          <button
            onClick={() => setRefreshTick((t) => t + 1)}
            className="px-3 py-2 text-sm rounded-card border border-[var(--color-border,#1e293b)] bg-[var(--color-accent,#3b82f6)] text-white hover:opacity-90 transition"
          >
            刷新
          </button>
        </div>
      </header>

      {error && (
        <div className="rounded-card border border-red-700 bg-red-900/30 text-red-200 p-3 text-sm">
          {error}
        </div>
      )}

      {/* KPI strip */}
      <section className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
        <Kpi label="Track B 发布" value={kpis.published} sub={`approved ${kpis.approved}`} />
        <Kpi label="平均 ValidAgent 分" value={kpis.avgScore.toFixed(2)} sub="0-1" />
        <Kpi label="知识文档" value={kpis.knowledgeDocs} sub={`patches ${kpis.patches}`} />
        <Kpi label="A/B 锦标赛" value={kpis.tournaments} sub={`accepted ${kpis.tournamentsAccepted}`} />
        <Kpi
          label="评分区分度"
          value={kpis.discriminating}
          sub={kpis.discriminationPass ? "PASS" : "running"}
          accent={kpis.discriminationPass ? COLOR_GOOD : COLOR_NEUTRAL}
        />
        <Kpi label="实验局数" value={kpis.experimentGames} sub="真 LLM" />
      </section>

      {/* Chart row 1: per-role score discrimination */}
      <section className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <Panel title="按角色 — 评分均值 ± SD (good vs bad)" subtitle="adjusted_final_score 区间 0-100">
          {roleScoreChartData.length === 0 ? (
            <EmptyState label="等待 scripts/analyze_score_distributions.py 写出 discrimination_summary.json" />
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={roleScoreChartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="role" stroke="#94a3b8" />
                <YAxis domain={[0, 100]} stroke="#94a3b8" />
                <Tooltip
                  contentStyle={{ backgroundColor: "#0f172a", border: "1px solid #1e293b" }}
                  labelStyle={{ color: "#e2e8f0" }}
                />
                <Legend />
                <Bar dataKey="good_mean" name="good 策略均分" fill={COLOR_GOOD}>
                  <ErrorBar dataKey="good_sd" stroke="#86efac" strokeWidth={1.5} />
                </Bar>
                <Bar dataKey="bad_mean" name="bad 策略均分" fill={COLOR_BAD}>
                  <ErrorBar dataKey="bad_sd" stroke="#fca5a5" strokeWidth={1.5} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
          <DiscriminationTable rows={roleScoreChartData} />
        </Panel>

        <Panel title="按角色 — 每局原始分散点 (good vs bad)" subtitle="单点 = 一局 LLM 对局">
          {rawScatterData.length === 0 ? (
            <EmptyState label="data/experiment/ 下还没有完成的对局 JSON" />
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <ScatterChart>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis
                  type="number"
                  dataKey="x"
                  ticks={roleScoreChartData.map((_, i) => i + 1)}
                  tickFormatter={(idx: number) => roleScoreChartData[idx - 1]?.role || ""}
                  stroke="#94a3b8"
                  domain={[0.5, roleScoreChartData.length + 0.5]}
                />
                <YAxis type="number" dataKey="y" domain={[0, 100]} stroke="#94a3b8" />
                <ZAxis range={[60, 60]} />
                <Tooltip
                  cursor={{ strokeDasharray: "3 3" }}
                  contentStyle={{ backgroundColor: "#0f172a", border: "1px solid #1e293b" }}
                  labelStyle={{ color: "#e2e8f0" }}
                  formatter={(value: any, name: any) => [value, name ?? ""]}
                />
                <Legend />
                <Scatter name="good 局" data={rawScatterData.filter((d) => d.variant === "good")} fill={COLOR_GOOD} />
                <Scatter name="bad 局" data={rawScatterData.filter((d) => d.variant === "bad")} fill={COLOR_BAD} />
              </ScatterChart>
            </ResponsiveContainer>
          )}
        </Panel>
      </section>

      {/* Chart row 2: evolution + patches + gates */}
      <section className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Panel title="进化轮次 — Δ 胜率 (%)" subtitle={`最近 ${evolutionDeltaData.length} 轮`}>
          {evolutionDeltaData.length === 0 ? (
            <EmptyState label="没有 EvolutionRound 数据" />
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={evolutionDeltaData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="index" stroke="#94a3b8" />
                <YAxis stroke="#94a3b8" />
                <Tooltip
                  contentStyle={{ backgroundColor: "#0f172a", border: "1px solid #1e293b" }}
                  labelStyle={{ color: "#e2e8f0" }}
                />
                <ReferenceLine y={0} stroke="#475569" />
                <Line
                  type="monotone"
                  dataKey="delta_win_rate"
                  stroke={COLOR_ACCENT}
                  strokeWidth={2}
                  dot={(props: any) => {
                    const accepted = props.payload?.accepted === 1;
                    return (
                      <circle
                        key={props.key}
                        cx={props.cx}
                        cy={props.cy}
                        r={4}
                        stroke={accepted ? COLOR_GOOD : COLOR_NEUTRAL}
                        fill={accepted ? COLOR_GOOD : "#0f172a"}
                        strokeWidth={1.5}
                      />
                    );
                  }}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </Panel>

        <Panel title="Patch 状态分布" subtitle={`Track C 累计 ${aggregate?.track_c?.patches_total ?? 0}`}>
          {patchStatusData.length === 0 ? (
            <EmptyState label="没有 patch 记录" />
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={patchStatusData} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis type="number" stroke="#94a3b8" />
                <YAxis dataKey="status" type="category" width={100} stroke="#94a3b8" />
                <Tooltip
                  contentStyle={{ backgroundColor: "#0f172a", border: "1px solid #1e293b" }}
                  labelStyle={{ color: "#e2e8f0" }}
                />
                <Bar dataKey="count" fill={COLOR_ACCENT} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </Panel>

        <Panel title="B/C 验收门通过率" subtitle="success_rate vs threshold">
          {gateData.length === 0 ? (
            <EmptyState label="没有 acceptance_metrics" />
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={gateData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="step" stroke="#94a3b8" angle={-25} textAnchor="end" height={50} interval={0} fontSize={10} />
                <YAxis stroke="#94a3b8" domain={[0, 100]} />
                <Tooltip
                  contentStyle={{ backgroundColor: "#0f172a", border: "1px solid #1e293b" }}
                  labelStyle={{ color: "#e2e8f0" }}
                />
                <Legend />
                <Bar dataKey="threshold_pct" name="阈值 %" fill="#1e293b" />
                <Bar dataKey="success_rate_pct" name="实测 %">
                  {gateData.map((entry, idx) => (
                    <Cell key={idx} fill={entry.passed ? COLOR_GOOD : COLOR_BAD} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </Panel>
      </section>

      <footer className="border-t border-[var(--color-border,#1e293b)] pt-4 text-xs text-slate-500">
        本页布局固定，新一轮数据出现后点右上 “刷新” 即可。后端数据来源：
        <code className="text-slate-300 ml-1">/api/eval/role-scores</code>{" "}
        <code className="text-slate-300 ml-1">/api/metrics/aggregate</code>{" "}
        <code className="text-slate-300 ml-1">/api/evolution</code>{" "}
        <code className="text-slate-300 ml-1">/api/evolution/dashboard</code>
        {loading && <span className="ml-3 text-slate-400">loading…</span>}
      </footer>
    </div>
  );
}

function Kpi({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string | number;
  sub?: string;
  accent?: string;
}) {
  return (
    <div className="rounded-card border border-[var(--color-border,#1e293b)] bg-[var(--color-card,#0f172a)] p-4">
      <div className="text-xs text-slate-400 uppercase tracking-wide">{label}</div>
      <div
        className="text-2xl font-semibold mt-1"
        style={accent ? { color: accent } : undefined}
      >
        {value}
      </div>
      {sub && <div className="text-xs text-slate-500 mt-1">{sub}</div>}
    </div>
  );
}

function Panel({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-card border border-[var(--color-border,#1e293b)] bg-[var(--color-card,#0f172a)] p-4">
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="text-base font-semibold">{title}</h2>
        {subtitle && <span className="text-xs text-slate-500">{subtitle}</span>}
      </div>
      {children}
    </div>
  );
}

function EmptyState({ label }: { label: string }) {
  return (
    <div className="h-[260px] flex items-center justify-center text-sm text-slate-500 italic border border-dashed border-[var(--color-border,#1e293b)] rounded">
      {label}
    </div>
  );
}

function DiscriminationTable({ rows }: { rows: any[] }) {
  if (rows.length === 0) return null;
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full text-xs text-slate-300">
        <thead>
          <tr className="text-slate-500 border-b border-[var(--color-border,#1e293b)]">
            <th className="py-1 text-left">角色</th>
            <th className="py-1 text-right">good 均分</th>
            <th className="py-1 text-right">bad 均分</th>
            <th className="py-1 text-right">Cohen&apos;s d</th>
            <th className="py-1 text-left pl-3">verdict</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.role} className="border-b border-[var(--color-border,#1e293b)]/40">
              <td className="py-1">{row.role}</td>
              <td className="py-1 text-right">{row.good_mean}</td>
              <td className="py-1 text-right">{row.bad_mean}</td>
              <td className="py-1 text-right">{row.cohens_d}</td>
              <td
                className="py-1 pl-3"
                style={{
                  color:
                    row.verdict === "DISCRIMINATES"
                      ? COLOR_GOOD
                      : row.verdict === "INCONCLUSIVE"
                      ? COLOR_NEUTRAL
                      : COLOR_BAD,
                }}
              >
                {row.verdict}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
