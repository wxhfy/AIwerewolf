"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { apiUrl } from "@/lib/api";
import { useAppContext } from "@/context/AppContext";

interface EvolutionDashboard {
  active_versions: any[];
  knowledge: any[];
  patches: any[];
  tournaments: any[];
  acceptance_audit?: any;
  acceptance_metrics?: AcceptanceMetric[];
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
  details?: Record<string, any>;
}

export default function EvolutionPage() {
  const { language } = useAppContext();
  const [dashboard, setDashboard] = useState<EvolutionDashboard | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState("");
  const [cycleSummary, setCycleSummary] = useState<any>(null);
  const t = (zh: string, en: string) => (language === "zh" ? zh : en);

  async function loadDashboard() {
    setError("");
    try {
      const response = await fetch(apiUrl("/api/evolution/dashboard"));
      if (!response.ok) throw new Error(`dashboard ${response.status}`);
      setDashboard(await response.json());
    } catch (err: any) {
      setError(err.message || "load failed");
    } finally {
      setIsLoading(false);
    }
  }

  async function runCycle() {
    setIsRunning(true);
    setError("");
    try {
      const response = await fetch(apiUrl("/api/evolution/cycle"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ seeds: Array.from({ length: 20 }, (_, index) => index + 1) }),
      });
      if (!response.ok) throw new Error(`cycle ${response.status}`);
      const payload = await response.json();
      setCycleSummary(payload.summary);
      await loadDashboard();
    } catch (err: any) {
      setError(err.message || "cycle failed");
    } finally {
      setIsRunning(false);
    }
  }

  useEffect(() => {
    loadDashboard();
  }, []);

  const knowledge = dashboard?.knowledge || [];
  const patches = dashboard?.patches || [];
  const tournaments = dashboard?.tournaments || [];
  const versions = dashboard?.active_versions || [];
  const acceptanceMetrics = dashboard?.acceptance_metrics || [];
  const acceptanceAudit = dashboard?.acceptance_audit;

  return (
    <main className="min-h-screen px-5 py-6" style={{ background: "var(--color-bg)" }}>
      <div className="mx-auto max-w-7xl space-y-6">
        <header className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-wider text-text-sub">Track C</p>
            <h1 className="font-display text-3xl font-bold text-primary">
              {t("自进化控制台", "Evolution Dashboard")}
            </h1>
          </div>
          <div className="flex items-center gap-2">
            <Link href="/" className="rounded-button border px-4 py-2 text-sm text-textPrimary" style={{ borderColor: "var(--color-border)" }}>
              {t("返回大厅", "Lobby")}
            </Link>
            <button
              onClick={runCycle}
              disabled={isRunning}
              className="rounded-button bg-primary px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
            >
              {isRunning ? t("进化中...", "Running...") : t("运行 20 Seed A/B", "Run 20-Seed A/B")}
            </button>
          </div>
        </header>

        {error && <div className="rounded-card border border-danger/40 px-4 py-3 text-sm text-danger">{error}</div>}
        {cycleSummary && (
          <section className="grid gap-3 md:grid-cols-4">
            {[
              [t("知识条目", "Knowledge"), cycleSummary.knowledge_docs],
              [t("已校验 Patch", "Validated Patches"), cycleSummary.validated_patches],
              [t("晋升", "Promoted"), cycleSummary.promoted],
              [t("回滚", "Rolled Back"), cycleSummary.rolled_back],
            ].map(([label, value]) => (
              <div key={String(label)} className="rounded-card border p-4" style={{ background: "var(--color-card)", borderColor: "var(--color-border)" }}>
                <p className="text-xs text-text-sub">{label}</p>
                <p className="mt-2 text-2xl font-bold text-textPrimary">{String(value ?? 0)}</p>
              </div>
            ))}
          </section>
        )}

        {isLoading ? (
          <p className="text-text-sub">{t("加载中...", "Loading...")}</p>
        ) : (
          <>
            <AcceptancePanel
              metrics={acceptanceMetrics}
              overallRate={Number(acceptanceAudit?.overall_success_rate || 0)}
              passed={Boolean(acceptanceAudit?.passed)}
              t={t}
            />

            <section className="grid gap-4 lg:grid-cols-3">
              <Panel title={t("当前版本", "Active Versions")}>
                <div className="space-y-2">
                  {versions.slice(0, 6).map((item) => (
                    <Row key={`${item.role}-${item.version}`} title={`${item.role} · ${item.version}`} meta={item.status} value={item.parent_version || "root"} />
                  ))}
                  {!versions.length && <Empty text={t("暂无策略版本", "No strategy cards yet")} />}
                </div>
              </Panel>

              <Panel title={t("候选 Patch", "Candidate Patches")}>
                <div className="space-y-2">
                  {patches.slice(0, 6).map((item) => (
                    <Row key={item.patch_id} title={`${item.target_role || "global"} · ${item.to_version}`} meta={item.status} value={`${(item.operations || []).length} ops`} />
                  ))}
                  {!patches.length && <Empty text={t("暂无 Patch", "No patches yet")} />}
                </div>
              </Panel>

              <Panel title={t("A/B 实验", "A/B Tournaments")}>
                <div className="space-y-2">
                  {tournaments.slice(0, 6).map((item) => (
                    <Row
                      key={item.tournament_id}
                      title={`${item.baseline_version} → ${item.candidate_version}`}
                      meta={item.decision?.action || item.status}
                      value={`${Math.round((item.comparison?.candidate_target_role_avg_score || 0) * 10) / 10}`}
                    />
                  ))}
                  {!tournaments.length && <Empty text={t("暂无 A/B 结果", "No tournament results yet")} />}
                </div>
              </Panel>
            </section>

            <section className="grid gap-4 xl:grid-cols-[1.1fr,0.9fr]">
              <Panel title={t("策略知识库", "Knowledge Wiki")}>
                <div className="grid gap-2 md:grid-cols-2">
                  {knowledge.slice(0, 12).map((item) => (
                    <article key={item.doc_id} className="rounded-button border p-3" style={{ borderColor: "var(--color-border)", background: "rgba(255,255,255,0.04)" }}>
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-sm font-semibold text-textPrimary">{item.role} · {item.phase}</p>
                        <span className="text-xs text-primary">{Number(item.quality_score || 0).toFixed(2)}</span>
                      </div>
                      <p className="mt-2 line-clamp-2 text-xs text-text-sub">{item.recommended_action}</p>
                      <p className="mt-2 text-[11px] text-text-sub/70">{item.doc_type} · {item.status}</p>
                    </article>
                  ))}
                  {!knowledge.length && <Empty text={t("暂无策略知识", "No strategy knowledge yet")} />}
                </div>
              </Panel>

              <Panel title={t("版本排行榜", "Version Leaderboard")}>
                <div className="space-y-2">
                  {tournaments.slice(0, 10).map((item) => {
                    const c = item.comparison || {};
                    return (
                      <div key={`${item.tournament_id}-leaderboard`} className="rounded-button border p-3" style={{ borderColor: "var(--color-border)" }}>
                        <div className="flex items-center justify-between gap-3">
                          <p className="text-sm font-semibold text-textPrimary">{item.candidate_version}</p>
                          <span className="text-xs text-primary">{item.decision?.action || "-"}</span>
                        </div>
                        <div className="mt-2 grid grid-cols-3 gap-2 text-xs text-text-sub">
                          <span>{t("胜率", "Win")} {Number(c.candidate_camp_win_rate || 0).toFixed(2)}</span>
                          <span>{t("分数", "Score")} {Number(c.candidate_target_role_avg_score || 0).toFixed(1)}</span>
                          <span>{t("失误", "Mistakes")} {Number(c.candidate_critical_mistakes_per_game || 0).toFixed(2)}</span>
                        </div>
                      </div>
                    );
                  })}
                  {!tournaments.length && <Empty text={t("运行进化周期后显示", "Run a cycle to populate this")} />}
                </div>
              </Panel>
            </section>
          </>
        )}
      </div>
    </main>
  );
}

function AcceptancePanel({
  metrics,
  overallRate,
  passed,
  t,
}: {
  metrics: AcceptanceMetric[];
  overallRate: number;
  passed: boolean;
  t: (zh: string, en: string) => string;
}) {
  const trackB = metrics.filter((item) => item.track === "B");
  const trackC = metrics.filter((item) => item.track === "C");
  const renderTrack = (items: AcceptanceMetric[], title: string) => (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-wider text-text-sub">{title}</p>
        <span className="text-xs text-text-sub">
          {items.filter((item) => item.passed).length}/{items.length}
        </span>
      </div>
      <div className="grid gap-2 lg:grid-cols-2">
        {items.map((item) => (
          <div key={`${item.track}-${item.step_id}`} className="rounded-button border p-3" style={{ borderColor: "var(--color-border)", background: "rgba(255,255,255,0.035)" }}>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-xs font-semibold text-textPrimary">{item.step_id} · {item.name}</p>
                <p className="mt-1 line-clamp-1 text-[11px] text-text-sub">{item.evidence}</p>
              </div>
              <span className={item.passed ? "text-xs font-semibold text-success" : "text-xs font-semibold text-danger"}>
                {Math.round(item.success_rate * 100)}%
              </span>
            </div>
            <div className="mt-2 h-2 overflow-hidden rounded-full" style={{ background: "rgba(255,255,255,0.08)" }}>
              <div
                className={item.passed ? "h-full rounded-full bg-success" : "h-full rounded-full bg-danger"}
                style={{ width: `${Math.max(3, Math.min(100, item.success_rate * 100))}%` }}
              />
            </div>
            <div className="mt-2 flex items-center justify-between text-[11px] text-text-sub">
              <span>{Number(item.numerator).toFixed(item.denominator <= 1 ? 2 : 0)} / {Number(item.denominator).toFixed(item.denominator <= 1 ? 2 : 0)}</span>
              <span>{t("阈值", "Threshold")} {Math.round(item.threshold * 100)}%</span>
            </div>
          </div>
        ))}
      </div>
      {!items.length && <Empty text={t("暂无验收指标，先运行一次对局或进化周期。", "No acceptance metrics yet. Run a game or evolution cycle first.")} />}
    </div>
  );

  return (
    <Panel title={t("B/C 量化验收", "B/C Quantified Acceptance")}>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-button px-4 py-3" style={{ background: "rgba(255,255,255,0.04)" }}>
        <div>
          <p className="text-sm font-semibold text-textPrimary">
            {passed ? t("整体通过", "Overall passed") : t("整体未完全通过", "Overall not fully passed")}
          </p>
          <p className="text-xs text-text-sub">
            {t("每一步都按样本数计算成功率；空数据不会算作通过。", "Every step is rate-based; empty data never counts as pass.")}
          </p>
        </div>
        <div className="text-right">
          <p className={passed ? "text-3xl font-bold text-success" : "text-3xl font-bold text-danger"}>
            {Math.round(overallRate * 100)}%
          </p>
          <p className="text-xs text-text-sub">{t("平均成功率", "Average success")}</p>
        </div>
      </div>
      <div className="grid gap-5 xl:grid-cols-2">
        {renderTrack(trackB, "Track B")}
        {renderTrack(trackC, "Track C")}
      </div>
    </Panel>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-card border p-4" style={{ background: "var(--color-card)", borderColor: "var(--color-border)" }}>
      <h2 className="mb-3 text-sm font-semibold text-textPrimary">{title}</h2>
      {children}
    </section>
  );
}

function Row({ title, meta, value }: { title: string; meta?: string; value?: string }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-button px-3 py-2" style={{ background: "rgba(255,255,255,0.04)" }}>
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-textPrimary">{title}</p>
        {meta && <p className="truncate text-xs text-text-sub">{meta}</p>}
      </div>
      {value && <span className="shrink-0 text-xs text-primary">{value}</span>}
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return <p className="text-sm text-text-sub">{text}</p>;
}
