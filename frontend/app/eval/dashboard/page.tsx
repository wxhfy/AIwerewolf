"use client";

import React, { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ErrorBar,
  Legend,
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
 *  - GET /api/metrics/aggregate       — Track B 持久层聚合
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

const COLOR_GOOD = "rgb(var(--color-village-rgb) / 0.95)";
const COLOR_BAD = "rgb(var(--color-danger-rgb) / 0.95)";
const COLOR_NEUTRAL = "rgb(var(--color-text-sub-rgb) / 0.7)";
const COLOR_GRID = "rgb(var(--color-text-sub-rgb) / 0.16)";
const COLOR_AXIS = "rgb(var(--color-text-sub-rgb) / 0.72)";
const COLOR_CARD = "var(--color-card)";
const COLOR_BORDER = "var(--color-border)";
const COLOR_TEXT = "rgb(var(--color-text-rgb) / 0.95)";
const TOOLTIP_STYLE = {
  backgroundColor: COLOR_CARD,
  border: `1px solid ${COLOR_BORDER}`,
  color: COLOR_TEXT,
};

export default function EvalDashboardPage() {
  const [roleScores, setRoleScores] = useState<RoleScoresResponse | null>(null);
  const [aggregate, setAggregate] = useState<AggregateMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshTick, setRefreshTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function loadAll() {
      setLoading(true);
      setError("");
      try {
        const [scoresRes, aggRes] = await Promise.all([
          fetch(apiUrl("/api/eval/role-scores")),
          fetch(apiUrl("/api/metrics/aggregate?limit_games=500")),
        ]);
        if (cancelled) return;
        if (scoresRes.ok) setRoleScores(await scoresRes.json());
        if (aggRes.ok) setAggregate(await aggRes.json());
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

  // ------------- KPIs -------------
  const kpis = useMemo(() => {
    const tb = aggregate?.track_b;
    const summary = roleScores?.summary;
    return {
      published: tb?.published_total ?? 0,
      approved: tb?.approved ?? 0,
      avgScore: tb?.avg_score ?? 0,
      discriminating: summary
        ? `${summary.discriminating_count}/${summary.total_roles}`
        : "0/0",
      discriminationPass: summary?.overall_pass ?? false,
      experimentGames: roleScores?.total_records ?? 0,
    };
  }, [aggregate, roleScores]);

  return (
    <div className="min-h-screen space-y-6 bg-background p-6 text-textPrimary">
      <header className="flex items-center justify-between border-b border-border pb-4">
        <div>
          <h1 className="text-2xl font-semibold">Track B 评估总览</h1>
          <p className="mt-1 text-sm text-text-sub">
            真 LLM 评分区分度 — 最新刷新时间: {new Date().toLocaleString()}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => setRefreshTick((t) => t + 1)}
            className="rounded-card border border-primary/20 bg-primary px-3 py-2 text-sm font-medium text-white transition hover:bg-primaryHover"
          >
            刷新
          </button>
        </div>
      </header>

      {error && (
        <div className="rounded-card border border-danger/30 bg-danger/10 p-3 text-sm text-danger">
          {error}
        </div>
      )}

      {/* KPI strip */}
      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Kpi label="Track B 发布" value={kpis.published} sub={`approved ${kpis.approved}`} />
        <Kpi label="平均 ValidAgent 分" value={kpis.avgScore.toFixed(2)} sub="0-1" />
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
                <CartesianGrid strokeDasharray="3 3" stroke={COLOR_GRID} />
                <XAxis dataKey="role" stroke={COLOR_AXIS} />
                <YAxis domain={[0, 100]} stroke={COLOR_AXIS} />
                <Tooltip
                  contentStyle={TOOLTIP_STYLE}
                  labelStyle={{ color: COLOR_TEXT }}
                />
                <Legend />
                <Bar dataKey="good_mean" name="good 策略均分" fill={COLOR_GOOD}>
                  <ErrorBar dataKey="good_sd" stroke={COLOR_GOOD} strokeWidth={1.5} />
                </Bar>
                <Bar dataKey="bad_mean" name="bad 策略均分" fill={COLOR_BAD}>
                  <ErrorBar dataKey="bad_sd" stroke={COLOR_BAD} strokeWidth={1.5} />
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
                <CartesianGrid strokeDasharray="3 3" stroke={COLOR_GRID} />
                <XAxis
                  type="number"
                  dataKey="x"
                  ticks={roleScoreChartData.map((_, i) => i + 1)}
                  tickFormatter={(idx: number) => roleScoreChartData[idx - 1]?.role || ""}
                  stroke={COLOR_AXIS}
                  domain={[0.5, roleScoreChartData.length + 0.5]}
                />
                <YAxis type="number" dataKey="y" domain={[0, 100]} stroke={COLOR_AXIS} />
                <ZAxis range={[60, 60]} />
                <Tooltip
                  cursor={{ strokeDasharray: "3 3" }}
                  contentStyle={TOOLTIP_STYLE}
                  labelStyle={{ color: COLOR_TEXT }}
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

      <footer className="border-t border-border pt-4 text-xs text-text-sub">
        本页布局固定，新一轮数据出现后点右上 “刷新” 即可。后端数据来源：
        <code className="ml-1 text-textPrimary">/api/eval/role-scores</code>{" "}
        <code className="ml-1 text-textPrimary">/api/metrics/aggregate</code>{" "}
        {loading && <span className="ml-3 text-text-sub">loading...</span>}
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
    <div className="rounded-card border border-border bg-cardBackground p-4 shadow-card">
      <div className="text-xs uppercase tracking-wide text-text-sub">{label}</div>
      <div
        className="mt-1 text-2xl font-semibold text-textPrimary"
        style={accent ? { color: accent } : undefined}
      >
        {value}
      </div>
      {sub && <div className="mt-1 text-xs text-text-sub/75">{sub}</div>}
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
    <div className="rounded-card border border-border bg-cardBackground p-4 shadow-card">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="text-base font-semibold text-textPrimary">{title}</h2>
        {subtitle && <span className="text-xs text-text-sub/75">{subtitle}</span>}
      </div>
      {children}
    </div>
  );
}

function EmptyState({ label }: { label: string }) {
  return (
    <div className="flex h-[260px] items-center justify-center rounded-card border border-dashed border-border text-sm italic text-text-sub/75">
      {label}
    </div>
  );
}

function DiscriminationTable({ rows }: { rows: any[] }) {
  if (rows.length === 0) return null;
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full text-xs text-text-sub">
        <thead>
          <tr className="border-b border-border text-text-sub/75">
            <th className="py-1 text-left">角色</th>
            <th className="py-1 text-right">good 均分</th>
            <th className="py-1 text-right">bad 均分</th>
            <th className="py-1 text-right">Cohen&apos;s d</th>
            <th className="py-1 text-left pl-3">verdict</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.role} className="border-b border-border/40">
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
