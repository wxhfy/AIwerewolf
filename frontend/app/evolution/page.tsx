"use client";

import React, { useEffect, useState, useMemo } from "react";
import Link from "next/link";
import { apiUrl } from "@/lib/api";
import { useAppContext } from "@/context/AppContext";

/* ── Types ── */

interface StrategyCard {
  card_id: string;
  role: string;
  version: string;
  goal: string;
  speech_policy: string[];
  vote_policy: string[];
  skill_policy: string[];
  risk_rules: string[];
  retrieval_policy: { top_k: number; enabled: boolean; min_quality: number };
  status: string;
  created_at: string;
}

interface KnowledgeDoc {
  doc_id: string;
  role: string;
  phase: string;
  doc_type: string;
  quality_score: number;
  usage_count: number;
  success_count: number;
  failure_count: number;
  status: string;
  recommended_action: string;
  situation_pattern: string;
  rationale: string;
  evidence_summary: string;
  trigger_conditions: string[];
  confidence_tier: string;
}

interface Tournament {
  tournament_id: string;
  baseline_version: string;
  candidate_version: string;
  status: string;
  decision?: { action?: string };
  comparison?: {
    candidate_camp_win_rate?: number;
    baseline_camp_win_rate?: number;
    candidate_target_role_avg_score?: number;
    candidate_critical_mistakes_per_game?: number;
  };
}

interface AcceptanceMetric {
  track: string;
  step_id: string;
  name: string;
  numerator: number;
  denominator: number;
  success_rate: number;
  threshold: number;
  passed: boolean;
  evidence: string;
}

interface ApiDashboard {
  active_versions: StrategyCard[];
  knowledge: KnowledgeDoc[];
  tournaments: Tournament[];
  acceptance_metrics: AcceptanceMetric[];
  acceptance_audit?: { overall_success_rate?: number; passed?: boolean; total_steps?: number };
}

/* ── Experiment data ── */

const EXPERIMENT_TIERS = {
  baseline:    { name: "Baseline",    desc: "纯 MBTI + Role，无策略" },
  anti_only:   { name: "Anti-Patterns", desc: "MBTI + 静态反模式清单" },
  trackc_only: { name: "Track C",       desc: "MBTI + 动态策略检索" },
  both:        { name: "Anti + Track C", desc: "完整三层架构" },
};

const EXPERIMENT: Record<string, { games: number; failed: number; village: number; wolf: number; days: number }> = {
  baseline:    { games: 18, failed: 4,  village: 33.3, wolf: 66.7, days: 1.72 },
  anti_only:   { games: 20, failed: 2,  village: 20.0, wolf: 80.0, days: 1.85 },
  trackc_only: { games: 13, failed: 13, village: 30.8, wolf: 69.2, days: 1.77 },
  both:        { games: 13, failed: 20, village: 23.1, wolf: 76.9, days: 1.69 },
};

const META = "2026-06-07 · doubao:deepseek-v4-flash · 7P · strict";

const CARD_COLORS: Record<string, string> = {
  Seer: "#a78bfa", Witch: "#34d399", Hunter: "#fbbf24", Guard: "#60a5fa",
  Villager: "#9ca3af", Werewolf: "#f87171", WhiteWolfKing: "#ef4444",
};

/* ── Helpers ── */

function delta(a: number, b: number): string {
  const d = a - b;
  return `${d >= 0 ? "+" : ""}${d.toFixed(1)}%`;
}

function deltaNum(a: number, b: number): number { return a - b; }

/* ── Page ── */

export default function EvolutionPage() {
  const { language } = useAppContext();
  const t = (zh: string, en: string) => (language === "zh" ? zh : en);

  const [api, setApi] = useState<ApiDashboard | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(apiUrl("/api/evolution/dashboard"));
        if (res.ok) setApi(await res.json());
      } catch { /* offline — show experiment data only */ }
      finally { setLoading(false); }
    })();
  }, []);

  /* ── Derived data ── */

  // Role-strategy cards, sorted
  const cards = api?.active_versions || [];
  const cardsByRole = useMemo(() => {
    const map: Record<string, StrategyCard> = {};
    for (const c of cards) map[c.role] = c;
    return map;
  }, [cards]);

  // Knowledge base stats
  const knowledge = api?.knowledge || [];
  const knowledgeByRole = useMemo(() => {
    const map: Record<string, KnowledgeDoc[]> = {};
    for (const k of knowledge) {
      const r = k.role;
      if (!map[r]) map[r] = [];
      map[r].push(k);
    }
    return map;
  }, [knowledge]);
  const activeCount = knowledge.filter(k => k.status === "active" || k.status === "candidate").length;
  const deprecatedCount = knowledge.filter(k => k.status === "deprecated").length;
  const avgQuality = knowledge.length
    ? knowledge.reduce((s, k) => s + k.quality_score, 0) / knowledge.length
    : 0;

  // Per-role strategy effectiveness: usage_count + success/failure ratio
  const roleStrategyStats = useMemo(() => {
    const map: Record<string, { usage: number; success: number; failure: number; active_docs: number }> = {};
    for (const k of knowledge) {
      const r = k.role;
      if (!map[r]) map[r] = { usage: 0, success: 0, failure: 0, active_docs: 0 };
      map[r].usage += k.usage_count || 0;
      map[r].success += k.success_count || 0;
      map[r].failure += k.failure_count || 0;
      if (k.status === "active" || k.status === "candidate") map[r].active_docs++;
    }
    return map;
  }, [knowledge]);

  // Acceptance
  const acceptance = api?.acceptance_metrics || [];
  const trackB = acceptance.filter(m => m.track === "B");
  const trackC = acceptance.filter(m => m.track === "C");

  // Tournaments (A/B comparisons)
  const tournaments = api?.tournaments || [];

  // Experiment ablation effects
  const tcVsBaseline = deltaNum(EXPERIMENT.trackc_only.wolf, EXPERIMENT.baseline.wolf);
  const antiVsBaseline = deltaNum(EXPERIMENT.anti_only.wolf, EXPERIMENT.baseline.wolf);
  const bothVsAnti = deltaNum(EXPERIMENT.both.wolf, EXPERIMENT.anti_only.wolf);

  return (
    <main className="min-h-screen px-5 py-6" style={{ background: "var(--color-bg)" }}>
      <div className="mx-auto max-w-7xl space-y-5">
        {/* Header */}
        <header className="flex flex-wrap items-center justify-between gap-3 pb-2">
          <div>
            <h1 className="text-2xl font-bold text-textPrimary">{t("策略进化", "Strategy Evolution")}</h1>
            <p className="mt-0.5 text-xs text-text-sub">{META}</p>
          </div>
          <Link href="/" className="rounded-button border px-3 py-1.5 text-sm text-textPrimary" style={{ borderColor: "var(--color-border)" }}>
            {t("大厅", "Lobby")}
          </Link>
        </header>

        {/* ══════════════════════════════════════════════════
            1. ABLATION — 消融实验
            ══════════════════════════════════════════════════ */}
        <section className="rounded-lg border p-5" style={{ borderColor: "var(--color-border)", background: "var(--color-card)" }}>
          <h2 className="mb-1 text-base font-semibold text-textPrimary">{t("消融实验", "Ablation Study")}</h2>
          <p className="mb-4 text-xs text-text-sub">
            {t("逐层叠加，测量每一层对狼人胜率的独立贡献", "Layer-by-layer ablation measuring each component's independent contribution to wolf win rate")}
          </p>

          {/* Visual: stacked horizontal bars showing each layer's effect */}
          <div className="mb-5">
            <div className="space-y-2">
              {(["baseline", "anti_only", "trackc_only", "both"] as const).map((tier, i) => {
                const d = EXPERIMENT[tier];
                const x = EXPERIMENT.baseline;
                const wolfDelta = tier === "baseline" ? null : deltaNum(d.wolf, x.wolf);
                const prevTier = i > 0 ? (["baseline", "anti_only", "trackc_only", "both"] as const)[i - 1] : null;
                const stackedDelta = prevTier ? deltaNum(d.wolf, EXPERIMENT[prevTier].wolf) : null;
                const c = EXPERIMENT_TIERS[tier];
                return (
                  <div key={tier} className="flex items-center gap-3">
                    <div className="w-36 shrink-0 text-right">
                      <span className="text-sm font-medium text-textPrimary">{c.name}</span>
                      <span className="ml-1.5 text-[11px] text-text-sub">{c.desc}</span>
                    </div>
                    <div className="flex-1">
                      <div className="relative h-8 rounded" style={{ background: "rgba(255,255,255,0.05)" }}>
                        {/* baseline bar */}
                        <div className="absolute inset-y-0 left-0 rounded bg-text-sub/20" style={{ width: `${d.wolf}%` }} />
                        {/* incremental bar: stacked on top of previous tier specifically for wolf */}
                        <div className="absolute inset-y-0 left-0 rounded" style={{
                          width: `${d.wolf}%`,
                          background: i === 0 ? "#6b7280" : i === 1 ? "#f59e0b" : i === 2 ? "#3b82f6" : "#8b5cf6",
                          opacity: 0.75,
                        }} />
                      </div>
                    </div>
                    <div className="w-12 text-right font-mono text-sm font-semibold">{d.wolf}%</div>
                    <div className="w-24 text-right font-mono text-xs" style={{ color: wolfDelta === null ? "transparent" : wolfDelta >= 0 ? "var(--color-success)" : "var(--color-danger)" }}>
                      {wolfDelta !== null ? `${delta(d.wolf, x.wolf)} vs baseline` : ""}
                    </div>
                    <div className="w-20 text-right font-mono text-[11px] text-text-sub">
                      {stackedDelta !== null ? `+${stackedDelta.toFixed(1)}%` : ""}
                    </div>
                  </div>
                );
              })}
            </div>
            <p className="mt-2 text-right text-[11px] text-text-sub/60">{t("黑底 = baseline，彩色 = 累计；最右列为逐层叠加增量", "Gray = baseline, colored = cumulative; rightmost = per-layer increment")}</p>
          </div>

          {/* Ablation table */}
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-xs uppercase tracking-wide text-text-sub" style={{ borderColor: "var(--color-border)" }}>
                  <th className="py-2 text-left">{t("配置", "Layer")}</th>
                  <th className="py-2 text-right">{t("局数", "Games")}</th>
                  <th className="py-2 text-right">{t("失败", "Failed")}</th>
                  <th className="py-2 text-right">{t("好人胜率", "Village WR")}</th>
                  <th className="py-2 text-right">{t("狼人胜率", "Wolf WR")}</th>
                  <th className="py-2 text-right">{t("vs Baseline Δ", "vs Baseline Δ")}</th>
                  <th className="py-2 text-right">{t("逐层 Δ", "Layer Δ")}</th>
                </tr>
              </thead>
              <tbody>
                {(["baseline", "anti_only", "trackc_only", "both"] as const).map((tier, i) => {
                  const d = EXPERIMENT[tier];
                  const prevTier = i > 0 ? (["baseline", "anti_only", "trackc_only", "both"] as const)[i - 1] : null;
                  return (
                    <tr key={tier} className="border-b" style={{ borderColor: "var(--color-border)" }}>
                      <td className="py-2 text-xs">
                        <span className="font-medium">{EXPERIMENT_TIERS[tier].name}</span>
                        <span className="ml-1 text-text-sub/60">{EXPERIMENT_TIERS[tier].desc}</span>
                      </td>
                      <td className="py-2 text-right font-mono text-xs">{d.games}</td>
                      <td className="py-2 text-right font-mono text-xs text-text-sub">{d.failed}</td>
                      <td className="py-2 text-right font-mono text-xs">{d.village}%</td>
                      <td className="py-2 text-right font-mono text-xs font-semibold">{d.wolf}%</td>
                      <td className="py-2 text-right font-mono text-xs" style={{ color: tier === "baseline" ? "transparent" : d.wolf >= EXPERIMENT.baseline.wolf ? "var(--color-success)" : "var(--color-danger)" }}>
                        {tier === "baseline" ? "-" : delta(d.wolf, EXPERIMENT.baseline.wolf)}
                      </td>
                      <td className="py-2 text-right font-mono text-xs text-text-sub">
                        {prevTier ? delta(d.wolf, EXPERIMENT[prevTier].wolf) : "-"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>

        {/* ══════════════════════════════════════════════════
            2. STRATEGY CARDS — 策略卡片
            ══════════════════════════════════════════════════ */}
        <section className="rounded-lg border p-5" style={{ borderColor: "var(--color-border)", background: "var(--color-card)" }}>
          <h2 className="mb-3 text-base font-semibold text-textPrimary">
            {t("活跃策略卡片", "Active Strategy Cards")}
            <span className="ml-2 text-xs font-normal text-text-sub">{cards.length} cards</span>
          </h2>
          {loading ? (
            <p className="text-xs text-text-sub">{t("加载中...", "Loading...")}</p>
          ) : cards.length === 0 ? (
            <p className="text-xs text-text-sub">{t("暂无策略卡片，运行对局并完成复盘后生成", "No strategy cards yet. Run games and complete post-game analysis to generate.")}</p>
          ) : (
            <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
              {cards.map((card) => (
                <div key={card.card_id} className="rounded-lg border p-4" style={{ borderColor: "var(--color-border)", background: "rgba(255,255,255,0.025)" }}>
                  {/* Header */}
                  <div className="mb-3 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="h-2.5 w-2.5 rounded-full" style={{ background: CARD_COLORS[card.role] || "#9ca3af" }} />
                      <span className="text-sm font-semibold text-textPrimary">{t(card.role, card.role)}</span>
                      <span className="rounded px-1.5 py-0.5 text-[10px] text-text-sub" style={{ background: "rgba(255,255,255,0.06)" }}>{card.version}</span>
                    </div>
                    <span className="text-[10px] text-text-sub">{card.status}</span>
                  </div>
                  {/* Goal */}
                  <p className="mb-3 text-xs text-text-sub">{card.goal}</p>
                  {/* Policies */}
                  <div className="space-y-2">
                    {card.speech_policy?.length > 0 && (
                      <div>
                        <span className="text-[10px] font-semibold uppercase text-text-sub/60">{t("发言策略", "Speech")}</span>
                        <ul className="mt-0.5 list-inside list-disc space-y-0.5">
                          {card.speech_policy.slice(0, 2).map((p, i) => <li key={i} className="text-[11px] text-textPrimary">{p}</li>)}
                        </ul>
                      </div>
                    )}
                    {card.vote_policy?.length > 0 && (
                      <div>
                        <span className="text-[10px] font-semibold uppercase text-text-sub/60">{t("投票策略", "Vote")}</span>
                        <ul className="mt-0.5 list-inside list-disc space-y-0.5">
                          {card.vote_policy.slice(0, 2).map((p, i) => <li key={i} className="text-[11px] text-textPrimary">{p}</li>)}
                        </ul>
                      </div>
                    )}
                    {card.skill_policy?.length > 0 && (
                      <div>
                        <span className="text-[10px] font-semibold uppercase text-text-sub/60">{t("技能策略", "Skill")}</span>
                        <ul className="mt-0.5 list-inside list-disc space-y-0.5">
                          {card.skill_policy.slice(0, 2).map((p, i) => <li key={i} className="text-[11px] text-textPrimary">{p}</li>)}
                        </ul>
                      </div>
                    )}
                  </div>
                  {/* Risk rules */}
                  {card.risk_rules?.length > 0 && (
                    <div className="mt-3 rounded border border-warning/30 px-2.5 py-2" style={{ background: "rgba(245,158,11,0.06)" }}>
                      <span className="text-[10px] font-semibold text-warning">{t("风险规避", "Risk Rules")}</span>
                      <ul className="mt-0.5 list-inside list-disc space-y-0.5">
                        {card.risk_rules.slice(0, 2).map((r, i) => <li key={i} className="text-[11px] text-text-sub">{r}</li>)}
                      </ul>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>

        {/* ══════════════════════════════════════════════════
            3. PER-ROLE STRATEGY IMPACT
            ══════════════════════════════════════════════════ */}
        <section className="rounded-lg border p-5" style={{ borderColor: "var(--color-border)", background: "var(--color-card)" }}>
          <h2 className="mb-3 text-base font-semibold text-textPrimary">
            {t("单角色策略效果", "Per-Role Strategy Impact")}
          </h2>
          <p className="mb-4 text-xs text-text-sub">
            {t("每个角色的策略检索使用量、成功率、活跃文档数。usage = 对局中检索到该角色策略的总次数", "Per-role strategy retrieval usage, success rate, and active docs. usage = total times this role's strategies were retrieved during games.")}
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-xs uppercase tracking-wide text-text-sub" style={{ borderColor: "var(--color-border)" }}>
                  <th className="py-2 text-left">{t("角色", "Role")}</th>
                  <th className="py-2 text-right">{t("检索次数", "Retrievals")}</th>
                  <th className="py-2 text-right">{t("成功", "Success")}</th>
                  <th className="py-2 text-right">{t("失败", "Failure")}</th>
                  <th className="py-2 text-right">{t("成功率", "Hit Rate")}</th>
                  <th className="py-2 text-right">{t("活跃文档", "Active Docs")}</th>
                  <th className="py-2 text-right">{t("有策略卡", "Card")}</th>
                  <th className="py-2 text-right">{t("狼人胜率 baseline → both", "Wolf WR baseline → both")}</th>
                </tr>
              </thead>
              <tbody>
                {["Seer", "Witch", "Hunter", "Guard", "Villager", "Werewolf"].map((role) => {
                  const stats = roleStrategyStats[role] || { usage: 0, success: 0, failure: 0, active_docs: 0 };
                  const hitRate = stats.usage > 0 ? stats.success / stats.usage : 0;
                  const hasCard = role in cardsByRole;
                  // Role wolf WR: same as faction WR (good roles share village WR, wolf role = wolf WR)
                  const wolfWR = role === "Werewolf"
                    ? `${EXPERIMENT.baseline.wolf}% → ${EXPERIMENT.both.wolf}% (${delta(EXPERIMENT.both.wolf, EXPERIMENT.baseline.wolf)})`
                    : "-";
                  return (
                    <tr key={role} className="border-b" style={{ borderColor: "var(--color-border)" }}>
                      <td className="py-2">
                        <span className="inline-flex items-center gap-1.5">
                          <span className="h-2 w-2 rounded-full" style={{ background: CARD_COLORS[role] || "#9ca3af" }} />
                          <span className="text-xs font-medium">{t(role, role)}</span>
                        </span>
                      </td>
                      <td className="py-2 text-right font-mono text-xs">{stats.usage > 0 ? stats.usage.toLocaleString() : "-"}</td>
                      <td className="py-2 text-right font-mono text-xs text-success">{stats.success > 0 ? stats.success.toLocaleString() : "-"}</td>
                      <td className="py-2 text-right font-mono text-xs text-text-sub">{stats.failure > 0 ? stats.failure.toLocaleString() : "-"}</td>
                      <td className="py-2 text-right font-mono text-xs" style={{ color: hitRate >= 0.3 ? "var(--color-success)" : hitRate > 0 ? "var(--color-warning, #f59e0b)" : "var(--color-text-sub)" }}>
                        {stats.usage > 0 ? `${(hitRate * 100).toFixed(1)}%` : "-"}
                      </td>
                      <td className="py-2 text-right font-mono text-xs">{stats.active_docs > 0 ? stats.active_docs : "-"}</td>
                      <td className="py-2 text-center">
                        {hasCard ? <span className="text-xs text-success">Yes</span> : <span className="text-xs text-text-sub">-</span>}
                      </td>
                      <td className="py-2 text-right font-mono text-[11px] text-text-sub">{wolfWR}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>

        {/* ══════════════════════════════════════════════════
            4. KNOWLEDGE BASE — 知识库条目
            ══════════════════════════════════════════════════ */}
        <section className="rounded-lg border p-5" style={{ borderColor: "var(--color-border)", background: "var(--color-card)" }}>
          <h2 className="mb-1 text-base font-semibold text-textPrimary">
            {t("知识库", "Knowledge Base")}
            <span className="ml-2 text-xs font-normal text-text-sub">
              {knowledge.length} total · {activeCount} active · {deprecatedCount} deprecated · avg quality {avgQuality.toFixed(2)}
            </span>
          </h2>
          <p className="mb-4 text-xs text-text-sub">
            {t("对局复盘后自动提炼的策略知识。每条知识有使用次数和成功/失败计数，低质量或被证伪的知识会标记为 deprecated。", "Strategy knowledge auto-extracted from post-game analysis. Each entry tracks usage and success/failure counts. Low-quality or falsified entries are deprecated.")}
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-xs uppercase tracking-wide text-text-sub" style={{ borderColor: "var(--color-border)" }}>
                  <th className="py-2 text-left">{t("角色", "Role")}</th>
                  <th className="py-2 text-left">{t("阶段", "Phase")}</th>
                  <th className="py-2 text-left">{t("模式 / 行动", "Pattern / Action")}</th>
                  <th className="py-2 text-right">{t("质量", "Quality")}</th>
                  <th className="py-2 text-right">{t("使用", "Used")}</th>
                  <th className="py-2 text-right">{t("成功", "OK")}</th>
                  <th className="py-2 text-right">{t("失败", "Fail")}</th>
                  <th className="py-2 text-right">{t("状态", "Status")}</th>
                </tr>
              </thead>
              <tbody>
                {knowledge.slice(0, 30).map((k) => (
                  <tr key={k.doc_id} className="border-b" style={{ borderColor: "var(--color-border)" }}>
                    <td className="py-2">
                      <span className="inline-flex items-center gap-1.5">
                        <span className="h-2 w-2 rounded-full" style={{ background: CARD_COLORS[k.role] || "#9ca3af" }} />
                        <span className="text-xs font-medium">{k.role}</span>
                      </span>
                    </td>
                    <td className="py-2 text-xs text-text-sub">{k.phase}</td>
                    <td className="py-2 max-w-xs">
                      <p className="text-xs text-textPrimary truncate">{k.recommended_action || k.situation_pattern}</p>
                    </td>
                    <td className="py-2 text-right font-mono text-xs" style={{ color: k.quality_score >= 0.7 ? "var(--color-success)" : k.quality_score >= 0.4 ? "var(--color-warning, #f59e0b)" : "var(--color-text-sub)" }}>
                      {k.quality_score.toFixed(2)}
                    </td>
                    <td className="py-2 text-right font-mono text-xs">{k.usage_count}</td>
                    <td className="py-2 text-right font-mono text-xs text-success">{k.success_count}</td>
                    <td className="py-2 text-right font-mono text-xs text-text-sub">{k.failure_count}</td>
                    <td className="py-2 text-right">
                      <span className={`rounded px-1.5 py-0.5 text-[10px] ${k.status === "active" ? "text-success" : k.status === "deprecated" ? "text-text-sub/50" : "text-warning"}`}>
                        {k.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* ══════════════════════════════════════════════════
            5. B/C ACCEPTANCE
            ══════════════════════════════════════════════════ */}
        {acceptance.length > 0 && (
          <section className="rounded-lg border p-5" style={{ borderColor: "var(--color-border)", background: "var(--color-card)" }}>
            <h2 className="mb-3 text-base font-semibold text-textPrimary">
              {t("B/C 验收", "B/C Acceptance")}
              {api?.acceptance_audit && (
                <span className={`ml-2 text-xs ${api.acceptance_audit.passed ? "text-success" : "text-danger"}`}>
                  {Math.round((api.acceptance_audit.overall_success_rate || 0) * 100)}%
                </span>
              )}
            </h2>
            <div className="grid gap-4 md:grid-cols-2">
              {([trackB, trackC] as const).map((metrics, i) => (
                <div key={i}>
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-sub">
                    {i === 0 ? "Track B — 反模式" : "Track C — 策略检索"}
                  </p>
                  <div className="space-y-2">
                    {metrics.map((m) => (
                      <div key={m.step_id} className="rounded border p-2.5" style={{ borderColor: "var(--color-border)", background: "rgba(255,255,255,0.025)" }}>
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0">
                            <p className="text-xs font-medium text-textPrimary">{m.step_id}</p>
                            <p className="mt-0.5 line-clamp-1 text-[10px] text-text-sub">{m.name}</p>
                          </div>
                          <span className={m.passed ? "text-xs font-semibold text-success" : "text-xs font-semibold text-danger"}>
                            {Math.round(m.success_rate * 100)}%
                          </span>
                        </div>
                        <div className="mt-1 h-2 overflow-hidden rounded-full" style={{ background: "rgba(255,255,255,0.06)" }}>
                          <div className={`h-full rounded-full ${m.passed ? "bg-success" : "bg-danger"}`}
                            style={{ width: `${Math.max(2, Math.min(100, m.success_rate * 100))}%` }} />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* ══════════════════════════════════════════════════
            6. A/B TOURNAMENTS
            ══════════════════════════════════════════════════ */}
        {tournaments.length > 0 && (
          <section className="rounded-lg border p-5" style={{ borderColor: "var(--color-border)", background: "var(--color-card)" }}>
            <h2 className="mb-3 text-base font-semibold text-textPrimary">
              {t("A/B 对比实验", "A/B Tournaments")}
              <span className="ml-2 text-xs font-normal text-text-sub">{tournaments.length} completed</span>
            </h2>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-xs uppercase tracking-wide text-text-sub" style={{ borderColor: "var(--color-border)" }}>
                    <th className="py-2 text-left">{t("基线 → 候选", "Baseline → Candidate")}</th>
                    <th className="py-2 text-right">{t("候选胜率", "Candidate WR")}</th>
                    <th className="py-2 text-right">{t("候选评分", "Candidate Score")}</th>
                    <th className="py-2 text-right">{t("致命失误/局", "Mistakes/Game")}</th>
                    <th className="py-2 text-right">{t("决策", "Decision")}</th>
                  </tr>
                </thead>
                <tbody>
                  {tournaments.map((t) => {
                    const c = t.comparison || {};
                    return (
                      <tr key={t.tournament_id} className="border-b" style={{ borderColor: "var(--color-border)" }}>
                        <td className="py-2 text-xs font-mono text-textPrimary">{t.baseline_version} → {t.candidate_version}</td>
                        <td className="py-2 text-right font-mono text-xs">{c.candidate_camp_win_rate != null ? `${(c.candidate_camp_win_rate * 100).toFixed(1)}%` : "-"}</td>
                        <td className="py-2 text-right font-mono text-xs">{c.candidate_target_role_avg_score?.toFixed(1) || "-"}</td>
                        <td className="py-2 text-right font-mono text-xs">{c.candidate_critical_mistakes_per_game?.toFixed(2) || "-"}</td>
                        <td className="py-2 text-right text-xs">{t.decision?.action || t.status || "-"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        )}
      </div>
    </main>
  );
}
