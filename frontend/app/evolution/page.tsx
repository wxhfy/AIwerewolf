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
  status: string;
}
interface KnowledgeDoc {
  doc_id: string; role: string; phase: string; quality_score: number;
  usage_count: number; success_count: number; failure_count: number;
  status: string; recommended_action: string; situation_pattern: string; confidence_tier: string;
  evidence_summary?: string; rationale?: string;
}
interface AcceptanceMetric { track: string; step_id: string; name: string; numerator: number; denominator: number; success_rate: number; threshold: number; passed: boolean; evidence: string; }
interface ApiDashboard { active_versions: StrategyCard[]; knowledge: KnowledgeDoc[]; acceptance_metrics: AcceptanceMetric[]; acceptance_audit?: { overall_success_rate?: number; passed?: boolean }; }
interface WinStat { wins: number; games: number; win_rate: number | null; wilson_95_ci?: [number, number]; fallback_decisions?: number; invalid_decisions?: number; }
interface DeltaStat { baseline_win_rate: number | null; current_win_rate: number | null; delta: number | null; baseline_games: number; current_games: number; }
interface TierSummary {
  games_completed: number; games_failed: number; completion_rate: number;
  winner_counts?: Record<string, number>;
  game_win_rate?: Record<string, WinStat>;
  team_role_games?: Record<string, WinStat>;
  role?: Record<string, WinStat>;
  mbti?: Record<string, WinStat>;
}
interface FullVictoryReport {
  generated_at: string;
  sources?: Record<string, string>;
  run_metadata?: { tier_labels?: string[]; mbti_acceptance_label?: string };
  multi_tier?: {
    tiers?: Record<string, TierSummary>;
    tier_deltas?: Record<string, {
      game_win_rate?: Record<string, DeltaStat>;
      team_role_games?: Record<string, DeltaStat>;
      role?: Record<string, DeltaStat>;
      mbti?: Record<string, DeltaStat>;
    }>;
  };
  multi_tier_source_distribution?: { providers?: Record<string, number>; models?: Record<string, number> };
  mbti_acceptance?: {
    games_succeeded: number; games_failed: number; games_requested?: number;
    player_count?: number; strict_no_fallback?: boolean;
    llm_decision_total?: number; fallback_decision_total?: number; invalid_decision_total?: number;
    mbti_stats?: Record<string, WinStat>;
    role_stats?: Record<string, WinStat>;
    alignment_stats?: Record<string, WinStat>;
    mbti_role_stats?: Record<string, WinStat>;
    mbti_alignment_stats?: Record<string, WinStat>;
    provider?: string; model?: string; model_pool?: string[];
  };
}

/* ── Constants ── */
const ROLES = ["Seer","Witch","Hunter","Guard","Villager","Werewolf"] as const;
const GOD_ROLES = ["Seer","Witch","Hunter","Guard"] as const;
const ROLE_COLORS: Record<string, string> = { Seer:"#a78bfa", Witch:"#34d399", Hunter:"#fbbf24", Guard:"#60a5fa", Villager:"#9ca3af", Werewolf:"#f87171", WhiteWolfKing:"#ef4444" };
const ROLE_LABELS: Record<string, string> = { Seer:"预言家", Witch:"女巫", Hunter:"猎人", Guard:"守卫", Villager:"村民", Werewolf:"狼人", WhiteWolfKing:"白狼王" };
const PHASE_LABELS: Record<string, string> = { DAY_SPEECH:"白天发言", DAY_VOTE:"放逐投票", NIGHT_ACTION:"夜晚行动", BADGE_SPEECH:"警徽发言", NIGHT_SEER_ACTION:"查验" };
const PER_ROLE_GAMES = 20;

/* ── MBTI × Role data ── */
const MBTI_ROLE_DELTA: { mbti: string; role: string; delta: number; nB: number; nBoth: number }[] = [
  { mbti:"ENTP", role:"Werewolf", delta:+100, nB:1, nBoth:2 }, { mbti:"INFJ", role:"Guard", delta:+100, nB:1, nBoth:1 },
  { mbti:"INFP", role:"Seer", delta:+100, nB:1, nBoth:1 }, { mbti:"ENTJ", role:"Werewolf", delta:+66.7, nB:3, nBoth:3 },
  { mbti:"ENFJ", role:"Werewolf", delta:+50, nB:6, nBoth:2 }, { mbti:"ENFJ", role:"Witch", delta:+50, nB:2, nBoth:2 },
  { mbti:"ESTP", role:"Witch", delta:+50, nB:3, nBoth:2 }, { mbti:"ISFP", role:"Hunter", delta:+50, nB:2, nBoth:2 },
  { mbti:"ISTP", role:"Werewolf", delta:+50, nB:1, nBoth:2 }, { mbti:"INTJ", role:"Seer", delta:+30, nB:5, nBoth:2 },
  { mbti:"INTJ", role:"Werewolf", delta:+20, nB:5, nBoth:2 }, { mbti:"ESFJ", role:"Villager", delta:-6.7, nB:5, nBoth:3 },
  { mbti:"ESTJ", role:"Villager", delta:-16.7, nB:2, nBoth:3 }, { mbti:"INFJ", role:"Seer", delta:-16.7, nB:4, nBoth:3 },
  { mbti:"ENFJ", role:"Guard", delta:-33.3, nB:3, nBoth:2 }, { mbti:"ESTP", role:"Werewolf", delta:-33.3, nB:3, nBoth:1 },
  { mbti:"INFP", role:"Guard", delta:-33.3, nB:3, nBoth:2 }, { mbti:"ISTJ", role:"Seer", delta:-33.3, nB:3, nBoth:2 },
  { mbti:"ISTJ", role:"Witch", delta:-33.3, nB:3, nBoth:1 }, { mbti:"ESFJ", role:"Hunter", delta:-50, nB:2, nBoth:1 },
  { mbti:"INFP", role:"Hunter", delta:-50, nB:2, nBoth:1 }, { mbti:"ISTJ", role:"Werewolf", delta:-50, nB:3, nBoth:2 },
  { mbti:"INFP", role:"Werewolf", delta:-66.7, nB:2, nBoth:3 }, { mbti:"ENFP", role:"Witch", delta:-100, nB:1, nBoth:2 },
];

/* ── Helpers ── */
function bestText(k: KnowledgeDoc): string {
  for (const f of [k.situation_pattern, k.recommended_action, k.evidence_summary as string, k.rationale as string])
    if (f && /[一-鿿]/.test(f)) return f;
  return k.recommended_action || k.situation_pattern || "";
}

function pct(value?: number | null): string {
  return value == null ? "-" : `${(value * 100).toFixed(1)}%`;
}

function pp(value?: number | null): string {
  if (value == null) return "-";
  const n = value * 100;
  return `${n > 0 ? "+" : ""}${n.toFixed(1)}pp`;
}

function ci(stat?: WinStat): string {
  return stat?.wilson_95_ci ? `${pct(stat.wilson_95_ci[0])} - ${pct(stat.wilson_95_ci[1])}` : "-";
}

function statEntries(stats?: Record<string, WinStat>, limit?: number) {
  const rows = Object.entries(stats || {}).sort((a, b) => {
    const rateDelta = (b[1].win_rate ?? -1) - (a[1].win_rate ?? -1);
    return rateDelta || b[1].games - a[1].games || a[0].localeCompare(b[0]);
  });
  return typeof limit === "number" ? rows.slice(0, limit) : rows;
}

function compactModelName(name: string): string {
  return name.replace(/^deepseek:/, "").replace(/^doubao:/, "").replace(/^dsv4flash:/, "");
}

export default function EvolutionPage() {
  const { language } = useAppContext();
  const t = (zh: string, en: string) => language === "zh" ? zh : en;
  const [api, setApi] = useState<ApiDashboard | null>(null);
  const [report, setReport] = useState<FullVictoryReport | null>(null);
  const [tab, setTab] = useState<"experiment"|"mbti"|"perrole"|"cards"|"knowledge"|"accept">("experiment");
  const [loading, setLoading] = useState(true);
  const [reportLoading, setReportLoading] = useState(true);
  const [expandedCard, setExpandedCard] = useState<string | null>(null);

  useEffect(() => { (async () => {
    try { const r = await fetch(apiUrl("/api/evolution/dashboard")); if (r.ok) setApi(await r.json()); } catch { setApi(null); }
    finally { setLoading(false); }
  })(); }, []);
  useEffect(() => { (async () => {
    try { const r = await fetch("/experiments/full_victory_report.json", { cache: "no-store" }); if (r.ok) setReport(await r.json()); } catch { setReport(null); }
    finally { setReportLoading(false); }
  })(); }, []);

  const cards = (api?.active_versions || []).filter(c => c.status === "active");
  const knowledge = api?.knowledge || [];
  const acceptance = api?.acceptance_metrics || [];
  const godCards = cards.filter(c => (GOD_ROLES as readonly string[]).includes(c.role));
  const wolfCards = cards.filter(c => c.role === "Werewolf" || c.role === "WhiteWolfKing");
  const villagerCards = cards.filter(c => c.role === "Villager");

  const roleStats = useMemo(() => {
    const m: Record<string, { usage: number; success: number; active: number }> = {};
    for (const k of knowledge) {
      const r = k.role; if (!m[r]) m[r] = { usage:0, success:0, active:0 };
      m[r].usage += k.usage_count||0; m[r].success += k.success_count||0; m[r].active++;
    }
    return m;
  }, [knowledge]);

  const tabDefs = [
    ["experiment", "完整实验", "Full Runs"],
    ["mbti", "MBTI×角色", "MBTI×Role"],
    ["perrole", "单角色 Track C", "Per-Role TC"],
    ["cards", "策略卡片", "Cards"],
    ["knowledge", "知识库", "Knowledge"],
    ["accept", "B/C验收", "Acceptance"],
  ] as const;

  return (
    <main className="min-h-screen px-5 py-6" style={{ background: "var(--color-bg)" }}>
      <div className="mx-auto max-w-7xl space-y-5">
        <header className="flex flex-wrap items-center justify-between gap-3 pb-2 border-b" style={{ borderColor: "var(--color-border)" }}>
          <div><h1 className="text-2xl font-bold text-textPrimary">{t("策略进化", "Strategy Evolution")}</h1><p className="text-xs text-text-sub mt-0.5">7P · strict · v4-flash · hybrid_role_mbti_global · {report?.generated_at?.slice(0, 10) || t("报告加载中", "loading report")}</p></div>
          <Link href="/" className="rounded border px-3 py-1.5 text-sm text-textPrimary" style={{ borderColor: "var(--color-border)" }}>{t("大厅", "Lobby")}</Link>
        </header>
        <div className="flex gap-1 overflow-x-auto pb-1">
          {tabDefs.map(([key, zh, en]) => (
            <button key={key} onClick={() => setTab(key as any)} className="rounded px-4 py-2 text-sm font-medium transition"
              style={{ background: tab===key ? "var(--color-primary, #3b82f6)" : "transparent", color: tab===key ? "#fff" : "var(--color-text-sub)" }}>{t(zh, en)}</button>
          ))}
        </div>

        {/* Full experiment report */}
        {tab === "experiment" && <ExperimentReportTab t={t} report={report} loading={reportLoading} />}

        {/* MBTI × Role */}
        {tab === "mbti" && <MBTIRoleTab t={t} report={report} loading={reportLoading} />}

        {/* Per-Role Track C */}
        {tab === "perrole" && <PerRoleTab t={t} roles={ROLES as unknown as string[]} roleLabels={ROLE_LABELS} roleColors={ROLE_COLORS} roleStats={roleStats} />}

        {/* Strategy Cards */}
        {tab === "cards" && <CardsTab t={t} loading={loading} godCards={godCards} wolfCards={wolfCards} villagerCards={villagerCards} roleStats={roleStats} roleLabels={ROLE_LABELS} roleColors={ROLE_COLORS} expandedCard={expandedCard} setExpandedCard={setExpandedCard} />}

        {/* Knowledge */}
        {tab === "knowledge" && <KnowledgeTab t={t} knowledge={knowledge} roleLabels={ROLE_LABELS} roleColors={ROLE_COLORS} phaseLabels={PHASE_LABELS} bestText={bestText} />}

        {/* B/C Acceptance */}
        {tab === "accept" && <AcceptTab t={t} acceptance={acceptance} audit={api?.acceptance_audit} />}
      </div>
    </main>
  );
}

/* ── Sub-components ── */

function ExperimentReportTab({ t, report, loading }: { t: (zh:string,en:string)=>string; report: FullVictoryReport | null; loading: boolean }) {
  if (loading) return <p className="text-sm text-text-sub px-3">{t("实验报告加载中...", "Loading experiment report...")}</p>;
  if (!report) return <p className="text-sm text-text-sub px-3">{t("未找到完整实验报告", "Full experiment report not found")}</p>;

  const tierLabels: Record<string, string> = {
    baseline: t("Baseline", "Baseline"),
    anti_only: t("仅反模式", "Anti only"),
    trackc_only: t("仅 Track C", "Track C only"),
    both: t("B + C", "B + C"),
  };
  const tierOrder = ["baseline", "anti_only", "trackc_only", "both"];
  const tiers = report.multi_tier?.tiers || {};
  const deltas = report.multi_tier?.tier_deltas || {};
  const mbti = report.mbti_acceptance;
  const providerRows = Object.entries(report.multi_tier_source_distribution?.providers || {}).sort((a, b) => b[1] - a[1]);
  const modelRows = Object.entries(report.multi_tier_source_distribution?.models || {}).sort((a, b) => b[1] - a[1]);
  const mbtiCount = Object.keys(mbti?.mbti_stats || {}).length;
  const mbtiRoleCount = Object.keys(mbti?.mbti_role_stats || {}).length;
  const mbtiAlignCount = Object.keys(mbti?.mbti_alignment_stats || {}).length;
  const minMbtiGames = Math.min(...Object.values(mbti?.mbti_stats || {}).map(s => s.games));

  return (
    <div className="space-y-5">
      <section className="rounded-lg border p-5" style={{ borderColor:"var(--color-border)", background:"var(--color-card)" }}>
        <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
          <div>
            <h2 className="text-base font-semibold text-textPrimary">{t("完整对局实验总览", "Full Game Run Overview")}</h2>
            <p className="text-xs text-text-sub mt-1">{t("四层策略实验 + 16 MBTI 接受度批次，严格无 fallback/invalid 决策。", "Four strategy tiers plus 16-MBTI acceptance batch with strict zero fallback/invalid decisions.")}</p>
          </div>
          <div className="flex flex-wrap gap-2 text-xs">
            <a className="rounded border px-3 py-1.5 text-textPrimary" style={{ borderColor:"var(--color-border)" }} href="/experiments/full_victory_report.html" target="_blank" rel="noreferrer">{t("打开 HTML 报告", "Open HTML Report")}</a>
            <a className="rounded border px-3 py-1.5 text-textPrimary" style={{ borderColor:"var(--color-border)" }} href="/experiments/full_victory_report.json" target="_blank" rel="noreferrer">JSON</a>
          </div>
        </div>
        <div className="grid gap-3 md:grid-cols-4">
          {tierOrder.map(key => {
            const tier = tiers[key];
            if (!tier) return null;
            const wolf = tier.game_win_rate?.wolf;
            const village = tier.game_win_rate?.village;
            const wolfDelta = deltas[key]?.game_win_rate?.wolf?.delta;
            return (
              <div key={key} className="rounded-lg border p-4" style={{ borderColor:"var(--color-border)", background:"rgba(255,255,255,0.03)" }}>
                <div className="flex items-center justify-between gap-2">
                  <h3 className="text-sm font-semibold text-textPrimary">{tierLabels[key] || key}</h3>
                  <span className="rounded px-2 py-0.5 text-[10px] bg-white/5 text-text-sub">{tier.games_completed}/{tier.games_completed + tier.games_failed}</span>
                </div>
                <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
                  <div><span className="text-text-sub">{t("狼人胜率", "Wolf WR")}</span><p className="font-mono text-base font-bold text-danger">{pct(wolf?.win_rate)}</p></div>
                  <div><span className="text-text-sub">{t("好人胜率", "Village WR")}</span><p className="font-mono text-base font-bold text-success">{pct(village?.win_rate)}</p></div>
                  <div><span className="text-text-sub">{t("失败局", "Failed")}</span><p className="font-mono">{tier.games_failed}</p></div>
                  <div><span className="text-text-sub">{t("狼胜Δ", "Wolf Δ")}</span><p className={`font-mono ${wolfDelta != null && wolfDelta >= 0 ? "text-danger" : "text-success"}`}>{key === "baseline" ? "-" : pp(wolfDelta)}</p></div>
                </div>
                <p className="mt-3 text-[10px] text-text-sub">{t("狼人 CI", "Wolf CI")}: {ci(wolf)}</p>
              </div>
            );
          })}
        </div>
      </section>

      <section className="rounded-lg border p-5" style={{ borderColor:"var(--color-border)", background:"var(--color-card)" }}>
        <h2 className="text-base font-semibold text-textPrimary mb-3">{t("MBTI 接受度覆盖", "MBTI Acceptance Coverage")}</h2>
        <div className="grid gap-3 md:grid-cols-5">
          {[
            [t("成功对局", "Succeeded"), mbti?.games_succeeded ?? 0],
            [t("失败对局", "Failed"), mbti?.games_failed ?? 0],
            [t("MBTI 类型", "MBTI Types"), mbtiCount],
            [t("MBTI×角色", "MBTI×Role"), mbtiRoleCount],
            [t("MBTI×阵营", "MBTI×Alignment"), mbtiAlignCount],
          ].map(([label, value]) => (
            <div key={label} className="rounded border p-3" style={{ borderColor:"var(--color-border)", background:"rgba(255,255,255,0.025)" }}>
              <p className="text-[10px] text-text-sub">{label}</p>
              <p className="mt-1 font-mono text-lg font-bold text-textPrimary">{value}</p>
            </div>
          ))}
        </div>
        <div className="mt-3 grid gap-3 md:grid-cols-4 text-xs">
          <div><span className="text-text-sub">{t("每 MBTI 最少成功局", "Min games per MBTI")}</span><p className="font-mono">{Number.isFinite(minMbtiGames) ? minMbtiGames : "-"}</p></div>
          <div><span className="text-text-sub">LLM decisions</span><p className="font-mono">{mbti?.llm_decision_total?.toLocaleString() || "-"}</p></div>
          <div><span className="text-text-sub">fallback</span><p className="font-mono text-success">{mbti?.fallback_decision_total ?? "-"}</p></div>
          <div><span className="text-text-sub">invalid</span><p className="font-mono text-success">{mbti?.invalid_decision_total ?? "-"}</p></div>
        </div>
      </section>

      <section className="grid gap-5 lg:grid-cols-2">
        <div className="rounded-lg border p-5" style={{ borderColor:"var(--color-border)", background:"var(--color-card)" }}>
          <h2 className="text-base font-semibold text-textPrimary mb-3">{t("MBTI 胜率 Top 8", "Top 8 MBTI Win Rates")}</h2>
          <div className="space-y-2">
            {statEntries(mbti?.mbti_stats, 8).map(([name, stat]) => (
              <div key={name} className="grid grid-cols-[4rem_1fr_4rem] items-center gap-3 text-xs">
                <span className="font-semibold">{name}</span>
                <div className="h-2 rounded-full bg-white/8"><div className="h-full rounded-full bg-success" style={{ width: `${Math.max(2, (stat.win_rate || 0) * 100)}%` }} /></div>
                <span className="font-mono text-right">{stat.wins}/{stat.games} · {pct(stat.win_rate)}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="rounded-lg border p-5" style={{ borderColor:"var(--color-border)", background:"var(--color-card)" }}>
          <h2 className="text-base font-semibold text-textPrimary mb-3">{t("模型与供应商来源", "Model and Provider Sources")}</h2>
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <p className="text-xs font-semibold text-text-sub mb-2">{t("供应商", "Providers")}</p>
              <div className="space-y-1.5">{providerRows.map(([name, count]) => <div key={name} className="flex justify-between gap-3 text-xs"><span>{name}</span><span className="font-mono">{count}</span></div>)}</div>
            </div>
            <div>
              <p className="text-xs font-semibold text-text-sub mb-2">{t("模型", "Models")}</p>
              <div className="space-y-1.5">{modelRows.map(([name, count]) => <div key={name} className="flex justify-between gap-3 text-xs"><span className="truncate">{compactModelName(name)}</span><span className="font-mono">{count}</span></div>)}</div>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}

function MBTIRoleTab({ t, report, loading }: { t: (zh:string,en:string)=>string; report: FullVictoryReport | null; loading: boolean }) {
  const reportStats = report?.mbti_acceptance?.mbti_role_stats;
  const reportRows = Object.entries(reportStats || {}).map(([key, stat]) => {
    const [mbti, role] = key.split("+");
    return { mbti, role, stat };
  }).filter(row => row.mbti && row.role);
  const mbtis = reportRows.length ? Array.from(new Set(reportRows.map(row => row.mbti))).sort() : Array.from(new Set(MBTI_ROLE_DELTA.map(d=>d.mbti))).sort();
  const statMap = new Map(reportRows.map(row => [`${row.mbti}+${row.role}`, row.stat]));

  return (
    <section className="rounded-lg border p-5" style={{ borderColor:"var(--color-border)", background:"var(--color-card)" }}>
      <h2 className="text-base font-semibold text-textPrimary mb-3">{t("MBTI × 角色 对局结果", "MBTI × Role Game Results")}</h2>
      <p className="text-xs text-text-sub mb-3">{reportRows.length ? t("使用完整 MBTI 接受度批次的真实分层胜率；每格显示 wins/games 和胜率。", "Using real stratified win rates from the full MBTI acceptance batch; each cell shows wins/games and win rate.") : t("真实报告加载前使用旧版 both vs baseline Δ 作为占位。", "Using legacy both-vs-baseline deltas while the report loads.")}</p>
      {loading && <p className="mb-3 text-xs text-text-sub">{t("报告加载中...", "Loading report...")}</p>}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead><tr className="border-b" style={{ borderColor:"var(--color-border)" }}><th className="py-1.5 text-left font-semibold w-16">MBTI</th>{ROLES.map(r=><th key={r} className="py-1.5 text-center font-semibold w-24">{ROLE_LABELS[r]||r}</th>)}</tr></thead>
          <tbody>{mbtis.map(mbti=>{const legacy=MBTI_ROLE_DELTA.filter(d=>d.mbti===mbti);return(<tr key={mbti} className="border-b" style={{borderColor:"var(--color-border)"}}><td className="py-1 font-medium">{mbti}</td>{ROLES.map(role=>{const stat=statMap.get(`${mbti}+${role}`);if(stat){const bg=(stat.win_rate || 0)>=0.6?"rgba(16,185,129,0.18)":(stat.win_rate || 0)>=0.4?"rgba(96,165,250,0.10)":"rgba(239,68,68,0.12)";return(<td key={role} className="py-1 text-center rounded" style={{background:bg}}><span className="font-mono font-semibold text-xs">{stat.wins}/{stat.games}</span><span className="block text-[9px] text-text-sub/60">{pct(stat.win_rate)}</span></td>)}const e=legacy.find(d=>d.role===role);if(!e)return <td key={role} className="py-1 text-center text-text-sub/20">-</td>;const bg=e.delta>30?"rgba(16,185,129,0.18)":e.delta>0?"rgba(16,185,129,0.07)":e.delta>-30?"rgba(239,68,68,0.07)":"rgba(239,68,68,0.15)";return(<td key={role} className="py-1 text-center rounded" style={{background:bg}}><span className="font-mono font-semibold text-xs" style={{color:e.delta>0?"var(--color-success)":"var(--color-danger)"}}>{e.delta>0?"+":""}{e.delta.toFixed(0)}pp</span><span className="block text-[9px] text-text-sub/50">n={e.nB}+{e.nBoth}</span></td>)})}</tr>)})}</tbody>
        </table>
      </div>
      <div className="flex items-center gap-4 mt-3 text-[10px] text-text-sub"><span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded bg-emerald-500/30"/> {t("高胜率", "High win rate")}</span><span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded bg-red-500/30"/> {t("低胜率", "Low win rate")}</span></div>
    </section>
  );
}

function PerRoleTab({ t, roles, roleLabels, roleColors, roleStats }: any) {
  return (
    <section className="rounded-lg border p-5" style={{ borderColor:"var(--color-border)", background:"var(--color-card)" }}>
      <h2 className="text-base font-semibold text-textPrimary mb-3">{t("单角色 Track C 效果", "Per-Role Track C")}</h2>
      <p className="text-xs text-text-sub mb-4">{t("每角色20局 baseline + 20局 Track C，hybrid_role_mbti_global 检索。胜率数据从 per_role_experiment.py 获取。", "20 baseline + 20 TC games per role. hybrid_role_mbti_global retrieval.")}</p>
      <div className="grid gap-4 md:grid-cols-3">
        {roles.map((role: string) => {
          const s = roleStats[role] || { usage:0, success:0, active:0 };
          const hit = s.usage>0 ? (s.success/s.usage*100).toFixed(0) : null;
          return (
            <div key={role} className="rounded-lg border p-4" style={{ borderColor:"var(--color-border)", background:"rgba(255,255,255,0.03)" }}>
              <div className="flex items-center gap-2 mb-3"><span className="h-3 w-3 rounded-full" style={{background:roleColors[role]}}/><span className="text-sm font-semibold">{roleLabels[role]||role}</span></div>
              <div className="grid grid-cols-2 gap-2 text-xs mb-3">
                <div><span className="text-text-sub">{t("检索次数","Retrievals")}</span><p className="font-mono">{s.usage>0?s.usage.toLocaleString():"-"}</p></div>
                <div><span className="text-text-sub">{t("命中率","Hit Rate")}</span><p className="font-mono text-success">{hit?`${hit}%`:"-"}</p></div>
                <div><span className="text-text-sub">{t("活跃文档","Active")}</span><p className="font-mono">{s.active||"-"}</p></div>
                <div><span className="text-text-sub">{t("实验局数","Games")}</span><p className="font-mono">{PER_ROLE_GAMES}</p></div>
              </div>
              <div className="pt-3 border-t text-center" style={{borderColor:"var(--color-border)"}}><span className="text-[10px] text-text-sub">{t("Track C 胜率变化","TC WR Δ")}</span><p className="text-lg font-bold" style={{color:"var(--color-primary)"}}>{t("实验进行中","Running...")}</p></div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function CardsTab({ t, loading, godCards, wolfCards, villagerCards, roleStats, roleLabels, expandedCard, setExpandedCard }: any) {
  if (loading) return <p className="text-sm text-text-sub px-3">{t("加载中...","Loading...")}</p>;
  if (godCards.length===0 && wolfCards.length===0) return <p className="text-sm text-text-sub px-3">{t("暂无策略卡片","No cards")}</p>;
  const groups = [
    { title: t("神职角色","God Roles"), items: godCards },
    { title: t("狼人角色","Wolf Roles"), items: wolfCards },
    { title: t("村民角色","Villager"), items: villagerCards },
  ].filter(g => g.items.length > 0);
  return (
    <div className="space-y-5">
      {groups.map(group => (
        <section key={group.title} className="rounded-lg border p-5" style={{ borderColor:"var(--color-border)", background:"var(--color-card)" }}>
          <h2 className="text-base font-semibold text-textPrimary mb-3">{group.title} <span className="text-xs font-normal text-text-sub ml-1">{group.items.length} cards</span></h2>
          <div className="grid gap-3 md:grid-cols-2">
            {group.items.map((card: StrategyCard) => {
              const isExp = expandedCard === card.card_id;
              const stats = roleStats[card.role];
              const hit = stats && stats.usage>0 ? (stats.success/stats.usage*100).toFixed(0) : null;
              return (
                <div key={card.card_id} className="rounded-lg border cursor-pointer transition"
                  style={{ borderColor: isExp ? (ROLE_COLORS[card.role]||"#9ca3af") : "var(--color-border)", background:"rgba(255,255,255,0.025)" }}
                  onClick={() => setExpandedCard(isExp ? null : card.card_id)}>
                  <div className="p-4">
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <span className="h-3 w-3 rounded-full" style={{ background:ROLE_COLORS[card.role]||"#9ca3af" }}/>
                        <span className="text-sm font-bold">{roleLabels[card.role]||card.role}</span>
                        <span className="rounded px-1.5 text-[10px] text-text-sub bg-white/5">{card.version}</span>
                      </div>
                      <div className="flex items-center gap-3 text-[10px] text-text-sub">
                        {stats && <span>{t("检索","Used")} {stats.usage.toLocaleString()}</span>}
                        {hit && <span className="text-success">{t("命中","Hit")} {hit}%</span>}
                        <span className="text-text-sub/40">{isExp ? "▲" : "▼"}</span>
                      </div>
                    </div>
                    <p className="text-xs text-text-sub line-clamp-2">{card.goal}</p>
                  </div>
                  {isExp && (
                    <div className="px-4 pb-4 border-t pt-3" style={{borderColor:"var(--color-border)"}} onClick={e=>e.stopPropagation()}>
                      {(["speech","vote","skill"] as const).map(p => {
                        const items = (card as any)[p+"_policy"]||[];
                        if (!items.length) return null;
                        return (<div key={p} className="mb-3"><span className="text-[10px] font-semibold uppercase text-text-sub/70">{p==="speech"?t("发言策略","Speech"):p==="vote"?t("投票策略","Vote"):t("技能策略","Skill")}</span><ul className="space-y-1 mt-1">{items.map((x:string,j:number)=><li key={j} className="text-xs text-textPrimary pl-3 relative before:content-['·'] before:absolute before:left-1">{x}</li>)}</ul></div>);
                      })}
                      {card.risk_rules?.length>0 && (
                        <div className="rounded border border-amber-500/20 px-3 py-2 bg-amber-500/5"><span className="text-[10px] font-semibold text-amber-400">{t("风险规避","Risk Rules")}</span><ul className="space-y-1 mt-1">{card.risk_rules.map((r:string,j:number)=><li key={j} className="text-[11px] text-text-sub pl-3 relative before:content-['⚠'] before:absolute before:left-0 before:text-[9px]">{r}</li>)}</ul></div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}

function KnowledgeTab({ t, knowledge, roleLabels, roleColors, phaseLabels, bestText }: any) {
  return (
    <section className="rounded-lg border p-5" style={{ borderColor:"var(--color-border)", background:"var(--color-card)" }}>
      <h2 className="text-base font-semibold text-textPrimary mb-3">{t("策略知识库", "Knowledge Base")} <span className="text-xs font-normal text-text-sub ml-1">{knowledge.length} entries</span></h2>
      <div className="grid gap-2 md:grid-cols-2 lg:grid-cols-3">
        {knowledge.slice(0,48).map((k: KnowledgeDoc) => {
          const text = bestText(k);
          const qC = k.quality_score>=0.7?"var(--color-success)":k.quality_score>=0.5?"var(--color-warning)":"var(--color-text-sub)";
          return (
            <div key={k.doc_id} className="rounded-lg border p-3" style={{ borderColor:"var(--color-border)", background:"rgba(255,255,255,0.025)" }}>
              <div className="flex items-center justify-between mb-1.5">
                <div className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full" style={{background:roleColors[k.role]||"#9ca3af"}}/><span className="text-xs font-semibold">{roleLabels[k.role]||k.role}</span><span className="text-[10px] text-text-sub">{phaseLabels[k.phase]||k.phase}</span></div>
                <span className="font-mono text-xs" style={{color:qC}}>{k.quality_score.toFixed(2)}</span>
              </div>
              <p className="text-xs text-textPrimary line-clamp-3 leading-relaxed">{text}</p>
              <div className="flex items-center justify-between mt-2 text-[10px] text-text-sub/60"><span>使用{k.usage_count} · 成功{k.success_count}</span><span>{(k.confidence_tier||"").replace("L","Lv").replace("_"," ")}</span></div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function AcceptTab({ t, acceptance, audit }: any) {
  return (
    <section className="rounded-lg border p-5" style={{ borderColor:"var(--color-border)", background:"var(--color-card)" }}>
      <h2 className="text-base font-semibold text-textPrimary mb-3">{t("B/C 验收", "B/C Acceptance")}
        {audit?.overall_success_rate != null && <span className={`ml-2 text-xs ${audit.passed?"text-success":"text-danger"}`}>{Math.round(audit.overall_success_rate*100)}%</span>}
      </h2>
      {acceptance.length===0 ? <p className="text-xs text-text-sub">{t("暂无验收数据","No data")}</p> : (
        <div className="grid gap-4 md:grid-cols-2">
          {(["B","C"] as const).map(track => {
            const items = acceptance.filter((m: AcceptanceMetric) => m.track===track);
            return (
              <div key={track}>
                <p className="text-xs font-semibold uppercase tracking-wide text-text-sub mb-2">{track==="B"?t("反模式验收","Anti-Pattern"):t("策略检索验收","Retrieval")}</p>
                <div className="space-y-2">{items.map((m: AcceptanceMetric) => (
                  <div key={m.step_id} className="rounded border p-2.5" style={{ borderColor:"var(--color-border)", background:"rgba(255,255,255,0.025)" }}>
                    <div className="flex items-start justify-between gap-2"><div><p className="text-xs font-medium">{m.step_id}</p><p className="text-[10px] text-text-sub mt-0.5">{m.name}</p></div><span className={m.passed?"text-xs font-semibold text-success":"text-xs font-semibold text-danger"}>{Math.round(m.success_rate*100)}%</span></div>
                    <div className="mt-1 h-1.5 rounded-full bg-white/8"><div className={`h-full rounded-full ${m.passed?"bg-success":"bg-danger"}`} style={{width:`${Math.max(2,m.success_rate*100)}%`}}/></div>
                  </div>
                ))}</div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
