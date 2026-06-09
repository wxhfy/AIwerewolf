"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { demoReplay, DemoReplayPlayer, DemoReplayStep } from "@/lib/demoReplayData";

const roleLabels: Record<string, string> = {
  Hunter: "猎人",
  Villager: "村民",
  Guard: "守卫",
  Werewolf: "狼人",
  Witch: "女巫",
  Seer: "预言家",
};

const actionTone: Record<DemoReplayStep["kind"], string> = {
  talk: "border-sky-500/30 bg-sky-500/10 text-sky-950",
  vote: "border-amber-500/35 bg-amber-500/10 text-amber-950",
  attack: "border-red-500/35 bg-red-500/10 text-red-950",
  guard: "border-emerald-500/35 bg-emerald-500/10 text-emerald-950",
  witch_save: "border-teal-500/35 bg-teal-500/10 text-teal-950",
  witch_poison: "border-rose-500/35 bg-rose-500/10 text-rose-950",
  divine: "border-indigo-500/35 bg-indigo-500/10 text-indigo-950",
};

function formatNumber(value: number) {
  return new Intl.NumberFormat("zh-CN").format(value);
}

function playerLabel(player?: DemoReplayPlayer) {
  return player ? `${player.seat}号 ${player.name}` : "无目标";
}

export default function FixedReplayDemoPage() {
  const [stepIndex, setStepIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const playersById = useMemo(() => new Map(demoReplay.players.map((player) => [player.id, player])), []);
  const currentStep = demoReplay.steps[stepIndex];
  const actor = playersById.get(currentStep.actorId);
  const target = currentStep.targetId ? playersById.get(currentStep.targetId) : undefined;
  const timelineStart = Math.max(0, stepIndex - 7);
  const visibleSteps = demoReplay.steps.slice(timelineStart, stepIndex + 1);
  const progress = ((stepIndex + 1) / demoReplay.steps.length) * 100;

  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => {
      setStepIndex((index) => {
        if (index >= demoReplay.steps.length - 1) {
          setPlaying(false);
          return index;
        }
        return index + 1;
      });
    }, 1800);
    return () => window.clearInterval(timer);
  }, [playing]);

  function jumpTo(index: number) {
    setStepIndex(Math.max(0, Math.min(index, demoReplay.steps.length - 1)));
  }

  return (
    <main className="min-h-screen bg-[#f6f2ea] text-[#241c15]">
      <header className="border-b border-[#d8c7aa] bg-[#fffaf1]/95 px-5 py-3 backdrop-blur">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-[#8a6231]">Fixed Demo Replay</p>
            <h1 className="font-display text-2xl font-bold text-[#5f2a0b]">历史真实对局固定回放</h1>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="rounded-full border border-[#d8c7aa] px-3 py-1 text-[#6f5a43]">game_id: {demoReplay.source.gameId.slice(0, 8)}</span>
            <Link href="/" className="rounded-button border border-[#b98745] px-4 py-2 font-semibold text-[#5f2a0b] transition hover:bg-[#f2e4cb]">
              返回大厅
            </Link>
          </div>
        </div>
      </header>

      <div className="mx-auto grid max-w-[1600px] gap-4 px-5 py-5 xl:grid-cols-[320px_minmax(0,1fr)_360px]">
        <aside className="space-y-4">
          <section className="rounded-card border border-[#d8c7aa] bg-[#fffaf1] p-4 shadow-sm">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs text-[#80684d]">本局结果</p>
                <h2 className="mt-1 font-display text-2xl font-bold text-[#126033]">{demoReplay.result.winnerLabel}</h2>
              </div>
              <div className="rounded-full bg-[#126033] px-3 py-1 text-xs font-bold text-white">Day {demoReplay.result.totalDays}</div>
            </div>
            <div className="mt-4 grid grid-cols-2 gap-2 text-sm">
              <div className="border-t border-[#ead9bd] pt-3">
                <p className="text-xs text-[#80684d]">MVP</p>
                <p className="font-semibold">{demoReplay.result.mvp} · {roleLabels[demoReplay.result.mvpRole]}</p>
              </div>
              <div className="border-t border-[#ead9bd] pt-3">
                <p className="text-xs text-[#80684d]">Track B</p>
                <p className="font-semibold">{demoReplay.result.mvpScore.toFixed(1)}</p>
              </div>
              <div className="border-t border-[#ead9bd] pt-3">
                <p className="text-xs text-[#80684d]">固定决策</p>
                <p className="font-semibold">{demoReplay.metrics.decisions} 条</p>
              </div>
              <div className="border-t border-[#ead9bd] pt-3">
                <p className="text-xs text-[#80684d]">策略检索</p>
                <p className="font-semibold">{demoReplay.metrics.retrievalHits}/{demoReplay.metrics.decisions}</p>
              </div>
            </div>
          </section>

          <section className="rounded-card border border-[#d8c7aa] bg-[#fffaf1] p-4 shadow-sm">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="font-display text-lg font-bold text-[#5f2a0b]">席位与身份</h2>
              <span className="text-xs text-[#80684d]">全局演示视角</span>
            </div>
            <div className="space-y-2">
              {demoReplay.players.map((player) => (
                <div key={player.id} className="grid grid-cols-[2.2rem_minmax(0,1fr)_4.4rem] items-center gap-2 rounded-lg border border-[#ead9bd] bg-white/55 px-3 py-2">
                  <div className={`flex h-8 w-8 items-center justify-center rounded-full text-sm font-bold ${player.camp === "wolf" ? "bg-[#8d1d16] text-white" : "bg-[#176d37] text-white"}`}>
                    {player.seat}
                  </div>
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold">{player.name}</p>
                    <p className="truncate text-[11px] text-[#80684d]">{player.mbti} · {player.style}</p>
                  </div>
                  <div className="text-right text-xs">
                    <p className="font-semibold">{roleLabels[player.role]}</p>
                    <p className={player.aliveAtEnd ? "text-[#176d37]" : "text-[#8d1d16]"}>{player.aliveAtEnd ? "存活" : "出局"}</p>
                  </div>
                </div>
              ))}
            </div>
          </section>
        </aside>

        <section className="min-w-0 space-y-4">
          <section className="rounded-card border border-[#d8c7aa] bg-[#fffaf1] p-4 shadow-sm">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[#8a6231]">Current Frame</p>
                <h2 className="mt-1 font-display text-xl font-bold text-[#5f2a0b]">第 {currentStep.day} 天 · {currentStep.phaseLabel}</h2>
              </div>
              <div className="flex items-center gap-2">
                <button type="button" onClick={() => jumpTo(stepIndex - 1)} className="h-10 rounded-button border border-[#d8c7aa] px-4 text-sm font-semibold text-[#5f2a0b] transition hover:bg-[#f2e4cb]">上一句</button>
                <button type="button" onClick={() => setPlaying((value) => !value)} className="h-10 rounded-button bg-[#6f3510] px-5 text-sm font-semibold text-white transition hover:bg-[#854714]">
                  {playing ? "暂停" : "播放"}
                </button>
                <button type="button" onClick={() => jumpTo(stepIndex + 1)} className="h-10 rounded-button border border-[#d8c7aa] px-4 text-sm font-semibold text-[#5f2a0b] transition hover:bg-[#f2e4cb]">下一句</button>
              </div>
            </div>

            <div className="h-2 overflow-hidden rounded-full bg-[#ead9bd]">
              <div className="h-full rounded-full bg-[#8a4b18] transition-all duration-300" style={{ width: `${progress}%` }} />
            </div>

            <div className="mt-5 grid gap-4 lg:grid-cols-[minmax(0,1fr)_220px]">
              <div className={`rounded-card border p-5 ${actionTone[currentStep.kind]}`}>
                <div className="mb-4 flex flex-wrap items-center gap-2">
                  <span className="rounded-full bg-white/70 px-3 py-1 text-xs font-bold">{currentStep.kindLabel}</span>
                  <span className="text-xs font-semibold">{stepIndex + 1} / {demoReplay.steps.length}</span>
                  {currentStep.retrievalUsed && <span className="rounded-full bg-[#176d37] px-3 py-1 text-xs font-bold text-white">Track C 策略命中</span>}
                </div>
                <div className="mb-4 flex items-center gap-3">
                  <div className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-full text-base font-bold text-white ${actor?.camp === "wolf" ? "bg-[#8d1d16]" : "bg-[#176d37]"}`}>
                    {actor?.seat}
                  </div>
                  <div>
                    <p className="font-display text-2xl font-bold">{playerLabel(actor)}</p>
                    <p className="text-sm opacity-75">{actor ? roleLabels[actor.role] : ""}{target ? ` → ${playerLabel(target)}` : ""}</p>
                  </div>
                </div>
                <p className="whitespace-pre-line text-lg leading-relaxed">{currentStep.text}</p>
              </div>

              <div className="rounded-card border border-[#ead9bd] bg-white/65 p-4">
                <p className="text-xs text-[#80684d]">本句运行证据</p>
                <dl className="mt-3 space-y-3 text-sm">
                  <div>
                    <dt className="text-[#80684d]">模型</dt>
                    <dd className="font-semibold">Doubao v4 Flash</dd>
                  </div>
                  <div>
                    <dt className="text-[#80684d]">Token</dt>
                    <dd className="font-semibold">{formatNumber(currentStep.tokenTotal)}</dd>
                  </div>
                  <div>
                    <dt className="text-[#80684d]">耗时</dt>
                    <dd className="font-semibold">{(currentStep.latencyMs / 1000).toFixed(1)}s</dd>
                  </div>
                  <div>
                    <dt className="text-[#80684d]">目标</dt>
                    <dd className="font-semibold">{target ? playerLabel(target) : "无"}</dd>
                  </div>
                </dl>
              </div>
            </div>
          </section>

          <section className="rounded-card border border-[#d8c7aa] bg-[#fffaf1] p-4 shadow-sm">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <h2 className="font-display text-lg font-bold text-[#5f2a0b]">固定时间线</h2>
              <div className="flex flex-wrap gap-2">
                {demoReplay.chapters.map((chapter) => (
                  <button key={chapter.label} type="button" onClick={() => jumpTo(chapter.stepIndex)} className="rounded-full border border-[#d8c7aa] px-3 py-1 text-xs font-semibold text-[#6f5a43] transition hover:bg-[#f2e4cb]">
                    {chapter.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="timeline-scroll max-h-[34rem] space-y-2 overflow-y-auto pr-1">
              {visibleSteps.map((step, localIndex) => {
                const index = timelineStart + localIndex;
                const stepActor = playersById.get(step.actorId);
                const stepTarget = step.targetId ? playersById.get(step.targetId) : undefined;
                const selected = index === stepIndex;
                return (
                  <button
                    key={step.id}
                    type="button"
                    onClick={() => jumpTo(index)}
                    className={`w-full rounded-lg border px-3 py-2 text-left transition ${selected ? "border-[#8a4b18] bg-[#f3e0bf]" : "border-[#ead9bd] bg-white/55 hover:bg-[#f8eddc]"}`}
                  >
                    <div className="flex flex-wrap items-center gap-2 text-xs text-[#80684d]">
                      <span className="font-bold text-[#5f2a0b]">{String(index + 1).padStart(2, "0")}</span>
                      <span>第 {step.day} 天</span>
                      <span>{step.phaseLabel}</span>
                      <span>{step.kindLabel}</span>
                      {step.retrievalUsed && <span className="rounded-full bg-[#dff1e5] px-2 py-0.5 text-[#176d37]">C</span>}
                    </div>
                    <p className="mt-1 truncate text-sm font-semibold text-[#241c15]">
                      {playerLabel(stepActor)}{stepTarget ? ` → ${playerLabel(stepTarget)}` : ""}: {step.text.replace(/\n+/g, " ")}
                    </p>
                  </button>
                );
              })}
            </div>
          </section>
        </section>

        <aside className="space-y-4">
          <section className="rounded-card border border-[#d8c7aa] bg-[#fffaf1] p-4 shadow-sm">
            <h2 className="font-display text-lg font-bold text-[#5f2a0b]">Track B / C 摘要</h2>
            <div className="mt-4 grid gap-3">
              <div className="rounded-lg border border-[#ead9bd] bg-white/60 p-3">
                <p className="text-xs text-[#80684d]">策略检索覆盖</p>
                <p className="mt-1 text-2xl font-bold text-[#176d37]">{Math.round(demoReplay.metrics.retrievalRate * 100)}%</p>
              </div>
              <div className="rounded-lg border border-[#ead9bd] bg-white/60 p-3">
                <p className="text-xs text-[#80684d]">总 Token</p>
                <p className="mt-1 text-2xl font-bold text-[#5f2a0b]">{formatNumber(demoReplay.metrics.totalTokens)}</p>
              </div>
              <div className="rounded-lg border border-[#ead9bd] bg-white/60 p-3">
                <p className="text-xs text-[#80684d]">平均决策耗时</p>
                <p className="mt-1 text-2xl font-bold text-[#5f2a0b]">{(demoReplay.metrics.avgLatencyMs / 1000).toFixed(1)}s</p>
              </div>
            </div>
            <div className="mt-4 space-y-2">
              {demoReplay.evidence.map((item) => (
                <p key={item} className="rounded-lg bg-[#f8eddc] px-3 py-2 text-sm leading-relaxed text-[#5f4630]">{item}</p>
              ))}
            </div>
          </section>

          <section className="rounded-card border border-[#d8c7aa] bg-[#fffaf1] p-4 shadow-sm">
            <h2 className="font-display text-lg font-bold text-[#5f2a0b]">关键转折</h2>
            <div className="mt-3 space-y-3">
              {demoReplay.chapters.map((chapter) => (
                <button key={chapter.label} type="button" onClick={() => jumpTo(chapter.stepIndex)} className="block w-full rounded-lg border border-[#ead9bd] bg-white/55 px-3 py-3 text-left transition hover:border-[#b98745] hover:bg-[#f8eddc]">
                  <p className="font-semibold text-[#5f2a0b]">{chapter.label}</p>
                  <p className="mt-1 text-sm leading-relaxed text-[#6f5a43]">{chapter.note}</p>
                </button>
              ))}
            </div>
          </section>

          <section className="rounded-card border border-[#d8c7aa] bg-[#fffaf1] p-4 shadow-sm">
            <h2 className="font-display text-lg font-bold text-[#5f2a0b]">玩家评分</h2>
            <div className="mt-3 space-y-2">
              {[...demoReplay.players].sort((a, b) => b.finalScore - a.finalScore).map((player) => (
                <div key={player.id} className="grid grid-cols-[minmax(0,1fr)_4rem] items-center gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold">{player.seat}号 {player.name} · {roleLabels[player.role]}</p>
                    <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-[#ead9bd]">
                      <div className={player.camp === "wolf" ? "h-full rounded-full bg-[#8d1d16]" : "h-full rounded-full bg-[#176d37]"} style={{ width: `${Math.min(100, player.processScore)}%` }} />
                    </div>
                  </div>
                  <p className="text-right text-sm font-bold">{player.finalScore.toFixed(1)}</p>
                </div>
              ))}
            </div>
          </section>
        </aside>
      </div>
    </main>
  );
}
