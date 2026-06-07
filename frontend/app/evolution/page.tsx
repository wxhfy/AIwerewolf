"use client";

import React from "react";
import Link from "next/link";
import { useAppContext } from "@/context/AppContext";

/* ── Embedded experiment data from docs/experiments/full_victory_report.md ── */

const TIERS = ["baseline", "anti_only", "trackc_only", "both"] as const;
type Tier = (typeof TIERS)[number];

const TIER_LABELS: Record<Tier, { zh: string; en: string }> = {
  baseline: { zh: "Baseline 基线", en: "Baseline" },
  anti_only: { zh: "Anti-Patterns 仅", en: "Anti-Patterns Only" },
  trackc_only: { zh: "Track C 仅", en: "Track C Only" },
  both: { zh: "Anti + Track C", en: "Anti + Track C" },
};

interface TierRow {
  games: number;
  failed: number;
  village_rate: number;
  wolf_rate: number;
  avg_days: number;
  llm_decisions: number;
  fallback: number;
  invalid: number;
}

const OVERALL: Record<Tier, TierRow> = {
  baseline: { games: 18, failed: 4, village_rate: 33.3, wolf_rate: 66.7, avg_days: 1.72, llm_decisions: 580, fallback: 0, invalid: 0 },
  anti_only: { games: 20, failed: 2, village_rate: 20.0, wolf_rate: 80.0, avg_days: 1.85, llm_decisions: 573, fallback: 0, invalid: 0 },
  trackc_only: { games: 13, failed: 13, village_rate: 30.8, wolf_rate: 69.2, avg_days: 1.77, llm_decisions: 363, fallback: 0, invalid: 0 },
  both: { games: 13, failed: 20, village_rate: 23.1, wolf_rate: 76.9, avg_days: 1.69, llm_decisions: 392, fallback: 0, invalid: 0 },
};

const DELTA: Record<string, { village_delta: number; wolf_delta: number; note: string }> = {
  anti_only: { village_delta: -13.3, wolf_delta: +13.3, note: "狼人提升 +13.3%" },
  trackc_only: { village_delta: -2.6, wolf_delta: +2.6, note: "狼人提升 +2.6%" },
  both: { village_delta: -10.2, wolf_delta: +10.2, note: "狼人提升 +10.2%" },
};

const ROLE_WIN_RATES: Record<string, Record<Tier, number>> = {
  Seer: { baseline: 33.3, anti_only: 20.0, trackc_only: 30.8, both: 23.1 },
  Witch: { baseline: 33.3, anti_only: 20.0, trackc_only: 30.8, both: 23.1 },
  Hunter: { baseline: 33.3, anti_only: 20.0, trackc_only: 30.8, both: 23.1 },
  Guard: { baseline: 33.3, anti_only: 20.0, trackc_only: 30.8, both: 23.1 },
  Villager: { baseline: 33.3, anti_only: 20.0, trackc_only: 30.8, both: 23.1 },
  Werewolf: { baseline: 66.7, anti_only: 80.0, trackc_only: 69.2, both: 76.9 },
};

const MBTI_WIN_RATES: Record<string, Record<Tier, { rate: number; n: number }>> = {
  ENFJ: { baseline: { rate: 33.3, n: 12 }, anti_only: { rate: 41.7, n: 12 }, trackc_only: { rate: 50.0, n: 6 }, both: { rate: 33.3, n: 9 } },
  ENFP: { baseline: { rate: 80.0, n: 5 }, anti_only: { rate: 71.4, n: 7 }, trackc_only: { rate: 66.7, n: 6 }, both: { rate: 40.0, n: 5 } },
  ENTJ: { baseline: { rate: 50.0, n: 6 }, anti_only: { rate: 33.3, n: 6 }, trackc_only: { rate: 57.1, n: 7 }, both: { rate: 80.0, n: 5 } },
  ENTP: { baseline: { rate: 25.0, n: 4 }, anti_only: { rate: 20.0, n: 5 }, trackc_only: { rate: 66.7, n: 3 }, both: { rate: 66.7, n: 3 } },
  ESFJ: { baseline: { rate: 50.0, n: 10 }, anti_only: { rate: 44.4, n: 9 }, trackc_only: { rate: 28.6, n: 7 }, both: { rate: 28.6, n: 7 } },
  ESFP: { baseline: { rate: 66.7, n: 3 }, anti_only: { rate: 25.0, n: 4 }, trackc_only: { rate: 25.0, n: 4 }, both: { rate: 25.0, n: 4 } },
  ESTJ: { baseline: { rate: 33.3, n: 6 }, anti_only: { rate: 50.0, n: 8 }, trackc_only: { rate: 16.7, n: 6 }, both: { rate: 33.3, n: 9 } },
  ESTP: { baseline: { rate: 11.1, n: 9 }, anti_only: { rate: 36.4, n: 11 }, trackc_only: { rate: 16.7, n: 6 }, both: { rate: 33.3, n: 6 } },
  INFJ: { baseline: { rate: 38.5, n: 13 }, anti_only: { rate: 50.0, n: 14 }, trackc_only: { rate: 66.7, n: 9 }, both: { rate: 45.5, n: 11 } },
  INFP: { baseline: { rate: 54.5, n: 11 }, anti_only: { rate: 25.0, n: 12 }, trackc_only: { rate: 30.0, n: 10 }, both: { rate: 37.5, n: 8 } },
  INTJ: { baseline: { rate: 38.9, n: 18 }, anti_only: { rate: 30.0, n: 20 }, trackc_only: { rate: 37.5, n: 8 }, both: { rate: 42.9, n: 7 } },
  INTP: { baseline: { rate: 50.0, n: 4 }, anti_only: { rate: 0.0, n: 5 }, trackc_only: { rate: 0.0, n: 2 }, both: { rate: 0.0, n: 1 } },
  ISFJ: { baseline: { rate: 50.0, n: 4 }, anti_only: { rate: 50.0, n: 4 }, trackc_only: { rate: 100.0, n: 1 }, both: { rate: 50.0, n: 2 } },
  ISFP: { baseline: { rate: 16.7, n: 6 }, anti_only: { rate: 16.7, n: 6 }, trackc_only: { rate: 40.0, n: 5 }, both: { rate: 33.3, n: 6 } },
  ISTJ: { baseline: { rate: 66.7, n: 12 }, anti_only: { rate: 28.6, n: 14 }, trackc_only: { rate: 40.0, n: 10 }, both: { rate: 20.0, n: 5 } },
  ISTP: { baseline: { rate: 33.3, n: 3 }, anti_only: { rate: 100.0, n: 3 }, trackc_only: { rate: 100.0, n: 1 }, both: { rate: 33.3, n: 3 } },
};

const META = {
  time: "2026-06-07 16:16",
  provider: "doubao",
  model: "deepseek-v4-flash",
  players: 7,
  strict: true,
};

/* ── Helpers ── */

const COLORS = {
  baseline: "#6b7280",
  anti_only: "#f59e0b",
  trackc_only: "#3b82f6",
  both: "#8b5cf6",
};

function deltaColor(v: number): string {
  if (v > 0) return "var(--color-success, #10b981)";
  if (v < 0) return "var(--color-danger, #ef4444)";
  return "var(--color-text-sub)";
}

/* ── Main Page ── */

export default function EvolutionPage() {
  const { language } = useAppContext();
  const t = (zh: string, en: string) => (language === "zh" ? zh : en);

  return (
    <main className="min-h-screen px-5 py-6" style={{ background: "var(--color-bg)" }}>
      <div className="mx-auto max-w-7xl space-y-6">
        {/* Header */}
        <header className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-wider text-text-sub">
              {t("多层实验报告", "Multi-Tier Experiment Report")}
            </p>
            <h1 className="font-display text-3xl font-bold text-primary">
              {t("策略进化效果", "Strategy Evolution Results")}
            </h1>
            <p className="mt-1 text-xs text-text-sub">
              {META.provider}:{META.model} · {META.players}P · {META.strict ? "Strict" : "Relaxed"} · {META.time}
            </p>
          </div>
          <Link href="/" className="rounded-button border px-4 py-2 text-sm text-textPrimary" style={{ borderColor: "var(--color-border)" }}>
            {t("返回大厅", "Lobby")}
          </Link>
        </header>

        {/* Section 1: Overall Win Rates */}
        <Section title={t("四层级整体胜率", "Overall Win Rates by Tier")}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b" style={{ borderColor: "var(--color-border)" }}>
                  <th className="py-2 text-left font-semibold">{t("层级", "Tier")}</th>
                  <th className="py-2 text-right font-semibold">{t("完成局", "Games")}</th>
                  <th className="py-2 text-right font-semibold">{t("失败", "Failed")}</th>
                  <th className="py-2 text-right font-semibold">{t("好人胜率", "Village WR")}</th>
                  <th className="py-2 text-right font-semibold">{t("狼人胜率", "Wolf WR")}</th>
                  <th className="py-2 text-right font-semibold">{t("平均天数", "Avg Days")}</th>
                  <th className="py-2 text-right font-semibold">{t("LLM 决策", "Decisions")}</th>
                  <th className="py-2 text-right font-semibold">{t("Fallback", "Fallback")}</th>
                  <th className="py-2 text-right font-semibold">{t("Invalid", "Invalid")}</th>
                </tr>
              </thead>
              <tbody>
                {TIERS.map((tier) => {
                  const r = OVERALL[tier];
                  return (
                    <tr key={tier} className="border-b" style={{ borderColor: "var(--color-border)" }}>
                      <td className="py-2.5">
                        <span className="inline-flex items-center gap-2">
                          <span className="h-2.5 w-2.5 rounded-full" style={{ background: COLORS[tier] }} />
                          <span className="font-medium">{t(TIER_LABELS[tier].zh, TIER_LABELS[tier].en)}</span>
                        </span>
                      </td>
                      <td className="py-2.5 text-right font-mono">{r.games}</td>
                      <td className="py-2.5 text-right font-mono text-text-sub">{r.failed}</td>
                      <td className="py-2.5 text-right font-mono font-semibold" style={{ color: r.village_rate > 50 ? "var(--color-success)" : "var(--color-textPrimary)" }}>{r.village_rate}%</td>
                      <td className="py-2.5 text-right font-mono font-semibold" style={{ color: r.wolf_rate > 50 ? "var(--color-danger)" : "var(--color-textPrimary)" }}>{r.wolf_rate}%</td>
                      <td className="py-2.5 text-right font-mono">{r.avg_days}</td>
                      <td className="py-2.5 text-right font-mono">{r.llm_decisions}</td>
                      <td className="py-2.5 text-right font-mono text-success">{r.fallback}</td>
                      <td className="py-2.5 text-right font-mono text-success">{r.invalid}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Section>

        {/* Section 2: Win Rate Bars */}
        <Section title={t("胜率对比", "Win Rate Comparison")}>
          <div className="grid gap-4 md:grid-cols-2">
            {(["village_rate", "wolf_rate"] as const).map((side) => {
              const isVillage = side === "village_rate";
              const label = isVillage ? t("好人阵营胜率", "Village Win Rate") : t("狼人阵营胜率", "Wolf Win Rate");
              const maxVal = Math.max(...TIERS.map((tier) => OVERALL[tier][side]));
              return (
                <div key={side}>
                  <h3 className="mb-3 text-sm font-semibold text-textPrimary">{label}</h3>
                  <div className="space-y-2.5">
                    {TIERS.map((tier) => {
                      const v = OVERALL[tier][side];
                      return (
                        <div key={tier} className="flex items-center gap-3">
                          <span className="w-32 shrink-0 text-xs text-text-sub">{t(TIER_LABELS[tier].zh, TIER_LABELS[tier].en)}</span>
                          <div className="flex-1">
                            <div className="h-6 rounded" style={{ background: "rgba(255,255,255,0.06)" }}>
                              <div
                                className="h-full rounded transition-all"
                                style={{ width: `${(v / maxVal) * 100}%`, background: COLORS[tier], minWidth: v > 0 ? "2px" : 0 }}
                              />
                            </div>
                          </div>
                          <span className="w-14 text-right text-xs font-mono font-semibold">{v}%</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        </Section>

        {/* Section 3: Delta vs Baseline */}
        <Section title={t("相对 Baseline 变化", "Change vs Baseline")}>
          <div className="grid gap-4 md:grid-cols-3">
            {(["anti_only", "trackc_only", "both"] as const).map((tier) => {
              const d = DELTA[tier];
              return (
                <div key={tier} className="rounded-card border p-4" style={{ borderColor: "var(--color-border)", background: "rgba(255,255,255,0.03)" }}>
                  <h3 className="mb-3 text-sm font-semibold" style={{ color: COLORS[tier] }}>{t(TIER_LABELS[tier].zh, TIER_LABELS[tier].en)}</h3>
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-text-sub">{t("好人 Δ", "Village Δ")}</span>
                      <span className="text-sm font-mono font-semibold" style={{ color: deltaColor(d.village_delta) }}>{d.village_delta > 0 ? "+" : ""}{d.village_delta}%</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-text-sub">{t("狼人 Δ", "Wolf Δ")}</span>
                      <span className="text-sm font-mono font-semibold" style={{ color: deltaColor(d.wolf_delta) }}>{d.wolf_delta > 0 ? "+" : ""}{d.wolf_delta}%</span>
                    </div>
                    <div className="mt-2 rounded-button px-3 py-2 text-xs" style={{ background: "rgba(255,255,255,0.05)" }}>
                      {t(d.note, d.note)}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </Section>

        {/* Section 4: Role Win Rates */}
        <Section title={t("各职业胜率", "Win Rates by Role")}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b" style={{ borderColor: "var(--color-border)" }}>
                  <th className="py-2 text-left font-semibold">{t("职业", "Role")}</th>
                  {TIERS.map((tier) => (
                    <th key={t} className="py-2 text-right font-semibold">{t(TIER_LABELS[tier].zh, TIER_LABELS[tier].en)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Object.entries(ROLE_WIN_RATES).map(([role, rates]) => (
                  <tr key={role} className="border-b" style={{ borderColor: "var(--color-border)" }}>
                    <td className="py-2.5 font-medium text-textPrimary">{t(role, role)}</td>
                    {TIERS.map((tier) => (
                      <td key={tier} className="py-2.5 text-right font-mono" style={{ color: rates[tier] >= 50 ? "var(--color-success)" : rates[tier] <= 30 ? "var(--color-danger)" : "var(--color-textPrimary)" }}>
                        {rates[tier]}%
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-text-sub">
            {t("好人神职 (Seer/Witch/Hunter/Guard/Villager) 共享阵营胜率；狼人 (Werewolf) 独立计算", "Village roles share faction win rate; Werewolf is calculated separately")}
          </p>
        </Section>

        {/* Section 5: MBTI Win Rates */}
        <Section title={t("各 MBTI 胜率", "Win Rates by MBTI")}>
          <div className="grid gap-1.5 md:grid-cols-2 lg:grid-cols-4">
            {Object.entries(MBTI_WIN_RATES)
              .sort((a, b) => a[0].localeCompare(b[0]))
              .map(([mbti, tiers]) => {
                const baselineRate = tiers.baseline.rate;
                const bothRate = tiers.both.rate;
                const delta = bothRate - baselineRate;
                return (
                  <div key={mbti} className="rounded-button border p-3" style={{ borderColor: "var(--color-border)", background: "rgba(255,255,255,0.03)" }}>
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-semibold text-textPrimary">{mbti}</span>
                      <span className="text-xs font-mono" style={{ color: deltaColor(delta) }}>{delta > 0 ? "+" : ""}{delta.toFixed(1)}%</span>
                    </div>
                    <div className="mt-3 grid grid-cols-4 gap-1">
                      {TIERS.map((tier) => {
                        const v = tiers[tier].rate;
                        return (
                          <div key={tier} className="text-center">
                            <div className="mx-auto mb-1 h-1.5 w-full rounded-full" style={{ background: "rgba(255,255,255,0.08)" }}>
                              <div className="h-full rounded-full" style={{ width: `${Math.min(100, v)}%`, background: COLORS[tier] }} />
                            </div>
                            <span className="text-[10px] font-mono text-text-sub">{v}%</span>
                          </div>
                        );
                      })}
                    </div>
                    <div className="mt-2 text-right text-[10px] text-text-sub/60">
                      n={tiers.baseline.n}+{tiers.anti_only.n}+{tiers.trackc_only.n}+{tiers.both.n}
                    </div>
                  </div>
                );
              })}
          </div>
        </Section>

        {/* Section 6: Conclusion */}
        <Section title={t("结论", "Conclusion")}>
          <div className="space-y-3 text-sm text-textPrimary">
            <p>
              {t(
                "在 strict no-fallback 条件下，Anti-Patterns 和 Track C 策略主要提升了狼人阵营胜率。",
                "Under strict no-fallback conditions, Anti-Patterns and Track C strategies primarily improved wolf faction win rates."
              )}
            </p>
            <ul className="ml-5 list-disc space-y-1.5 text-text-sub">
              <li>{t("anti_only 相对 baseline 狼人胜率 +13.3%，是效果最显著的层级", "anti_only vs baseline: wolf +13.3% — most impactful tier")}</li>
              <li>{t("both (Anti + Track C) 狼人 +10.2%，但完成率仅 39.4%，稳定性需改进", "both: wolf +10.2% but 39.4% completion rate — stability needs work")}</li>
              <li>{t("trackc_only 狼人 +2.6%，提升幅度较小；该层失败率 50% 可能掩盖了更多信号", "trackc_only: wolf +2.6% — modest gain; 50% failure rate may mask additional signals")}</li>
              <li>{t("好人阵营在所有强化层级下胜率均下降，提示当前策略优化方向偏狼人侧", "Village win rate decreased across all tiers, suggesting current optimizations favor wolf play")}</li>
              <li>{t("所有完成局 fallback=0, invalid=0，验证 strict 模式下数据干净", "All completed games: fallback=0, invalid=0 — clean data under strict mode")}</li>
            </ul>
            <p className="text-xs text-text-sub/70">
              {t("数据来源: docs/experiments/full_victory_report.md", "Source: docs/experiments/full_victory_report.md")}
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
