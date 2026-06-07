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
  confidence_tier: string;
}

interface AcceptanceMetric {
  track: string; step_id: string; name: string;
  numerator: number; denominator: number; success_rate: number;
  threshold: number; passed: boolean; evidence: string;
}

interface ApiDashboard {
  active_versions: StrategyCard[]; knowledge: KnowledgeDoc[];
  acceptance_metrics: AcceptanceMetric[];
  acceptance_audit?: { overall_success_rate?: number; passed?: boolean };
}

/* ── Experiment data (full_victory_report.md + per-role files) ── */

const TIER_ORDER = ["baseline", "anti_only", "trackc_only", "both"] as const;

const TIER_META: Record<string, { name: string; desc: string; color: string }> = {
  baseline:    { name: "Baseline",    desc: "纯 MBTI + Role",              color: "#6b7280" },
  anti_only:   { name: "Anti-Patterns", desc: "+ 静态反模式清单",          color: "#f59e0b" },
  trackc_only: { name: "Track C",       desc: "+ 动态策略检索",            color: "#3b82f6" },
  both:        { name: "Anti + Track C", desc: "完整三层",                 color: "#8b5cf6" },
};

// Multi-tier experiment: per-tier game counts from full_victory_report.md
const EXPERIMENT: Record<string, { games: number; village: number; wolf: number; days: number }> = {
  baseline:    { games: 18, village: 33.3, wolf: 66.7, days: 1.72 },
  anti_only:   { games: 20, village: 20.0, wolf: 80.0, days: 1.85 },
  trackc_only: { games: 13, village: 30.8, wolf: 69.2, days: 1.77 },
  both:        { games: 13, village: 23.1, wolf: 76.9, days: 1.69 },
};

// Per-role experiment: each role has 10 good + 10 bad = 20 games
// from data/experiment/role_*_good/bad_seed_*.json
const PER_ROLE_GAMES = 20;

// MBTI x Role delta (from full_victory_report.md §6)
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

const ROLES = ["Seer","Witch","Hunter","Guard","Villager","Werewolf"] as const;
const ROLE_COLORS: Record<string, string> = {
  Seer:"#a78bfa", Witch:"#34d399", Hunter:"#fbbf24", Guard:"#60a5fa",
  Villager:"#9ca3af", Werewolf:"#f87171", WhiteWolfKing:"#ef4444",
};

/* ── Helpers ── */
function delta(a: number, b: number) { const v = a - b; return `${v>=0?"+":""}${v.toFixed(1)}%`; }
function deltaNum(a: number, b: number) { return a - b; }

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
  const acceptance = api?.acceptance_metrics || [];

  // Per-role strategy stats from API knowledge
  const roleStats = useMemo(() => {
    const m: Record<string, { usage: number; success: number; failure: number; active: number }> = {};
    for (const k of knowledge) {
      const r = k.role; if (!m[r]) m[r] = { usage:0, success:0, failure:0, active:0 };
      m[r].usage += k.usage_count||0; m[r].success += k.success_count||0; m[r].failure += k.failure_count||0;
      if (k.status==="active"||k.status==="candidate") m[r].active++;
    }
    return m;
  }, [knowledge]);

  const totalUsage = Object.values(roleStats).reduce((s,r)=>s+r.usage,0);
  const activeCards = cards.filter(c => c.status === "active");

  const antiVsBaseline = deltaNum(EXPERIMENT.anti_only.wolf, EXPERIMENT.baseline.wolf);
  const tcVsBaseline = deltaNum(EXPERIMENT.trackc_only.wolf, EXPERIMENT.baseline.wolf);
  const bothVsBaseline = deltaNum(EXPERIMENT.both.wolf, EXPERIMENT.baseline.wolf);
  const bothVsAnti = deltaNum(EXPERIMENT.both.wolf, EXPERIMENT.anti_only.wolf);

  return (
    <main className="min-h-screen px-5 py-6" style={{ background: "var(--color-bg)" }}>
      <div className="mx-auto max-w-7xl space-y-5">

        {/* Header */}
        <header className="flex flex-wrap items-center justify-between gap-3 pb-2 border-b" style={{ borderColor: "var(--color-border)" }}>
          <div>
            <h1 className="text-2xl font-bold text-textPrimary">{t("策略进化", "Strategy Evolution")}</h1>
            <p className="text-xs text-text-sub mt-0.5">
              {t("7P · strict · doubao:deepseek-v4-flash · 每角色20局 · DB: 10K场对局 / 136K条知识", "7P · strict · doubao:deepseek-v4-flash · 20 games/role · DB: 10K games / 136K docs")}
            </p>
          </div>
          <Link href="/" className="rounded border px-3 py-1.5 text-sm text-textPrimary" style={{ borderColor: "var(--color-border)" }}>
            {t("大厅", "Lobby")}
          </Link>
        </header>

        {/* ═══ 1. ABLATION ═══ */}
        <section className="rounded-lg border p-5" style={{ borderColor:"var(--color-border)", background:"var(--color-card)" }}>
          <h2 className="text-base font-semibold text-textPrimary mb-3">{t("消融实验", "Ablation Study")}</h2>

          <div className="space-y-2 mb-5">
            {TIER_ORDER.map((tier, i) => {
              const e = EXPERIMENT[tier];
              const prev = i > 0 ? EXPERIMENT[TIER_ORDER[i-1]] : null;
              const layerDelta = prev ? e.wolf - prev.wolf : 0;
              const m = TIER_META[tier];
              return (
                <div key={tier} className="flex items-center gap-3">
                  <div className="w-44 shrink-0 text-right">
                    <span className="text-sm font-medium text-textPrimary">{m.name}</span>
                    <div className="text-[11px] text-text-sub">{m.desc}</div>
                  </div>
                  <div className="flex-1">
                    <div className="h-7 rounded flex items-center justify-end pr-2" style={{ width:`${Math.max(2,e.wolf)}%`, background:m.color, opacity:0.85 }}>
                      <span className="text-[10px] font-mono font-bold text-white drop-shadow">{e.wolf}%</span>
                    </div>
                  </div>
                  <span className="w-12 text-right font-mono text-xs text-text-sub">n={e.games}</span>
                  <span className="w-20 text-right font-mono text-xs" style={{ color:tier==="baseline"?"transparent":e.wolf>=EXPERIMENT.baseline.wolf?"var(--color-success)":"var(--color-danger)" }}>
                    {tier==="baseline"?"":"vs base "+delta(e.wolf, EXPERIMENT.baseline.wolf)}
                  </span>
                  <span className="w-14 text-right font-mono text-[11px]" style={{ color:layerDelta>0?"var(--color-success)":layerDelta<0?"var(--color-warning, #f59e0b)":"var(--color-text-sub)" }}>
                    {prev ? (layerDelta>=0?"+":"")+layerDelta.toFixed(1)+"pp" : ""}
                  </span>
                </div>
              );
            })}
          </div>

          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-xs uppercase tracking-wide text-text-sub" style={{ borderColor:"var(--color-border)" }}>
                <th className="py-2 text-left">{t("层级","Layer")}</th>
                <th className="py-2 text-right">{t("局数","n")}</th>
                <th className="py-2 text-right">{t("好人胜率","Village")}</th>
                <th className="py-2 text-right">{t("狼人胜率","Wolf")}</th>
                <th className="py-2 text-right">{t("vs Baseline","vs Base")}</th>
                <th className="py-2 text-right">{t("层增量","Layer Δ")}</th>
                <th className="py-2 text-left">{t("说明","Note")}</th>
              </tr>
            </thead>
            <tbody>
              {TIER_ORDER.map((tier, i) => {
                const e = EXPERIMENT[tier];
                const prev = i>0?EXPERIMENT[TIER_ORDER[i-1]]:null;
                const vsBase = tier==="baseline"?0:e.wolf-EXPERIMENT.baseline.wolf;
                const lyr = prev?e.wolf-prev.wolf:0;
                const notes: Record<string,string> = {
                  baseline: "纯 MBTI 人格基线",
                  anti_only: `反模式提升狼人胜率 +${antiVsBaseline.toFixed(0)}pp（最大单层增益）`,
                  trackc_only: `策略检索独立贡献 +${tcVsBaseline.toFixed(1)}pp（13局，统计功效有限）`,
                  both: `叠加后 ${bothVsAnti>=0?"+":""}${bothVsAnti.toFixed(1)}pp vs Anti（13局 vs 20局，样本不对称）`,
                };
                return (
                  <tr key={tier} className="border-b" style={{ borderColor:"var(--color-border)" }}>
                    <td className="py-2 text-xs font-medium"><span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full" style={{background:TIER_META[tier].color}}/>{TIER_META[tier].name}</span></td>
                    <td className="py-2 text-right font-mono text-xs">{e.games}</td>
                    <td className="py-2 text-right font-mono text-xs">{e.village}%</td>
                    <td className="py-2 text-right font-mono text-xs font-semibold">{e.wolf}%</td>
                    <td className="py-2 text-right font-mono text-xs" style={{color:tier==="baseline"?"var(--color-text-sub)":vsBase>=0?"var(--color-success)":"var(--color-danger)"}}>{tier==="baseline"?"-":delta(e.wolf,EXPERIMENT.baseline.wolf)}</td>
                    <td className="py-2 text-right font-mono text-xs text-text-sub">{prev?delta(e.wolf,prev.wolf):"-"}</td>
                    <td className="py-2 text-[11px] text-text-sub">{notes[tier]||""}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          <div className="mt-4 grid grid-cols-4 gap-4 text-center">
            <MiniStat label={t("Baseline 狼人胜率","Baseline Wolf")} value={`${EXPERIMENT.baseline.wolf}%`} />
            <MiniStat label={t("Anti 狼人增量","Anti Δ")} value={`+${antiVsBaseline.toFixed(0)}pp`} tone="good" />
            <MiniStat label={t("Track C 独立增量","Track C Δ")} value={`+${tcVsBaseline.toFixed(1)}pp`} tone="neutral" />
            <MiniStat label={t("完整三层狼人胜率","Both Wolf")} value={`${EXPERIMENT.both.wolf}%`} tone="good" />
          </div>
        </section>

        {/* ═══ 2. STRATEGY CARDS (from DB) ═══ */}
        <section className="rounded-lg border p-5" style={{ borderColor:"var(--color-border)", background:"var(--color-card)" }}>
          <h2 className="text-base font-semibold text-textPrimary mb-3">
            {t("策略卡片", "Strategy Cards")}
            <span className="ml-2 text-xs font-normal text-text-sub">{activeCards.length} active {t("（从 role_strategy_cards 读取）","(from role_strategy_cards)")}</span>
          </h2>
          {loading ? <p className="text-xs text-text-sub">{t("加载中...","Loading...")}</p>
          : activeCards.length===0 ? <p className="text-xs text-text-sub">{t("暂无策略卡片","No cards")}</p>
          : (
            <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
              {activeCards.map(card => {
                const hasRoleStats = roleStats[card.role];
                return (
                <div key={card.card_id} className="rounded-lg border p-4" style={{ borderColor:"var(--color-border)", background:"rgba(255,255,255,0.025)" }}>
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <span className="h-2.5 w-2.5 rounded-full" style={{ background:ROLE_COLORS[card.role]||"#9ca3af" }}/>
                      <span className="text-sm font-semibold">{card.role}</span>
                      <span className="rounded px-1.5 text-[10px] text-text-sub bg-white/5">{card.version}</span>
                    </div>
                    <span className="text-[10px] text-text-sub">{card.status}</span>
                  </div>
                  <p className="text-xs text-text-sub mb-2">{card.goal}</p>
                  {hasRoleStats && (
                    <div className="grid grid-cols-3 gap-1 mb-2 text-[10px]">
                      <div className="text-center rounded bg-white/5 px-1 py-0.5"><span className="text-text-sub">检索 </span><span className="font-mono">{hasRoleStats.usage.toLocaleString()}</span></div>
                      <div className="text-center rounded bg-white/5 px-1 py-0.5"><span className="text-text-sub">命中 </span><span className="font-mono text-success">{hasRoleStats.usage>0?(hasRoleStats.success/hasRoleStats.usage*100).toFixed(0):0}%</span></div>
                      <div className="text-center rounded bg-white/5 px-1 py-0.5"><span className="text-text-sub">文档 </span><span className="font-mono">{hasRoleStats.active}</span></div>
                    </div>
                  )}
                  {(["speech","vote","skill"] as const).map(p => {
                    const items = (card as any)[p+"_policy"]||[];
                    if (!items.length) return null;
                    return (
                      <div key={p} className="mb-1">
                        <span className="text-[10px] font-semibold uppercase text-text-sub/60">{p==="speech"?t("发言","Speech"):p==="vote"?t("投票","Vote"):t("技能","Skill")}</span>
                        <ul className="list-disc list-inside space-y-0.5 mt-0.5">{items.slice(0,2).map((x:string,j:number)=><li key={j} className="text-[11px] text-textPrimary">{x}</li>)}</ul>
                      </div>
                    );
                  })}
                  {card.risk_rules?.length>0 && (
                    <div className="mt-2 rounded border border-amber-500/20 px-2.5 py-2 bg-amber-500/5">
                      <span className="text-[10px] font-semibold text-amber-500">{t("规避","Risk")}</span>
                      <ul className="list-disc list-inside space-y-0.5 mt-0.5">{card.risk_rules.slice(0,2).map((r,j)=><li key={j} className="text-[11px] text-text-sub">{r}</li>)}</ul>
                    </div>
                  )}
                </div>
              );})}
            </div>
          )}
        </section>

        {/* ═══ 3. TRACK C RETRIEVAL EFFECTIVENESS ═══ */}
        <section className="rounded-lg border p-5" style={{ borderColor:"var(--color-border)", background:"var(--color-card)" }}>
          <h2 className="text-base font-semibold text-textPrimary mb-1">{t("Track C 策略检索效果", "Track C Retrieval Effectiveness")}</h2>
          <p className="text-xs text-text-sub mb-4">
            {t("对局中 Agent 通过 recall_memory / search_strategies 工具检索知识库。usage = 该角色策略被检索命中的总次数，hit% = 成功应用 / 总检索。", "Agents retrieve strategies via recall_memory/search_strategies tools. usage = total retrieval hits, hit% = successful applications / total retrievals.")}
          </p>

          <div className="grid gap-4 md:grid-cols-3 mb-5">
            <div className="rounded-lg border p-4 text-center" style={{ borderColor:"var(--color-border)" }}>
              <p className="text-2xl font-bold text-textPrimary">{totalUsage.toLocaleString()}</p>
              <p className="text-xs text-text-sub">{t("策略总检索次数", "Total strategy retrievals")}</p>
            </div>
            <div className="rounded-lg border p-4 text-center" style={{ borderColor:"var(--color-border)" }}>
              <p className="text-2xl font-bold" style={{color:tcVsBaseline>0?"var(--color-success)":"var(--color-textPrimary)"}}>{delta(EXPERIMENT.trackc_only.wolf, EXPERIMENT.baseline.wolf)}</p>
              <p className="text-xs text-text-sub">{t("Track C 独立效果 vs Baseline", "Track C alone vs Baseline")}</p>
            </div>
            <div className="rounded-lg border p-4 text-center" style={{ borderColor:"var(--color-border)" }}>
              <p className="text-2xl font-bold" style={{color:bothVsBaseline>0?"var(--color-success)":"var(--color-textPrimary)"}}>{delta(EXPERIMENT.both.wolf, EXPERIMENT.baseline.wolf)}</p>
              <p className="text-xs text-text-sub">{t("完整三层效果 vs Baseline", "Full stack vs Baseline")}</p>
            </div>
          </div>

          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-xs uppercase tracking-wide text-text-sub" style={{ borderColor:"var(--color-border)" }}>
                <th className="py-2 text-left">{t("角色","Role")}</th>
                <th className="py-2 text-right">{t("检索次数","Retrievals")}</th>
                <th className="py-2 text-right">{t("成功","OK")}</th>
                <th className="py-2 text-right">{t("失败","Fail")}</th>
                <th className="py-2 text-right">{t("命中率","Hit%")}</th>
                <th className="py-2 text-right">{t("活跃文档","Active")}</th>
                <th className="py-2 text-right">{t("策略卡","Card")}</th>
                <th className="py-2 text-right">{t("实验局数","Exp n")}</th>
              </tr>
            </thead>
            <tbody>
              {ROLES.map(role => {
                const s = roleStats[role] || { usage:0, success:0, failure:0, active:0 };
                const hit = s.usage>0?s.success/s.usage:0;
                const hasCard = activeCards.some(c=>c.role===role);
                return (
                  <tr key={role} className="border-b" style={{ borderColor:"var(--color-border)" }}>
                    <td className="py-1.5"><span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full" style={{background:ROLE_COLORS[role]}}/>{role}</span></td>
                    <td className="py-1.5 text-right font-mono text-xs">{s.usage>0?s.usage.toLocaleString():"-"}</td>
                    <td className="py-1.5 text-right font-mono text-xs text-success">{s.success>0?s.success.toLocaleString():"-"}</td>
                    <td className="py-1.5 text-right font-mono text-xs text-text-sub">{s.failure>0?s.failure.toLocaleString():"-"}</td>
                    <td className="py-1.5 text-right font-mono text-xs" style={{color:hit>=0.35?"var(--color-success)":hit>=0.25?"var(--color-warning)":"var(--color-text-sub)"}}>{s.usage>0?`${(hit*100).toFixed(0)}%`:"-"}</td>
                    <td className="py-1.5 text-right font-mono text-xs">{s.active>0?s.active:"-"}</td>
                    <td className="py-1.5 text-center text-xs">{hasCard?<span className="text-success">✓</span>:"-"}</td>
                    <td className="py-1.5 text-right font-mono text-xs">{PER_ROLE_GAMES}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>

        {/* ═══ 4. KNOWLEDGE BASE ═══ */}
        <section className="rounded-lg border p-5" style={{ borderColor:"var(--color-border)", background:"var(--color-card)" }}>
          <h2 className="text-base font-semibold text-textPrimary mb-3">
            {t("知识库", "Knowledge Base")}
            <span className="ml-2 text-xs font-normal text-text-sub">
              {knowledge.length} entries {t("（从 strategy_knowledge_docs 读取）","(from strategy_knowledge_docs)")}
            </span>
          </h2>
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
                {knowledge.slice(0,50).map(k => (
                  <tr key={k.doc_id} className="border-b" style={{ borderColor:"var(--color-border)" }}>
                    <td className="py-1"><span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full" style={{background:ROLE_COLORS[k.role]||"#9ca3af"}}/>{k.role}</span></td>
                    <td className="py-1 text-xs text-text-sub">{k.phase}</td>
                    <td className="py-1 max-w-xs text-xs truncate">{k.recommended_action||k.situation_pattern}</td>
                    <td className="py-1 text-right font-mono text-xs" style={{color:k.quality_score>=0.7?"var(--color-success)":k.quality_score>=0.4?"var(--color-warning)":"var(--color-text-sub)"}}>{k.quality_score.toFixed(2)}</td>
                    <td className="py-1 text-right font-mono text-xs">{k.usage_count}</td>
                    <td className="py-1 text-right font-mono text-xs text-success">{k.success_count}</td>
                    <td className="py-1 text-right font-mono text-xs text-text-sub">{k.failure_count}</td>
                    <td className="py-1 text-right text-[10px] text-text-sub">{(k.confidence_tier||"").replace("L","").replace("_"," ")}</td>
                    <td className="py-1 text-right text-[10px]" style={{color:k.status==="active"?"var(--color-success)":k.status==="deprecated"?"var(--color-text-sub)":"var(--color-warning)"}}>{k.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* ═══ 5. MBTI x ROLE ═══ */}
        <section className="rounded-lg border p-5" style={{ borderColor:"var(--color-border)", background:"var(--color-card)" }}>
          <h2 className="text-base font-semibold text-textPrimary mb-3">{t("MBTI × 角色胜率变化", "MBTI × Role Win Rate Δ")}</h2>
          <p className="text-xs text-text-sub mb-3">{t("both vs baseline，全玩家口径。颜色深度 = |Δ| 大小。nB/nBoth = 各层玩家样本数。", "both vs baseline, per-player. Color depth = |Δ| magnitude. n = per-tier player samples.")}</p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b" style={{ borderColor:"var(--color-border)" }}>
                  <th className="py-1.5 text-left font-semibold w-16">MBTI</th>
                  {ROLES.map(r => <th key={r} className="py-1.5 text-center font-semibold w-24">{r}</th>)}
                </tr>
              </thead>
              <tbody>
                {Array.from(new Set(MBTI_ROLE_DELTA.map(d=>d.mbti))).sort().map(mbti => {
                  const entries = MBTI_ROLE_DELTA.filter(d=>d.mbti===mbti);
                  return (
                    <tr key={mbti} className="border-b" style={{ borderColor:"var(--color-border)" }}>
                      <td className="py-1 font-medium">{mbti}</td>
                      {ROLES.map(role => {
                        const e = entries.find(d=>d.role===role);
                        if (!e) return <td key={role} className="py-1 text-center text-text-sub/20">-</td>;
                        const bg = e.delta>30?"rgba(16,185,129,0.18)":e.delta>0?"rgba(16,185,129,0.07)":e.delta>-30?"rgba(239,68,68,0.07)":"rgba(239,68,68,0.15)";
                        return (
                          <td key={role} className="py-1 text-center rounded" style={{background:bg}}>
                            <span className="font-mono font-semibold" style={{color:e.delta>0?"var(--color-success)":"var(--color-danger)"}}>{e.delta>0?"+":""}{e.delta.toFixed(0)}pp</span>
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
        </section>

        {/* ═══ 6. B/C ACCEPTANCE ═══ */}
        {acceptance.length>0 && (
          <section className="rounded-lg border p-5" style={{ borderColor:"var(--color-border)", background:"var(--color-card)" }}>
            <h2 className="text-base font-semibold text-textPrimary mb-3">
              {t("B/C 验收", "B/C Acceptance")}
              {api?.acceptance_audit?.overall_success_rate != null && (
                <span className={`ml-2 text-xs ${api.acceptance_audit.passed?"text-success":"text-danger"}`}>
                  {Math.round(api.acceptance_audit.overall_success_rate*100)}% pass
                </span>
              )}
            </h2>
            <div className="grid gap-4 md:grid-cols-2">
              {(["B","C"] as const).map(track => {
                const items = acceptance.filter(m=>m.track===track);
                return (
                  <div key={track}>
                    <p className="text-xs font-semibold uppercase tracking-wide text-text-sub mb-2">{track==="B"?t("反模式验收","Anti-Pattern"):t("策略检索验收","Strategy Retrieval")}</p>
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

function MiniStat({ label, value, tone }: { label:string; value:string; tone?:"good"|"neutral" }) {
  const c = tone==="good"?"var(--color-success)":tone==="neutral"?"var(--color-warning, #f59e0b)":"var(--color-textPrimary)";
  return <div className="rounded border p-3" style={{ borderColor:"var(--color-border)" }}><p className="text-xl font-bold" style={{color:c}}>{value}</p><p className="text-[10px] text-text-sub">{label}</p></div>;
}
