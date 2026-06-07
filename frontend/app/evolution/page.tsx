"use client";

import React, { useEffect, useState, useMemo } from "react";
import Link from "next/link";
import { apiUrl } from "@/lib/api";
import { useAppContext } from "@/context/AppContext";

/* ── Types ── */

interface StrategyCard {
  card_id: string; role: string; version: string; goal: string;
  speech_policy: string[]; vote_policy: string[]; skill_policy: string[];
  risk_rules: string[]; retrieval_policy: { top_k: number; enabled: boolean; min_quality: number };
  status: string; created_at: string;
}

interface KnowledgeDoc {
  doc_id: string; role: string; phase: string; doc_type: string;
  quality_score: number; usage_count: number; success_count: number; failure_count: number;
  status: string; recommended_action: string; situation_pattern: string;
  rationale: string; evidence_summary: string; trigger_conditions: string[];
  confidence_tier: string;
}

interface Tournament {
  tournament_id: string; baseline_version: string; candidate_version: string;
  status: string; decision?: { action?: string };
  comparison?: { candidate_camp_win_rate?: number; baseline_camp_win_rate?: number;
    candidate_target_role_avg_score?: number; candidate_critical_mistakes_per_game?: number; };
}

interface AcceptanceMetric {
  track: string; step_id: string; name: string;
  numerator: number; denominator: number; success_rate: number;
  threshold: number; passed: boolean; evidence: string;
}

interface ApiDashboard {
  active_versions: StrategyCard[]; knowledge: KnowledgeDoc[];
  tournaments: Tournament[]; acceptance_metrics: AcceptanceMetric[];
  acceptance_audit?: { overall_success_rate?: number; passed?: boolean };
}

/* ── Experiment data (from full_victory_report.md) ── */

const TIER_ORDER = ["baseline", "anti_only", "trackc_only", "both"] as const;

const TIER_META: Record<string, { name: string; desc: string; color: string }> = {
  baseline:    { name: "Baseline",    desc: "纯 MBTI + Role",              color: "#6b7280" },
  anti_only:   { name: "Anti-Patterns", desc: "+ 静态反模式清单",          color: "#f59e0b" },
  trackc_only: { name: "Track C",       desc: "+ 动态策略检索",            color: "#3b82f6" },
  both:        { name: "Anti + Track C", desc: "完整三层",                 color: "#8b5cf6" },
};

const EXPERIMENT: Record<string, { games: number; village: number; wolf: number; days: number }> = {
  baseline:    { games: 18, village: 33.3, wolf: 66.7, days: 1.72 },
  anti_only:   { games: 20, village: 20.0, wolf: 80.0, days: 1.85 },
  trackc_only: { games: 13, village: 30.8, wolf: 69.2, days: 1.77 },
  both:        { games: 13, village: 23.1, wolf: 76.9, days: 1.69 },
};

/* MBTI x Role: both vs baseline delta (from full_victory_report.md §6) */
const MBTI_ROLE_DELTA: { mbti: string; role: string; baseline: number; both: number; delta: number; nB: number; nBoth: number }[] = [
  { mbti:"ENTP", role:"Werewolf", baseline:0, both:100, delta:+100, nB:1, nBoth:2 },
  { mbti:"INFJ", role:"Guard", baseline:0, both:100, delta:+100, nB:1, nBoth:1 },
  { mbti:"INFP", role:"Seer", baseline:0, both:100, delta:+100, nB:1, nBoth:1 },
  { mbti:"ENTJ", role:"Werewolf", baseline:33.3, both:100, delta:+66.7, nB:3, nBoth:3 },
  { mbti:"ENFJ", role:"Werewolf", baseline:50, both:100, delta:+50, nB:6, nBoth:2 },
  { mbti:"ENFJ", role:"Witch", baseline:0, both:50, delta:+50, nB:2, nBoth:2 },
  { mbti:"ESTP", role:"Witch", baseline:0, both:50, delta:+50, nB:3, nBoth:2 },
  { mbti:"ISFP", role:"Hunter", baseline:0, both:50, delta:+50, nB:2, nBoth:2 },
  { mbti:"ISTP", role:"Werewolf", baseline:0, both:50, delta:+50, nB:1, nBoth:2 },
  { mbti:"INTJ", role:"Seer", baseline:20, both:50, delta:+30, nB:5, nBoth:2 },
  { mbti:"INTJ", role:"Werewolf", baseline:80, both:100, delta:+20, nB:5, nBoth:2 },
  { mbti:"ESFJ", role:"Villager", baseline:40, both:33.3, delta:-6.7, nB:5, nBoth:3 },
  { mbti:"ESTJ", role:"Villager", baseline:50, both:33.3, delta:-16.7, nB:2, nBoth:3 },
  { mbti:"INFJ", role:"Seer", baseline:50, both:33.3, delta:-16.7, nB:4, nBoth:3 },
  { mbti:"ENFJ", role:"Guard", baseline:33.3, both:0, delta:-33.3, nB:3, nBoth:2 },
  { mbti:"ESTP", role:"Werewolf", baseline:33.3, both:0, delta:-33.3, nB:3, nBoth:1 },
  { mbti:"INFP", role:"Guard", baseline:33.3, both:0, delta:-33.3, nB:3, nBoth:2 },
  { mbti:"ISTJ", role:"Seer", baseline:33.3, both:0, delta:-33.3, nB:3, nBoth:2 },
  { mbti:"ISTJ", role:"Witch", baseline:33.3, both:0, delta:-33.3, nB:3, nBoth:1 },
  { mbti:"ESFJ", role:"Hunter", baseline:50, both:0, delta:-50, nB:2, nBoth:1 },
  { mbti:"INFP", role:"Hunter", baseline:50, both:0, delta:-50, nB:2, nBoth:1 },
  { mbti:"ISTJ", role:"Werewolf", baseline:100, both:50, delta:-50, nB:3, nBoth:2 },
  { mbti:"INFP", role:"Werewolf", baseline:100, both:33.3, delta:-66.7, nB:2, nBoth:3 },
  { mbti:"ENFP", role:"Witch", baseline:100, both:0, delta:-100, nB:1, nBoth:2 },
];

const META = "2026-06-07 · doubao:deepseek-v4-flash · 7P · strict";
const ROLES = ["Seer","Witch","Hunter","Guard","Villager","Werewolf"] as const;
const ROLE_COLORS: Record<string, string> = {
  Seer:"#a78bfa", Witch:"#34d399", Hunter:"#fbbf24", Guard:"#60a5fa", Villager:"#9ca3af", Werewolf:"#f87171",
};

/* ── Helpers ── */
function d(a: number, b: number) { const v = a - b; return `${v>=0?"+":""}${v.toFixed(1)}%`; }

/* ── Page ── */
export default function EvolutionPage() {
  const { language } = useAppContext();
  const t = (zh: string, en: string) => language === "zh" ? zh : en;
  const [api, setApi] = useState<ApiDashboard | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => { (async () => {
    try { const r = await fetch(apiUrl("/api/evolution/dashboard")); if (r.ok) setApi(await r.json()); }
    catch {} finally { setLoading(false); }
  })(); }, []);

  const cards = api?.active_versions || [];
  const knowledge = api?.knowledge || [];
  const tournaments = api?.tournaments || [];
  const acceptance = api?.acceptance_metrics || [];

  // Per-role strategy usage stats
  const roleStats = useMemo(() => {
    const m: Record<string, { usage: number; success: number; failure: number; active: number }> = {};
    for (const k of knowledge) {
      const r = k.role; if (!m[r]) m[r] = { usage:0, success:0, failure:0, active:0 };
      m[r].usage += k.usage_count||0; m[r].success += k.success_count||0; m[r].failure += k.failure_count||0;
      if (k.status==="active"||k.status==="candidate") m[r].active++;
    }
    return m;
  }, [knowledge]);

  const activeKnowledge = knowledge.filter(k => k.status==="active"||k.status==="candidate");
  const avgQuality = knowledge.length ? knowledge.reduce((s,k)=>s+k.quality_score,0)/knowledge.length : 0;

  // Track C vs Anti-only: the key comparison
  const bothVsAnti = EXPERIMENT.both.wolf - EXPERIMENT.anti_only.wolf;
  const tcVsBaseline = EXPERIMENT.trackc_only.wolf - EXPERIMENT.baseline.wolf;
  const antiVsBaseline = EXPERIMENT.anti_only.wolf - EXPERIMENT.baseline.wolf;

  return (
    <main className="min-h-screen px-5 py-6" style={{ background: "var(--color-bg)" }}>
      <div className="mx-auto max-w-7xl space-y-5">

        {/* Header */}
        <header className="flex flex-wrap items-center justify-between gap-3 pb-2 border-b" style={{ borderColor: "var(--color-border)" }}>
          <div>
            <h1 className="text-2xl font-bold text-textPrimary">{t("策略进化 & 实验报告", "Strategy Evolution & Experiments")}</h1>
            <p className="text-xs text-text-sub mt-0.5">{META}</p>
          </div>
          <Link href="/" className="rounded border px-3 py-1.5 text-sm text-textPrimary" style={{ borderColor: "var(--color-border)" }}>
            {t("大厅", "Lobby")}
          </Link>
        </header>

        {/* ═══ 1. ABLATION ═══ */}
        <section className="rounded-lg border p-5" style={{ borderColor:"var(--color-border)", background:"var(--color-card)" }}>
          <h2 className="text-base font-semibold text-textPrimary mb-1">{t("消融实验", "Ablation Study")}</h2>
          <p className="text-xs text-text-sub mb-4">
            {t("逐层叠加组件，测量每个组件对狼人胜率的边际贡献。括号内为完成局数。仅统计成功对局，失败局不计入。", "Layer-by-layer ablation. Each layer adds one component. Only successful games counted.")}
          </p>

          {/* Layer bars */}
          <div className="space-y-2 mb-5">
            {TIER_ORDER.map((tier, i) => {
              const e = EXPERIMENT[tier];
              const prev = i > 0 ? EXPERIMENT[TIER_ORDER[i-1]] : null;
              const layerDelta = prev ? e.wolf - prev.wolf : 0;
              const meta = TIER_META[tier];
              return (
                <div key={tier} className="flex items-center gap-3">
                  <div className="w-40 shrink-0 text-right">
                    <span className="text-sm font-medium text-textPrimary">{meta.name}</span>
                    <span className="ml-1 text-[11px] text-text-sub">{meta.desc}</span>
                  </div>
                  {/* Layer bar */}
                  <div className="flex-1 flex items-center gap-2">
                    {/* Baseline portion */}
                    <div className="h-7 rounded" style={{ width:`${e.wolf}%`, maxWidth:"100%", background:meta.color, opacity:0.8, display:"flex", alignItems:"center", justifyContent:"flex-end", paddingRight:4 }}>
                      <span className="text-[10px] font-mono font-bold text-white drop-shadow">{e.wolf}%</span>
                    </div>
                  </div>
                  {/* n games */}
                  <span className="w-12 text-right font-mono text-xs text-text-sub">n={e.games}</span>
                  {/* vs baseline */}
                  <span className="w-20 text-right font-mono text-xs" style={{ color: tier==="baseline"?"transparent":e.wolf>=EXPERIMENT.baseline.wolf?"var(--color-success)":"var(--color-danger)" }}>
                    {tier==="baseline"?"":"vs base "+d(e.wolf, EXPERIMENT.baseline.wolf)}
                  </span>
                  {/* layer delta */}
                  <span className="w-16 text-right font-mono text-[11px]" style={{ color: layerDelta>0?"var(--color-success)":layerDelta<0?"var(--color-warning, #f59e0b)":"var(--color-text-sub)" }}>
                    {prev ? (layerDelta>=0?"+":"")+layerDelta.toFixed(1)+"%" : ""}
                  </span>
                </div>
              );
            })}
          </div>

          {/* Layer breakdown table */}
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-xs uppercase tracking-wide text-text-sub" style={{ borderColor:"var(--color-border)" }}>
                <th className="py-2 text-left">{t("层级", "Layer")}</th>
                <th className="py-2 text-right">{t("局数", "n")}</th>
                <th className="py-2 text-right">{t("好人胜率", "Village WR")}</th>
                <th className="py-2 text-right">{t("狼人胜率", "Wolf WR")}</th>
                <th className="py-2 text-right">{t("vs Baseline Δ", "vs Baseline")}</th>
                <th className="py-2 text-right">{t("逐层 Δ", "Layer Δ")}</th>
                <th className="py-2 text-left">{t("解读", "Note")}</th>
              </tr>
            </thead>
            <tbody>
              {TIER_ORDER.map((tier, i) => {
                const e = EXPERIMENT[tier];
                const prev = i > 0 ? EXPERIMENT[TIER_ORDER[i-1]] : null;
                const vsBase = tier==="baseline" ? 0 : e.wolf - EXPERIMENT.baseline.wolf;
                const lyr = prev ? e.wolf - prev.wolf : 0;
                const note = tier==="baseline" ? "纯 MBTI 人格基线"
                  : tier==="anti_only" ? `反模式使狼人胜率 +${antiVsBaseline.toFixed(0)}pp`
                  : tier==="trackc_only" ? `策略检索独立效果 +${tcVsBaseline.toFixed(1)}pp（仅13局，小样本）`
                  : `叠加 Track C 后狼人胜率${bothVsAnti>=0?"+":""}${bothVsAnti.toFixed(1)}pp（13局 vs 20局，需更大样本验证）`;
                return (
                  <tr key={tier} className="border-b" style={{ borderColor:"var(--color-border)" }}>
                    <td className="py-2 text-xs font-medium">{TIER_META[tier].name}</td>
                    <td className="py-2 text-right font-mono text-xs">{e.games}</td>
                    <td className="py-2 text-right font-mono text-xs">{e.village}%</td>
                    <td className="py-2 text-right font-mono text-xs font-semibold">{e.wolf}%</td>
                    <td className="py-2 text-right font-mono text-xs" style={{ color: tier==="baseline"?"var(--color-text-sub)":vsBase>=0?"var(--color-success)":"var(--color-danger)" }}>
                      {tier==="baseline" ? "-" : d(e.wolf, EXPERIMENT.baseline.wolf)}
                    </td>
                    <td className="py-2 text-right font-mono text-xs text-text-sub">{prev ? d(e.wolf, prev.wolf) : "-"}</td>
                    <td className="py-2 text-[11px] text-text-sub">{note}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>

        {/* ═══ 2. STRATEGY CARDS (from DB) ═══ */}
        <section className="rounded-lg border p-5" style={{ borderColor:"var(--color-border)", background:"var(--color-card)" }}>
          <h2 className="text-base font-semibold text-textPrimary mb-1">
            {t("策略卡片", "Strategy Cards")}
            <span className="ml-2 text-xs font-normal text-text-sub">{cards.length} {t("张", "cards")}</span>
          </h2>
          <p className="text-xs text-text-sub mb-4">
            {t("从数据库 role_strategy_cards 表读取。每张卡片定义了一个角色的发言/投票/技能策略和风险规避规则。", "Loaded from role_strategy_cards table. Each card defines speech/vote/skill policies and risk rules for one role.")}
          </p>
          {loading ? <p className="text-xs text-text-sub">{t("加载中...", "Loading...")}</p>
          : cards.length===0 ? <p className="text-xs text-text-sub">{t("暂无策略卡片", "No strategy cards yet")}</p>
          : (
            <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
              {cards.map(card => (
                <div key={card.card_id} className="rounded-lg border p-4" style={{ borderColor:"var(--color-border)", background:"rgba(255,255,255,0.025)" }}>
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                      <span className="h-2.5 w-2.5 rounded-full" style={{ background: ROLE_COLORS[card.role]||"#9ca3af" }} />
                      <span className="text-sm font-semibold">{t(card.role, card.role)}</span>
                      <span className="rounded px-1.5 py-0.5 text-[10px] text-text-sub bg-white/5">{card.version}</span>
                    </div>
                    <span className="text-[10px] text-text-sub">{card.status}</span>
                  </div>
                  <p className="text-xs text-text-sub mb-3">{card.goal}</p>
                  {["speech","vote","skill"].map(policy => {
                    const items = (card as any)[policy+"_policy"] || [];
                    if (!items.length) return null;
                    const label = policy==="speech"?t("发言","Speech"):policy==="vote"?t("投票","Vote"):t("技能","Skill");
                    return (
                      <div key={policy} className="mb-1.5">
                        <span className="text-[10px] font-semibold uppercase text-text-sub/60">{label}</span>
                        <ul className="list-disc list-inside space-y-0.5 mt-0.5">
                          {items.slice(0,2).map((p:string,i:number) => <li key={i} className="text-[11px] text-textPrimary">{p}</li>)}
                        </ul>
                      </div>
                    );
                  })}
                  {card.risk_rules?.length>0 && (
                    <div className="mt-2 rounded border border-amber-500/20 px-2.5 py-2 bg-amber-500/5">
                      <span className="text-[10px] font-semibold text-amber-500">{t("风险规避","Risk Rules")}</span>
                      <ul className="list-disc list-inside space-y-0.5 mt-0.5">
                        {card.risk_rules.slice(0,2).map((r,i) => <li key={i} className="text-[11px] text-text-sub">{r}</li>)}
                      </ul>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>

        {/* ═══ 3. KNOWLEDGE BASE ═══ */}
        <section className="rounded-lg border p-5" style={{ borderColor:"var(--color-border)", background:"var(--color-card)" }}>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-base font-semibold text-textPrimary">{t("知识库", "Knowledge Base")}</h2>
            <span className="text-xs text-text-sub">
              {knowledge.length} total · {activeKnowledge.length} active · avg quality {avgQuality.toFixed(2)}
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-xs uppercase tracking-wide text-text-sub" style={{ borderColor:"var(--color-border)" }}>
                  <th className="py-2 text-left">{t("角色","Role")}</th>
                  <th className="py-2 text-left">{t("阶段","Phase")}</th>
                  <th className="py-2 text-left">{t("策略内容","Strategy")}</th>
                  <th className="py-2 text-right">{t("质量","Q")}</th>
                  <th className="py-2 text-right">{t("使用","Used")}</th>
                  <th className="py-2 text-right">{t("成功","OK")}</th>
                  <th className="py-2 text-right">{t("失败","Fail")}</th>
                  <th className="py-2 text-right">{t("信任级","Tier")}</th>
                  <th className="py-2 text-right">{t("状态","St")}</th>
                </tr>
              </thead>
              <tbody>
                {knowledge.slice(0,40).map(k => (
                  <tr key={k.doc_id} className="border-b" style={{ borderColor:"var(--color-border)" }}>
                    <td className="py-1.5"><span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full" style={{background:ROLE_COLORS[k.role]||"#9ca3af"}}/>{k.role}</span></td>
                    <td className="py-1.5 text-xs text-text-sub">{k.phase}</td>
                    <td className="py-1.5 max-w-xs text-xs truncate">{k.recommended_action||k.situation_pattern}</td>
                    <td className="py-1.5 text-right font-mono text-xs" style={{color:k.quality_score>=0.7?"var(--color-success)":k.quality_score>=0.4?"var(--color-warning, #f59e0b)":"var(--color-text-sub)"}}>{k.quality_score.toFixed(2)}</td>
                    <td className="py-1.5 text-right font-mono text-xs">{k.usage_count}</td>
                    <td className="py-1.5 text-right font-mono text-xs text-success">{k.success_count}</td>
                    <td className="py-1.5 text-right font-mono text-xs text-text-sub">{k.failure_count}</td>
                    <td className="py-1.5 text-right text-[10px] text-text-sub">{k.confidence_tier?.replace("L","").replace("_"," ")}</td>
                    <td className="py-1.5 text-right text-[10px]" style={{color:k.status==="active"?"var(--color-success)":k.status==="deprecated"?"var(--color-text-sub)":"var(--color-warning)"}}>{k.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* ═══ 4. MBTI × ROLE ═══ */}
        <section className="rounded-lg border p-5" style={{ borderColor:"var(--color-border)", background:"var(--color-card)" }}>
          <h2 className="text-base font-semibold text-textPrimary mb-1">{t("MBTI × 角色胜率变化", "MBTI × Role Win Rate Δ")}</h2>
          <p className="text-xs text-text-sub mb-4">
            {t("both vs baseline，全玩家口径。仅展示有至少1个 baseline 样本和1个 both 样本的组合。nB = baseline 玩家样本数，nBoth = both 玩家样本数。", "both vs baseline, per-player. Only combos with ≥1 sample in both tiers shown.")}
          </p>

          {/* Heatmap grid: rows=MBTI, cols=Role */}
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b" style={{ borderColor:"var(--color-border)" }}>
                  <th className="py-1.5 text-left font-semibold w-16">MBTI</th>
                  {ROLES.map(r => <th key={r} className="py-1.5 text-center font-semibold w-20">{r}</th>)}
                </tr>
              </thead>
              <tbody>
                {Array.from(new Set(MBTI_ROLE_DELTA.map(d=>d.mbti))).sort().map(mbti => {
                  const entries = MBTI_ROLE_DELTA.filter(d=>d.mbti===mbti);
                  return (
                    <tr key={mbti} className="border-b" style={{ borderColor:"var(--color-border)" }}>
                      <td className="py-1 text-textPrimary font-medium">{mbti}</td>
                      {ROLES.map(role => {
                        const e = entries.find(d=>d.role===role);
                        if (!e) return <td key={role} className="py-1 text-center text-text-sub/30">-</td>;
                        const bg = e.delta>30 ? "rgba(16,185,129,0.15)" : e.delta>0 ? "rgba(16,185,129,0.06)" : e.delta>-30 ? "rgba(239,68,68,0.06)" : "rgba(239,68,68,0.15)";
                        const tc = e.delta>0 ? "var(--color-success)" : "var(--color-danger)";
                        return (
                          <td key={role} className="py-1 text-center rounded" style={{ background:bg }}>
                            <span className="font-mono" style={{color:tc}}>{e.delta>0?"+":""}{e.delta.toFixed(0)}%</span>
                            <span className="block text-[9px] text-text-sub/50">n={e.nB}+{e.nBoth}</span>
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="flex items-center gap-4 mt-3 text-[10px] text-text-sub">
            <span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded bg-emerald-500/30"/> +Δ = both 更好</span>
            <span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded bg-red-500/30"/> -Δ = baseline 更好</span>
            <span>{t("颜色深度 = |Δ| 大小", "Deeper color = larger |Δ|")}</span>
          </div>
        </section>

        {/* ═══ 5. TRACK C EFFECTIVENESS ═══ */}
        <section className="rounded-lg border p-5" style={{ borderColor:"var(--color-border)", background:"var(--color-card)" }}>
          <h2 className="text-base font-semibold text-textPrimary mb-1">{t("Track C 策略检索效果", "Track C Retrieval Effectiveness")}</h2>
          <p className="text-xs text-text-sub mb-4">
            {t("每个角色在对局中检索策略的次数、成功率和活跃策略文档数。usage = 该角色策略在真实对局中被检索命中的总次数。", "Per-role strategy retrieval counts, success rates, and active docs. usage = total times this role's strategies were retrieved during real games.")}
          </p>

          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 mb-5">
            {/* Summary cards */}
            <SummaryCard label={t("Track C 独立效果", "Track C Alone")} value={d(EXPERIMENT.trackc_only.wolf, EXPERIMENT.baseline.wolf)} sub={t("trackc_only vs baseline 狼人Δ", "trackc_only vs baseline wolf Δ")} tone={tcVsBaseline>0?"good":"neutral"} />
            <SummaryCard label={t("Track C 叠加效果", "Track C Stacked")} value={d(EXPERIMENT.both.wolf, EXPERIMENT.anti_only.wolf)} sub={t("both vs anti_only 狼人Δ", "both vs anti_only wolf Δ")} tone={bothVsAnti>0?"good":"neutral"} />
            <SummaryCard label={t("策略总命中次数", "Total Retrievals")} value={Object.values(roleStats).reduce((s,r)=>s+r.usage,0).toLocaleString()} sub={t("所有角色策略被检索的总次数", "total strategy retrievals across all roles")} tone="info" />
          </div>

          {/* Per-role retrieval table */}
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-xs uppercase tracking-wide text-text-sub" style={{ borderColor:"var(--color-border)" }}>
                <th className="py-2 text-left">{t("角色","Role")}</th>
                <th className="py-2 text-right">{t("检索次数","Retrievals")}</th>
                <th className="py-2 text-right">{t("成功","OK")}</th>
                <th className="py-2 text-right">{t("失败","Fail")}</th>
                <th className="py-2 text-right">{t("命中率","Hit %")}</th>
                <th className="py-2 text-right">{t("活跃文档","Active")}</th>
                <th className="py-2 text-right">{t("有策略卡","Card")}</th>
              </tr>
            </thead>
            <tbody>
              {ROLES.map(role => {
                const s = roleStats[role] || { usage:0, success:0, failure:0, active:0 };
                const hit = s.usage>0 ? s.success/s.usage : 0;
                const hasCard = cards.some(c=>c.role===role);
                return (
                  <tr key={role} className="border-b" style={{ borderColor:"var(--color-border)" }}>
                    <td className="py-1.5"><span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full" style={{background:ROLE_COLORS[role]}}/>{role}</span></td>
                    <td className="py-1.5 text-right font-mono text-xs">{s.usage>0?s.usage.toLocaleString():"-"}</td>
                    <td className="py-1.5 text-right font-mono text-xs text-success">{s.success>0?s.success.toLocaleString():"-"}</td>
                    <td className="py-1.5 text-right font-mono text-xs text-text-sub">{s.failure>0?s.failure.toLocaleString():"-"}</td>
                    <td className="py-1.5 text-right font-mono text-xs" style={{color:hit>=0.3?"var(--color-success)":hit>0?"var(--color-warning)":"var(--color-text-sub)"}}>{s.usage>0?`${(hit*100).toFixed(1)}%`:"-"}</td>
                    <td className="py-1.5 text-right font-mono text-xs">{s.active>0?s.active:"-"}</td>
                    <td className="py-1.5 text-center text-xs">{hasCard?<span className="text-success">✓</span>:"-"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>

        {/* ═══ 6. B/C ACCEPTANCE ═══ */}
        {acceptance.length>0 && (
          <section className="rounded-lg border p-5" style={{ borderColor:"var(--color-border)", background:"var(--color-card)" }}>
            <h2 className="text-base font-semibold text-textPrimary mb-3">
              {t("B/C 验收", "B/C Acceptance")}
              {api?.acceptance_audit?.overall_success_rate != null && (
                <span className={`ml-2 text-xs ${api.acceptance_audit.passed?"text-success":"text-danger"}`}>
                  {Math.round(api.acceptance_audit.overall_success_rate*100)}%
                </span>
              )}
            </h2>
            <div className="grid gap-4 md:grid-cols-2">
              {(["B","C"] as const).map(track => {
                const items = acceptance.filter(m=>m.track===track);
                return (
                  <div key={track}>
                    <p className="text-xs font-semibold uppercase tracking-wide text-text-sub mb-2">{track==="B"?t("反模式验收","Anti-Pattern Acceptance"):t("策略检索验收","Strategy Retrieval Acceptance")}</p>
                    <div className="space-y-2">
                      {items.map(m => (
                        <div key={m.step_id} className="rounded border p-2.5" style={{ borderColor:"var(--color-border)", background:"rgba(255,255,255,0.025)" }}>
                          <div className="flex items-start justify-between gap-2">
                            <div><p className="text-xs font-medium text-textPrimary">{m.step_id}</p><p className="text-[10px] text-text-sub mt-0.5">{m.name}</p></div>
                            <span className={m.passed?"text-xs font-semibold text-success":"text-xs font-semibold text-danger"}>{Math.round(m.success_rate*100)}%</span>
                          </div>
                          <div className="mt-1 h-1.5 rounded-full bg-white/8 overflow-hidden">
                            <div className={`h-full rounded-full ${m.passed?"bg-success":"bg-danger"}`} style={{width:`${Math.max(2,Math.min(100,m.success_rate*100))}%`}}/>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        )}
      </div>
    </main>
  );
}

function SummaryCard({ label, value, sub, tone }: { label:string; value:string; sub?:string; tone:"good"|"neutral"|"info" }) {
  const color = tone==="good"?"var(--color-success)":tone==="info"?"var(--color-primary, #3b82f6)":"var(--color-textPrimary)";
  return (
    <div className="rounded-lg border p-4" style={{ borderColor:"var(--color-border)", background:"rgba(255,255,255,0.03)" }}>
      <p className="text-xs text-text-sub">{label}</p>
      <p className="mt-1 text-2xl font-bold" style={{color}}>{value}</p>
      {sub && <p className="mt-1 text-[11px] text-text-sub/60">{sub}</p>}
    </div>
  );
}
