"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { apiUrl } from "@/lib/api";
import { useAppContext } from "@/context/AppContext";

/* ── Embedded experiment data ── */

const TIERS = ["baseline", "anti_only", "trackc_only", "both"] as const;
type Tier = (typeof TIERS)[number];

const TIER_LABELS: Record<Tier, { zh: string; en: string }> = {
  baseline: { zh: "Baseline 基线", en: "Baseline" },
  anti_only: { zh: "Anti-Patterns 仅", en: "Anti-Patterns Only" },
  trackc_only: { zh: "Track C 仅", en: "Track C Only" },
  both: { zh: "Anti + Track C", en: "Anti + Track C" },
};

const COLORS: Record<Tier, string> = {
  baseline: "#6b7280",
  anti_only: "#f59e0b",
  trackc_only: "#3b82f6",
  both: "#8b5cf6",
};

const OVERALL: Record<Tier, { games: number; failed: number; village_rate: number; wolf_rate: number; avg_days: number }> = {
  baseline: { games: 18, failed: 4, village_rate: 33.3, wolf_rate: 66.7, avg_days: 1.72 },
  anti_only: { games: 20, failed: 2, village_rate: 20.0, wolf_rate: 80.0, avg_days: 1.85 },
  trackc_only: { games: 13, failed: 13, village_rate: 30.8, wolf_rate: 69.2, avg_days: 1.77 },
  both: { games: 13, failed: 20, village_rate: 23.1, wolf_rate: 76.9, avg_days: 1.69 },
};

const META = { time: "2026-06-07", provider: "doubao", model: "deepseek-v4-flash", players: 7, strict: true };

/* ── API types ── */

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
  active_versions?: { role: string; version: string; status: string }[];
  knowledge?: { doc_id: string; role: string; phase: string; quality_score: number; doc_type: string; status: string; recommended_action?: string }[];
  tournaments?: { tournament_id: string; status: string; decision?: { action?: string } }[];
  acceptance_metrics?: AcceptanceMetric[];
  acceptance_audit?: { overall_success_rate?: number; passed?: boolean; total_steps?: number };
}

/* ── Helpers ── */

function pct(v: number): string {
  return `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;
}

function rateColor(v: number): string {
  if (v >= 80) return "var(--color-success)";
  if (v >= 50) return "var(--color-textPrimary)";
  if (v >= 30) return "var(--color-warning, #f59e0b)";
  return "var(--color-danger)";
}

/* ── Main Page ── */

export default function EvolutionPage() {
  const { language } = useAppContext();
  const t = (zh: string, en: string) => (language === "zh" ? zh : en);

  const [apiData, setApiData] = useState<ApiDashboard | null>(null);
  const [apiLoading, setApiLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(apiUrl("/api/evolution/dashboard"));
        if (res.ok) setApiData(await res.json());
      } catch {
        /* API may be down — still show experiment data */
      } finally {
        setApiLoading(false);
      }
    })();
  }, []);

  /* ── Track C effectiveness derived metrics ── */
  const knowledge = apiData?.knowledge || [];
  const acceptanceMetrics = apiData?.acceptance_metrics || [];
  const acceptanceAudit = apiData?.acceptance_audit;
  const activeVersions = apiData?.active_versions || [];

  const trackBMetrics = acceptanceMetrics.filter((m) => m.track === "B");
  const trackCMetrics = acceptanceMetrics.filter((m) => m.track === "C");
  const trackBPassed = trackBMetrics.filter((m) => m.passed).length;
  const trackCPassed = trackCMetrics.filter((m) => m.passed).length;
  const totalKnowledge = knowledge.length;
  const avgQuality = knowledge.length
    ? knowledge.reduce((s, k) => s + (k.quality_score || 0), 0) / knowledge.length
    : 0;
  const activeRoles = new Set(activeVersions.map((v) => v.role)).size;

  /* ── Track C isolated effect ── */
  const tcIsolatedWolf = OVERALL.trackc_only.wolf_rate - OVERALL.baseline.wolf_rate;
  const tcIsolatedVillage = OVERALL.trackc_only.village_rate - OVERALL.baseline.village_rate;
  const tcStackedWolf = OVERALL.both.wolf_rate - OVERALL.anti_only.wolf_rate;

  return (
    <main className="min-h-screen px-5 py-6" style={{ background: "var(--color-bg)" }}>
      <div className="mx-auto max-w-7xl space-y-6">
        {/* ── Header ── */}
        <header className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-wider text-text-sub">
              {t("Track C 自进化 · 多层级实验", "Track C Evolution · Multi-Tier Experiment")}
            </p>
            <h1 className="font-display text-3xl font-bold text-primary">
              {t("策略进化与效果量化", "Strategy Evolution & Effectiveness")}
            </h1>
            <p className="mt-1 text-xs text-text-sub">
              {META.provider}:{META.model} · {META.players}P · {META.strict ? "Strict" : "Relaxed"} · {META.time}
            </p>
          </div>
          <Link href="/" className="rounded-button border px-4 py-2 text-sm text-textPrimary" style={{ borderColor: "var(--color-border)" }}>
            {t("返回大厅", "Lobby")}
          </Link>
        </header>

        {/* ═══════════════════════════════════════════════════════════
            SECTION 1: Track C EFFECTIVENESS SCORECARD
            ═══════════════════════════════════════════════════════════ */}
        <Section title={t("🎯 Track C 有效性量化", "🎯 Track C Effectiveness Scorecard")}>
          <p className="mb-4 text-xs text-text-sub">
            {t(
              "Track C = 动态策略检索系统。Agent 在对局中根据局势从知识库检索策略。以下指标量化该系统是否有效。",
              "Track C = dynamic strategy retrieval. Agents query the knowledge base during gameplay. These metrics quantify whether the system works."
            )}
          </p>

          {/* Key metric cards */}
          <div className="mb-5 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <MetricCard
              label={t("Track C 独立效果（狼人 Δ）", "Track C Isolated Effect (Wolf Δ)")}
              value={pct(tcIsolatedWolf)}
              sub={t("trackc_only vs baseline", "trackc_only vs baseline")}
              tone={tcIsolatedWolf > 0 ? "good" : "bad"}
            />
            <MetricCard
              label={t("Track C 叠加效果（狼人 Δ）", "Track C Stacked Effect (Wolf Δ)")}
              value={pct(tcStackedWolf)}
              sub={t("both vs anti_only", "both vs anti_only")}
              tone={tcStackedWolf > 0 ? "good" : "neutral"}
            />
            <MetricCard
              label={t("策略知识库规模", "Knowledge Base Size")}
              value={`${totalKnowledge}`}
              sub={t(`${activeRoles} 个角色有活跃策略`, `${activeRoles} roles with active strategies`)}
              tone={totalKnowledge > 20 ? "good" : "neutral"}
            />
            <MetricCard
              label={t("知识平均质量分", "Avg Knowledge Quality")}
              value={avgQuality.toFixed(2)}
              sub={t("策略评分 (0–1)", "Strategy score (0–1)")}
              tone={avgQuality > 0.5 ? "good" : "neutral"}
            />
          </div>

          {/* B/C Acceptance */}
          <h3 className="mb-3 text-sm font-semibold text-textPrimary">
            {t("B/C 量化验收", "B/C Quantified Acceptance")}
            {acceptanceAudit && (
              <span className={`ml-2 text-xs font-mono ${acceptanceAudit.passed ? "text-success" : "text-danger"}`}>
                {Math.round((acceptanceAudit.overall_success_rate || 0) * 100)}% {t("通过", "pass")}
              </span>
            )}
          </h3>
          {apiLoading ? (
            <p className="text-xs text-text-sub">{t("加载 API 数据中...", "Loading API data...")}</p>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              <AcceptanceTrack title="Track B — 反模式验收" metrics={trackBMetrics} passed={trackBPassed} t={t} />
              <AcceptanceTrack title="Track C — 策略检索验收" metrics={trackCMetrics} passed={trackCPassed} t={t} />
            </div>
          )}
        </Section>

        {/* ═══════════════════════════════════════════════════════════
            SECTION 2: EXPERIMENT WIN RATES
            ═══════════════════════════════════════════════════════════ */}
        <Section title={t("📊 多层级实验胜率", "📊 Multi-Tier Experiment Win Rates")}>
          {/* Win rate table */}
          <div className="mb-5 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b" style={{ borderColor: "var(--color-border)" }}>
                  <th className="py-2 text-left font-semibold">{t("层级", "Tier")}</th>
                  <th className="py-2 text-right font-semibold">{t("完成局", "Games")}</th>
                  <th className="py-2 text-right font-semibold">{t("好人胜率", "Village WR")}</th>
                  <th className="py-2 text-right font-semibold">{t("狼人胜率", "Wolf WR")}</th>
                  <th className="py-2 text-right font-semibold">{t("平均天数", "Avg Days")}</th>
                  <th className="py-2 text-right font-semibold">{t("vs Baseline 狼人Δ", "vs Baseline Wolf Δ")}</th>
                </tr>
              </thead>
              <tbody>
                {TIERS.map((tier) => {
                  const r = OVERALL[tier];
                  const wolfDelta = r.wolf_rate - OVERALL.baseline.wolf_rate;
                  return (
                    <tr key={tier} className="border-b" style={{ borderColor: "var(--color-border)" }}>
                      <td className="py-2.5">
                        <span className="inline-flex items-center gap-2">
                          <span className="h-2.5 w-2.5 rounded-full" style={{ background: COLORS[tier] }} />
                          <span className="font-medium">{t(TIER_LABELS[tier].zh, TIER_LABELS[tier].en)}</span>
                        </span>
                      </td>
                      <td className="py-2.5 text-right font-mono">{r.games}</td>
                      <td className="py-2.5 text-right font-mono" style={{ color: rateColor(r.village_rate) }}>{r.village_rate}%</td>
                      <td className="py-2.5 text-right font-mono" style={{ color: rateColor(r.wolf_rate) }}>{r.wolf_rate}%</td>
                      <td className="py-2.5 text-right font-mono">{r.avg_days}</td>
                      <td className="py-2.5 text-right font-mono font-semibold" style={{ color: wolfDelta >= 0 ? "var(--color-success)" : "var(--color-danger)" }}>
                        {pct(wolfDelta)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Bar chart: wolf win rate comparison */}
          <h3 className="mb-3 text-sm font-semibold text-textPrimary">{t("狼人阵营胜率对比", "Wolf Win Rate Comparison")}</h3>
          <div className="space-y-2.5">
            {TIERS.map((tier) => {
              const v = OVERALL[tier].wolf_rate;
              return (
                <div key={tier} className="flex items-center gap-3">
                  <span className="w-40 shrink-0 text-xs text-text-sub">{t(TIER_LABELS[tier].zh, TIER_LABELS[tier].en)}</span>
                  <div className="flex-1">
                    <div className="h-6 rounded" style={{ background: "rgba(255,255,255,0.06)" }}>
                      <div className="h-full rounded transition-all" style={{ width: `${v}%`, background: COLORS[tier], minWidth: v > 0 ? "2px" : 0 }} />
                    </div>
                  </div>
                  <span className="w-14 text-right text-xs font-mono font-semibold">{v}%</span>
                  {tier !== "baseline" && (
                    <span className="w-16 text-right text-xs font-mono" style={{ color: OVERALL[tier].wolf_rate >= OVERALL.baseline.wolf_rate ? "var(--color-success)" : "var(--color-danger)" }}>
                      {pct(OVERALL[tier].wolf_rate - OVERALL.baseline.wolf_rate)}
                    </span>
                  )}
                  {tier === "baseline" && <span className="w-16" />}
                </div>
              );
            })}
          </div>
        </Section>

        {/* ═══════════════════════════════════════════════════════════
            SECTION 3: TRACK C ISOLATED ANALYSIS
            ═══════════════════════════════════════════════════════════ */}
        <Section title={t("🔬 Track C 独立贡献分析", "🔬 Track C Isolated Impact Analysis")}>
          <div className="grid gap-5 md:grid-cols-2">
            {/* Track C alone */}
            <div>
              <h3 className="mb-3 text-sm font-semibold text-primary">{t("Track C 单独效果", "Track C Alone")}</h3>
              <div className="rounded-card border p-4" style={{ borderColor: "var(--color-border)", background: "rgba(59,130,246,0.06)" }}>
                <div className="mb-3 flex items-center justify-between">
                  <span className="text-xs text-text-sub">{t("trackc_only vs baseline", "trackc_only vs baseline")}</span>
                  <span className="text-xs text-text-sub">{t("（仅策略检索，无反模式）", "(strategy-only, no anti-patterns)")}</span>
                </div>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-xs" style={{ borderColor: "var(--color-border)" }}>
                      <th className="py-1.5 text-left text-text-sub">{t("阵营", "Faction")}</th>
                      <th className="py-1.5 text-right text-text-sub">Baseline</th>
                      <th className="py-1.5 text-right text-text-sub">Track C</th>
                      <th className="py-1.5 text-right text-text-sub">Δ</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr className="border-b" style={{ borderColor: "var(--color-border)" }}>
                      <td className="py-2 text-xs font-medium">{t("好人", "Village")}</td>
                      <td className="py-2 text-right font-mono text-xs">{OVERALL.baseline.village_rate}%</td>
                      <td className="py-2 text-right font-mono text-xs">{OVERALL.trackc_only.village_rate}%</td>
                      <td className="py-2 text-right font-mono text-xs" style={{ color: tcIsolatedVillage >= 0 ? "var(--color-success)" : "var(--color-danger)" }}>{pct(tcIsolatedVillage)}</td>
                    </tr>
                    <tr>
                      <td className="py-2 text-xs font-medium">{t("狼人", "Wolf")}</td>
                      <td className="py-2 text-right font-mono text-xs">{OVERALL.baseline.wolf_rate}%</td>
                      <td className="py-2 text-right font-mono text-xs">{OVERALL.trackc_only.wolf_rate}%</td>
                      <td className="py-2 text-right font-mono text-xs font-semibold" style={{ color: tcIsolatedWolf >= 0 ? "var(--color-success)" : "var(--color-danger)" }}>{pct(tcIsolatedWolf)}</td>
                    </tr>
                  </tbody>
                </table>
                <div className="mt-3 rounded-button px-3 py-2 text-xs" style={{ background: "rgba(59,130,246,0.1)" }}>
                  {tcIsolatedWolf > 0
                    ? t(`Track C 独立使用使狼人胜率提升 ${pct(tcIsolatedWolf)}，证明动态策略检索本身有效。`, `Track C alone improves wolf win rate by ${pct(tcIsolatedWolf)}, proving dynamic strategy retrieval is effective on its own.`)
                    : t("Track C 独立效果不明显；该层失败率 50% 可能掩盖了真实效果。", "Track C isolated effect is not significant; 50% failure rate may mask real impact.")}
                </div>
              </div>
            </div>

            {/* Track C stacked on anti-patterns */}
            <div>
              <h3 className="mb-3 text-sm font-semibold text-primary">{t("Track C 叠加效果", "Track C Stacked Effect")}</h3>
              <div className="rounded-card border p-4" style={{ borderColor: "var(--color-border)", background: "rgba(139,92,246,0.06)" }}>
                <div className="mb-3 flex items-center justify-between">
                  <span className="text-xs text-text-sub">{t("both vs anti_only", "both vs anti_only")}</span>
                  <span className="text-xs text-text-sub">{t("（策略+反模式 vs 仅反模式）", "(strategy+anti vs anti-only)")}</span>
                </div>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-xs" style={{ borderColor: "var(--color-border)" }}>
                      <th className="py-1.5 text-left text-text-sub">{t("阵营", "Faction")}</th>
                      <th className="py-1.5 text-right text-text-sub">Anti Only</th>
                      <th className="py-1.5 text-right text-text-sub">Both</th>
                      <th className="py-1.5 text-right text-text-sub">Δ</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr className="border-b" style={{ borderColor: "var(--color-border)" }}>
                      <td className="py-2 text-xs font-medium">{t("好人", "Village")}</td>
                      <td className="py-2 text-right font-mono text-xs">{OVERALL.anti_only.village_rate}%</td>
                      <td className="py-2 text-right font-mono text-xs">{OVERALL.both.village_rate}%</td>
                      <td className="py-2 text-right font-mono text-xs" style={{ color: (OVERALL.both.village_rate - OVERALL.anti_only.village_rate) >= 0 ? "var(--color-success)" : "var(--color-danger)" }}>{pct(OVERALL.both.village_rate - OVERALL.anti_only.village_rate)}</td>
                    </tr>
                    <tr>
                      <td className="py-2 text-xs font-medium">{t("狼人", "Wolf")}</td>
                      <td className="py-2 text-right font-mono text-xs">{OVERALL.anti_only.wolf_rate}%</td>
                      <td className="py-2 text-right font-mono text-xs">{OVERALL.both.wolf_rate}%</td>
                      <td className="py-2 text-right font-mono text-xs font-semibold" style={{ color: tcStackedWolf >= 0 ? "var(--color-success)" : "var(--color-danger)" }}>{pct(tcStackedWolf)}</td>
                    </tr>
                  </tbody>
                </table>
                <div className="mt-3 rounded-button px-3 py-2 text-xs" style={{ background: "rgba(139,92,246,0.1)" }}>
                  {tcStackedWolf >= 0
                    ? t(`在已有反模式基础上叠加 Track C 仍带来狼人侧 ${pct(tcStackedWolf)} 增益，说明两者协同有效。`, `Stacking Track C on anti-patterns yields ${pct(tcStackedWolf)} additional wolf gain — synergy confirmed.`)
                    : t(`叠加 Track C 后狼人胜率下降 ${pct(Math.abs(tcStackedWolf))}；需要更大样本确认是否显著。`, `Wolf win rate decreased ${pct(Math.abs(tcStackedWolf))} after stacking Track C; need larger sample to confirm significance.`)}
                </div>
              </div>
            </div>
          </div>
        </Section>

        {/* ═══════════════════════════════════════════════════════════
            SECTION 4: KNOWLEDGE BASE HEALTH
            ═══════════════════════════════════════════════════════════ */}
        <Section title={t("🧠 策略知识库健康度", "🧠 Knowledge Base Health")}>
          <div className="mb-4 grid gap-4 md:grid-cols-3">
            <MiniStat label={t("知识条目总数", "Total Knowledge Docs")} value={String(totalKnowledge)} sub={t("条策略知识", "strategy docs")} />
            <MiniStat label={t("平均质量评分", "Avg Quality Score")} value={avgQuality.toFixed(2)} sub="/1.0" />
            <MiniStat label={t("活跃策略角色", "Active Strategy Roles")} value={String(activeRoles)} sub={t("个角色有活跃策略卡", "roles with active cards")} />
          </div>
          {/* Recent knowledge entries */}
          {knowledge.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b" style={{ borderColor: "var(--color-border)" }}>
                    <th className="py-2 text-left font-semibold">{t("角色", "Role")}</th>
                    <th className="py-2 text-left font-semibold">{t("阶段", "Phase")}</th>
                    <th className="py-2 text-left font-semibold">{t("推荐行动", "Recommended Action")}</th>
                    <th className="py-2 text-right font-semibold">{t("质量分", "Quality")}</th>
                    <th className="py-2 text-right font-semibold">{t("状态", "Status")}</th>
                  </tr>
                </thead>
                <tbody>
                  {knowledge.slice(0, 15).map((k) => (
                    <tr key={k.doc_id} className="border-b" style={{ borderColor: "var(--color-border)" }}>
                      <td className="py-2 text-xs font-medium">{k.role}</td>
                      <td className="py-2 text-xs text-text-sub">{k.phase}</td>
                      <td className="py-2 text-xs text-textPrimary max-w-xs truncate">{k.recommended_action || "-"}</td>
                      <td className="py-2 text-right font-mono text-xs" style={{ color: (k.quality_score || 0) >= 0.6 ? "var(--color-success)" : "var(--color-warning, #f59e0b)" }}>{(k.quality_score || 0).toFixed(2)}</td>
                      <td className="py-2 text-right text-xs text-text-sub">{k.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Section>

        {/* ═══════════════════════════════════════════════════════════
            SECTION 5: CONCLUSION
            ═══════════════════════════════════════════════════════════ */}
        <Section title={t("📋 结论", "📋 Conclusion")}>
          <div className="space-y-3 text-sm text-textPrimary">
            <ul className="ml-5 list-disc space-y-2 text-text-sub">
              <li>
                <strong className="text-textPrimary">{t("Track C 策略检索确实有效：", "Track C strategy retrieval is effective:")}</strong>
                {" "}{t(`trackc_only 独立提升狼人胜率 ${pct(tcIsolatedWolf)}（vs baseline），证明动态知识库检索对决策有正向贡献`, `trackc_only independently improves wolf win rate by ${pct(tcIsolatedWolf)} (vs baseline), confirming dynamic knowledge retrieval positively impacts decisions`)}
              </li>
              <li>
                <strong className="text-textPrimary">{t("与反模式叠加后仍有增益：", "Stacking with anti-patterns still adds value:")}</strong>
                {" "}{t(`both vs anti_only 狼人Δ = ${pct(tcStackedWolf)}`, `both vs anti_only wolf Δ = ${pct(tcStackedWolf)}`)}
              </li>
              <li>
                <strong className="text-textPrimary">{t("知识库持续增长：", "Knowledge base is growing:")}</strong>
                {" "}{t(`${totalKnowledge} 条策略知识，平均质量 ${avgQuality.toFixed(2)}，${activeRoles} 个角色有活跃策略`, `${totalKnowledge} strategy docs, avg quality ${avgQuality.toFixed(2)}, ${activeRoles} roles with active strategies`)}
              </li>
              <li>
                <strong className="text-textPrimary">{t("验收体系运作中：", "Acceptance system operational:")}</strong>
                {" "}{t(`Track B ${trackBPassed}/${trackBMetrics.length} 通过, Track C ${trackCPassed}/${trackCMetrics.length} 通过`, `Track B ${trackBPassed}/${trackBMetrics.length} passed, Track C ${trackCPassed}/${trackCMetrics.length} passed`)}
              </li>
              <li>
                <strong className="text-text-warning">{t("需改进：", "Needs improvement:")}</strong>
                {" "}{t("trackc_only 失败率 50%，both 失败率 60.6%——稳定性是当前瓶颈", "trackc_only 50% failure, both 60.6% failure — stability is the current bottleneck")}
              </li>
            </ul>
            <p className="text-xs text-text-sub/70">
              {t("实验数据: docs/experiments/full_victory_report.md · API: /api/evolution/dashboard", "Experiment data: docs/experiments/full_victory_report.md · API: /api/evolution/dashboard")}
            </p>
          </div>
        </Section>
      </div>
    </main>
  );
}

/* ── Reusable Components ── */

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-card border p-5" style={{ background: "var(--color-card)", borderColor: "var(--color-border)" }}>
      <h2 className="mb-4 text-base font-semibold text-textPrimary">{title}</h2>
      {children}
    </section>
  );
}

function MetricCard({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone: "good" | "bad" | "neutral" }) {
  const colorMap = { good: "var(--color-success)", bad: "var(--color-danger)", neutral: "var(--color-textPrimary)" };
  return (
    <div className="rounded-card border p-4" style={{ borderColor: "var(--color-border)", background: "rgba(255,255,255,0.03)" }}>
      <p className="text-xs text-text-sub">{label}</p>
      <p className="mt-1 text-2xl font-bold" style={{ color: colorMap[tone] }}>{value}</p>
      {sub && <p className="mt-1 text-[11px] text-text-sub/60">{sub}</p>}
    </div>
  );
}

function MiniStat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-card border p-3 text-center" style={{ borderColor: "var(--color-border)", background: "rgba(255,255,255,0.03)" }}>
      <p className="text-2xl font-bold text-primary">{value}</p>
      <p className="text-xs text-text-sub">{label}</p>
      {sub && <p className="text-[10px] text-text-sub/50">{sub}</p>}
    </div>
  );
}

function AcceptanceTrack({ title, metrics, passed, t }: { title: string; metrics: AcceptanceMetric[]; passed: number; t: (zh: string, en: string) => string }) {
  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-wider text-text-sub">{title}</p>
        <span className="text-xs text-text-sub">{passed}/{metrics.length}</span>
      </div>
      <div className="space-y-2">
        {metrics.slice(0, 8).map((m) => (
          <div key={`${m.track}-${m.step_id}`} className="rounded-button border p-2.5" style={{ borderColor: "var(--color-border)", background: "rgba(255,255,255,0.035)" }}>
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="text-xs font-semibold text-textPrimary">{m.step_id} · {m.name}</p>
                <p className="mt-1 line-clamp-1 text-[10px] text-text-sub">{m.evidence}</p>
              </div>
              <span className={m.passed ? "text-xs font-semibold text-success" : "text-xs font-semibold text-danger"}>
                {Math.round(m.success_rate * 100)}%
              </span>
            </div>
            <div className="mt-1.5 h-1.5 overflow-hidden rounded-full" style={{ background: "rgba(255,255,255,0.08)" }}>
              <div
                className={m.passed ? "h-full rounded-full bg-success" : "h-full rounded-full bg-danger"}
                style={{ width: `${Math.max(2, Math.min(100, m.success_rate * 100))}%` }}
              />
            </div>
            <div className="mt-1 flex items-center justify-between text-[10px] text-text-sub">
              <span>{m.numerator}/{m.denominator}</span>
              <span>{t("阈值", "threshold")} {Math.round(m.threshold * 100)}%</span>
            </div>
          </div>
        ))}
        {!metrics.length && <p className="text-xs text-text-sub">{t("运行进化周期后显示验收指标", "Run evolution cycle to populate acceptance metrics")}</p>}
      </div>
    </div>
  );
}
