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
  evidence_summary: string; rationale: string; confidence_tier: string;
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

/* ── Experiment data ── */

const TIER_ORDER = ["baseline", "anti_only", "trackc_only", "both"] as const;

const TIER_META: Record<string, { name: string; desc: string; color: string }> = {
  baseline:    { name: "Baseline",    desc: "纯 MBTI + Role",              color: "#6b7280" },
  anti_only:   { name: "Anti-Patterns", desc: "+ 静态反模式",              color: "#f59e0b" },
  trackc_only: { name: "Track C",       desc: "+ 动态策略检索",            color: "#3b82f6" },
  both:        { name: "Anti + Track C", desc: "完整三层",                 color: "#8b5cf6" },
};

const EXPERIMENT: Record<string, { games: number; village: number; wolf: number }> = {
  baseline:    { games: 18, village: 33.3, wolf: 66.7 },
  anti_only:   { games: 20, village: 20.0, wolf: 80.0 },
  trackc_only: { games: 13, village: 30.8, wolf: 69.2 },
  both:        { games: 13, village: 23.1, wolf: 76.9 },
};

const MBTI_ROLE_DELTA: { mbti: string; role: string; delta: number; nB: number; nBoth: number }[] = [
  { mbti:"ENTP", role:"Werewolf", delta:+100, nB:1, nBoth:2 },
  { mbti:"INFJ", role:"Guard", delta:+100, nB:1, nBoth:1 },
  { mbti:"INFP", role:"Seer", delta:+100, nB:1, nBoth:1 },
  { mbti:"ENTJ", role:"Werewolf", delta:+66.7, nB:3, nBoth:3 },
  { mbti:"ENFJ", role:"Werewolf", delta:+50, nB:6, nBoth:2 },
  { mbti:"ENFJ", role:"Witch", delta:+50, nB:2, nBoth:2 },
  { mbti:"ESTP", role:"Witch", delta:+50, nB:3, nBoth:2 },
  { mbti:"ISFP", role:"Hunter", delta:+50, nB:2, nBoth:2 },
  { mbti:"ISTP", role:"Werewolf", delta:+50, nB:1, nBoth:2 },
  { mbti:"INTJ", role:"Seer", delta:+30, nB:5, nBoth:2 },
  { mbti:"INTJ", role:"Werewolf", delta:+20, nB:5, nBoth:2 },
  { mbti:"ESFJ", role:"Villager", delta:-6.7, nB:5, nBoth:3 },
  { mbti:"ESTJ", role:"Villager", delta:-16.7, nB:2, nBoth:3 },
  { mbti:"INFJ", role:"Seer", delta:-16.7, nB:4, nBoth:3 },
  { mbti:"ENFJ", role:"Guard", delta:-33.3, nB:3, nBoth:2 },
  { mbti:"ESTP", role:"Werewolf", delta:-33.3, nB:3, nBoth:1 },
  { mbti:"INFP", role:"Guard", delta:-33.3, nB:3, nBoth:2 },
  { mbti:"ISTJ", role:"Seer", delta:-33.3, nB:3, nBoth:2 },
  { mbti:"ISTJ", role:"Witch", delta:-33.3, nB:3, nBoth:1 },
  { mbti:"ESFJ", role:"Hunter", delta:-50, nB:2, nBoth:1 },
  { mbti:"INFP", role:"Hunter", delta:-50, nB:2, nBoth:1 },
  { mbti:"ISTJ", role:"Werewolf", delta:-50, nB:3, nBoth:2 },
  { mbti:"INFP", role:"Werewolf", delta:-66.7, nB:2, nBoth:3 },
  { mbti:"ENFP", role:"Witch", delta:-100, nB:1, nBoth:2 },
];

const ROLES = ["Seer","Witch","Hunter","Guard","Villager","Werewolf"] as const;
const GOD_ROLES = ["Seer","Witch","Hunter","Guard"] as const;
const ROLE_COLORS: Record<string, string> = {
  Seer:"#a78bfa", Witch:"#34d399", Hunter:"#fbbf24", Guard:"#60a5fa",
  Villager:"#9ca3af", Werewolf:"#f87171", WhiteWolfKing:"#ef4444",
};
const ROLE_LABELS: Record<string, string> = {
  Seer:"预言家", Witch:"女巫", Hunter:"猎人", Guard:"守卫",
  Villager:"村民", Werewolf:"狼人", WhiteWolfKing:"白狼王",
};

const PHASE_LABELS: Record<string, string> = {
  DAY_SPEECH:"白天发言", DAY_VOTE:"放逐投票", NIGHT_ACTION:"夜晚行动",
  BADGE_SPEECH:"警徽发言", BADGE_ELECTION:"警徽投票", NIGHT_RESOLVE:"夜晚结算",
};

/* ── Helpers ── */

function isEnglishOnly(text: string): boolean {
  if (!text) return true;
  // If text contains any CJK character, it's not English-only
  return !/[一-鿿㐀-䶿]/.test(text);
}

function bestDisplayText(k: KnowledgeDoc): string {
  // Prefer Chinese text from any available field
  const fields = [k.situation_pattern, k.recommended_action, k.evidence_summary, k.rationale];
  for (const f of fields) {
    if (f && !isEnglishOnly(f)) return f;
  }
  // Fallback to first non-empty field (even if English)
  for (const f of fields) {
    if (f) return f;
  }
  return "";
}

function delta(a: number, b: number) { const v = a - b; return `${v>=0?"+":""}${v.toFixed(1)}pp`; }

/* ── Page ── */

export default function EvolutionPage() {
  const { language } = useAppContext();
  const t = (zh: string, en: string) => language === "zh" ? zh : en;
  const [api, setApi] = useState<ApiDashboard | null>(null);
  const [tab, setTab] = useState<"ablation"|"cards"|"knowledge"|"mbti"|"accept">("ablation");
  const [loading, setLoading] = useState(true);

  useEffect(() => { (async () => {
    try { const r = await fetch(apiUrl("/api/evolution/dashboard")); if (r.ok) setApi(await r.json()); }
    catch {} finally { setLoading(false); }
  })(); }, []);

  const cards = (api?.active_versions || []).filter(c => c.status === "active");
  const acceptance = api?.acceptance_metrics || [];

  // Only show active knowledge with de-identified, abstracted strategy content
  const knowledge = useMemo(() => {
    const raw = api?.knowledge || [];
    return raw.filter(k => {
      if (k.status !== "active") return false;
      const text = bestDisplayText(k);
      if (!text || isEnglishOnly(text)) return false;
      // Filter out raw game data: seat numbers (#号) and player names
      if (/\d+号/.test(text)) return false;
      if (/[顾景行苗信夏知霁川袁汐大壮宋知野]/.test(text)) return false;
      return true;
    });
  }, [api?.knowledge]);

  // Group cards by faction
  const godCards = cards.filter(c => GOD_ROLES.includes(c.role as any));
  const wolfCards = cards.filter(c => c.role === "Werewolf" || c.role === "WhiteWolfKing");
  const villagerCards = cards.filter(c => c.role === "Villager");

  // Per-role strategy stats
  const roleStats = useMemo(() => {
    const m: Record<string, { usage: number; success: number; active: number }> = {};
    for (const k of knowledge) {
      const r = k.role; if (!m[r]) m[r] = { usage:0, success:0, active:0 };
      m[r].usage += k.usage_count||0; m[r].success += k.success_count||0;
      m[r].active++;
    }
    return m;
  }, [knowledge]);

  // Active knowledge already filtered above: active + Chinese + de-identified

  return (
    <main className="min-h-screen px-5 py-6" style={{ background: "var(--color-bg)" }}>
      <div className="mx-auto max-w-7xl space-y-5">
        {/* Header */}
        <header className="flex flex-wrap items-center justify-between gap-3 pb-2 border-b" style={{ borderColor: "var(--color-border)" }}>
          <div>
            <h1 className="text-2xl font-bold text-textPrimary">{t("策略进化", "Strategy Evolution")}</h1>
            <p className="text-xs text-text-sub mt-0.5">7P · strict · doubao:deepseek-v4-flash · 每角色20局 · DB: 10K场</p>
          </div>
          <Link href="/" className="rounded border px-3 py-1.5 text-sm text-textPrimary" style={{ borderColor: "var(--color-border)" }}>
            {t("大厅", "Lobby")}
          </Link>
        </header>

        {/* ═══ Tabs ═══ */}
        <div className="flex gap-1 overflow-x-auto pb-1">
          {([
            ["ablation", "消融实验", "Ablation"],
            ["cards", "策略卡片", "Cards"],
            ["knowledge", "知识库", "Knowledge"],
            ["mbti", "MBTI×角色", "MBTI×Role"],
            ["accept", "B/C验收", "Acceptance"],
          ] as const).map(([key, zh, en]) => (
            <button key={key} onClick={() => setTab(key)}
              className="rounded px-4 py-2 text-sm font-medium transition"
              style={{
                background: tab===key ? "var(--color-primary, #3b82f6)" : "transparent",
                color: tab===key ? "#fff" : "var(--color-text-sub)",
              }}
            >{t(zh, en)}</button>
          ))}
        </div>

        {/* ═══ TAB: 消融实验 ═══ */}
        {tab === "ablation" && (
          <div className="space-y-5">
            <section className="rounded-lg border p-5" style={{ borderColor:"var(--color-border)", background:"var(--color-card)" }}>
              <h2 className="text-base font-semibold text-textPrimary mb-3">{t("逐层消融", "Layer Ablation")}</h2>
              <div className="space-y-2 mb-4">
                {TIER_ORDER.map((tier, i) => {
                  const e = EXPERIMENT[tier];
                  const prev = i>0?EXPERIMENT[TIER_ORDER[i-1]]:null;
                  const ly = prev?e.wolf-prev.wolf:0;
                  const m = TIER_META[tier];
                  return (
                    <div key={tier} className="flex items-center gap-3">
                      <div className="w-40 shrink-0 text-right"><span className="text-sm font-medium">{m.name}</span><div className="text-[11px] text-text-sub">{m.desc}</div></div>
                      <div className="flex-1"><div className="h-7 rounded flex items-center justify-end pr-2" style={{width:`${Math.max(2,e.wolf)}%`,background:m.color,opacity:0.85}}><span className="text-[10px] font-mono font-bold text-white">{e.wolf}%</span></div></div>
                      <span className="w-10 text-right font-mono text-xs text-text-sub">n={e.games}</span>
                      <span className="w-16 text-right font-mono text-xs" style={{color:tier==="baseline"?"transparent":e.wolf>=EXPERIMENT.baseline.wolf?"var(--color-success)":"var(--color-danger)"}}>{tier==="baseline"?"":delta(e.wolf,EXPERIMENT.baseline.wolf)}</span>
                      <span className="w-14 text-right font-mono text-[11px]" style={{color:ly>0?"var(--color-success)":ly<0?"var(--color-warning)":"var(--color-text-sub)"}}>{prev?(ly>=0?"+":"")+ly.toFixed(1)+"pp":""}</span>
                    </div>
                  );
                })}
              </div>
              <div className="grid grid-cols-4 gap-3 text-center">
                {[
                  ["Baseline 狼人胜率", `${EXPERIMENT.baseline.wolf}%`],
                  ["Anti-Patterns 增量", `+${(EXPERIMENT.anti_only.wolf-EXPERIMENT.baseline.wolf).toFixed(0)}pp`],
                  ["Track C 独立增量", `${delta(EXPERIMENT.trackc_only.wolf, EXPERIMENT.baseline.wolf)}`],
                  ["完整三层胜率", `${EXPERIMENT.both.wolf}%`],
                ].map(([label, value]) => (
                  <div key={label} className="rounded border p-3" style={{ borderColor:"var(--color-border)" }}>
                    <p className="text-xl font-bold">{value}</p><p className="text-[10px] text-text-sub">{label}</p>
                  </div>
                ))}
              </div>
            </section>
          </div>
        )}

        {/* ═══ TAB: 策略卡片 ═══ */}
        {tab === "cards" && (
          <div className="space-y-5">
            {loading ? <p className="text-sm text-text-sub px-3">{t("加载中...","Loading...")}</p> :
            cards.length===0 ? <p className="text-sm text-text-sub px-3">{t("暂无策略卡片","No cards yet")}</p> :
            <>
              {/* 神职 */}
              <section className="rounded-lg border p-5" style={{ borderColor:"var(--color-border)", background:"var(--color-card)" }}>
                <h2 className="text-base font-semibold text-textPrimary mb-3">{t("神职角色", "God Roles")} <span className="text-xs font-normal text-text-sub ml-1">{godCards.length} cards</span></h2>
                <div className="grid gap-3 md:grid-cols-2">
                  {godCards.map(card => <RoleCard key={card.card_id} card={card} stats={roleStats[card.role]} t={t} />)}
                </div>
              </section>

              {/* 狼人 */}
              <section className="rounded-lg border p-5" style={{ borderColor:"var(--color-border)", background:"var(--color-card)" }}>
                <h2 className="text-base font-semibold text-textPrimary mb-3">{t("狼人角色", "Wolf Roles")} <span className="text-xs font-normal text-text-sub ml-1">{wolfCards.length} cards</span></h2>
                <div className="grid gap-3 md:grid-cols-2">
                  {wolfCards.map(card => <RoleCard key={card.card_id} card={card} stats={roleStats[card.role]} t={t} />)}
                </div>
              </section>

              {/* 村民 */}
              {villagerCards.length > 0 && (
                <section className="rounded-lg border p-5" style={{ borderColor:"var(--color-border)", background:"var(--color-card)" }}>
                  <h2 className="text-base font-semibold text-textPrimary mb-3">{t("村民角色", "Villager Roles")} <span className="text-xs font-normal text-text-sub ml-1">{villagerCards.length} cards</span></h2>
                  <div className="grid gap-3 md:grid-cols-2">
                    {villagerCards.map(card => <RoleCard key={card.card_id} card={card} stats={roleStats[card.role]} t={t} />)}
                  </div>
                </section>
              )}
            </>}
          </div>
        )}

        {/* ═══ TAB: 知识库 ═══ */}
        {tab === "knowledge" && (
          <section className="rounded-lg border p-5" style={{ borderColor:"var(--color-border)", background:"var(--color-card)" }}>
            <h2 className="text-base font-semibold text-textPrimary mb-1">{t("策略知识库", "Knowledge Base")}</h2>
            <p className="text-xs text-text-sub mb-3">
              {knowledge.length} {t("条已脱敏策略 · 仅展示 active 状态 · 过滤了含座位号和玩家名的未抽象条目", "de-identified strategies · active only · raw game data filtered out")}
            </p>
            <div className="grid gap-2 md:grid-cols-2 lg:grid-cols-3">
              {knowledge.slice(0, 48).map(k => {
                const text = bestDisplayText(k);
                const qColor = k.quality_score>=0.7?"var(--color-success)":k.quality_score>=0.4?"var(--color-warning)":"var(--color-text-sub)";
                return (
                  <div key={k.doc_id} className="rounded-lg border p-3" style={{ borderColor:"var(--color-border)", background:"rgba(255,255,255,0.025)" }}>
                    <div className="flex items-center justify-between mb-1.5">
                      <div className="flex items-center gap-1.5">
                        <span className="h-2 w-2 rounded-full" style={{background:ROLE_COLORS[k.role]||"#9ca3af"}}/>
                        <span className="text-xs font-semibold">{k.role in ROLE_LABELS ? ROLE_LABELS[k.role] : k.role}</span>
                        <span className="text-[10px] text-text-sub">{PHASE_LABELS[k.phase] || k.phase}</span>
                      </div>
                      <span className="font-mono text-xs" style={{color:qColor}}>{k.quality_score.toFixed(2)}</span>
                    </div>
                    <p className="text-xs text-textPrimary line-clamp-3 leading-relaxed">{text}</p>
                    <div className="flex items-center justify-between mt-2 text-[10px] text-text-sub/60">
                      <span>使用{k.usage_count} · 成功{k.success_count}</span>
                      <span>{(k.confidence_tier||"").replace("L","Lv").replace("_"," ")}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {/* ═══ TAB: MBTI × Role ═══ */}
        {tab === "mbti" && (
          <section className="rounded-lg border p-5" style={{ borderColor:"var(--color-border)", background:"var(--color-card)" }}>
            <h2 className="text-base font-semibold text-textPrimary mb-3">{t("MBTI × 角色胜率变化", "MBTI × Role Win Rate Δ")}</h2>
            <p className="text-xs text-text-sub mb-3">{t("both vs baseline，颜色深度 = |Δ| 大小。n = 各层样本数。", "both vs baseline. Color depth = |Δ|. n = samples per tier.")}</p>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b" style={{ borderColor:"var(--color-border)" }}>
                    <th className="py-1.5 text-left font-semibold w-16">MBTI</th>
                    {ROLES.map(r => <th key={r} className="py-1.5 text-center font-semibold w-24">{r in ROLE_LABELS?ROLE_LABELS[r]:r}</th>)}
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
                              <span className="font-mono font-semibold text-xs" style={{color:e.delta>0?"var(--color-success)":"var(--color-danger)"}}>{e.delta>0?"+":""}{e.delta.toFixed(0)}pp</span>
                              <span className="block text-[9px] text-text-sub/50">{e.nB}+{e.nBoth}</span>
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
        )}

        {/* ═══ TAB: B/C Acceptance ═══ */}
        {tab === "accept" && (
          <section className="rounded-lg border p-5" style={{ borderColor:"var(--color-border)", background:"var(--color-card)" }}>
            <h2 className="text-base font-semibold text-textPrimary mb-3">
              {t("B/C 验收", "B/C Acceptance")}
              {api?.acceptance_audit?.overall_success_rate != null && (
                <span className={`ml-2 text-xs ${api.acceptance_audit.passed?"text-success":"text-danger"}`}>
                  {Math.round(api.acceptance_audit.overall_success_rate*100)}%
                </span>
              )}
            </h2>
            {acceptance.length===0 ? <p className="text-xs text-text-sub">{t("暂无验收数据","No acceptance data")}</p> : (
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
                              <div><p className="text-xs font-medium">{m.step_id}</p><p className="text-[10px] text-text-sub mt-0.5">{m.name}</p></div>
                              <span className={m.passed?"text-xs font-semibold text-success":"text-xs font-semibold text-danger"}>{Math.round(m.success_rate*100)}%</span>
                            </div>
                            <div className="mt-1 h-1.5 rounded-full bg-white/8"><div className={`h-full rounded-full ${m.passed?"bg-success":"bg-danger"}`} style={{width:`${Math.max(2,m.success_rate*100)}%`}}/></div>
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        )}
      </div>
    </main>
  );
}

/* ── Role Card Component ── */

function RoleCard({ card, stats, t }: { card: StrategyCard; stats?: { usage: number; success: number; active: number }; t: (zh:string,en:string)=>string }) {
  const color = ROLE_COLORS[card.role] || "#9ca3af";
  const label = ROLE_LABELS[card.role] || card.role;
  const hitRate = stats && stats.usage>0 ? (stats.success/stats.usage*100).toFixed(0) : null;

  return (
    <div className="rounded-lg border p-4" style={{ borderColor:"var(--color-border)", background:"rgba(255,255,255,0.025)" }}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="h-3 w-3 rounded-full" style={{ background:color }}/>
          <span className="text-sm font-bold">{label}</span>
          <span className="rounded px-1.5 text-[10px] text-text-sub bg-white/5">{card.version}</span>
        </div>
        {stats && (
          <div className="flex gap-2 text-[10px] text-text-sub">
            <span>{t("检索","Used")} {stats.usage.toLocaleString()}</span>
            {hitRate && <span className="text-success">{t("命中","Hit")} {hitRate}%</span>}
          </div>
        )}
      </div>

      <p className="text-xs text-text-sub mb-3">{card.goal}</p>

      {(["speech","vote","skill"] as const).map(p => {
        const items = (card as any)[p+"_policy"] || [];
        if (!items.length) return null;
        const title = p==="speech"?t("发言策略","Speech"):p==="vote"?t("投票策略","Vote"):t("技能策略","Skill");
        return (
          <div key={p} className="mb-2">
            <span className="text-[10px] font-semibold text-text-sub/70">{title}</span>
            <ul className="space-y-0.5 mt-0.5">
              {items.map((x:string,j:number) => <li key={j} className="text-xs text-textPrimary pl-3 relative before:content-['·'] before:absolute before:left-1">{x}</li>)}
            </ul>
          </div>
        );
      })}

      {card.risk_rules?.length>0 && (
        <div className="mt-2 rounded border border-amber-500/20 px-3 py-2 bg-amber-500/5">
          <span className="text-[10px] font-semibold text-amber-400">{t("风险规避","Risk Rules")}</span>
          <ul className="space-y-0.5 mt-0.5">
            {card.risk_rules.map((r,j) => <li key={j} className="text-[11px] text-text-sub pl-3 relative before:content-['⚠'] before:absolute before:left-0 before:text-[9px]">{r}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}
