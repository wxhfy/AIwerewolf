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

type ReplayViewMode = "audience" | "global";

const privateActionKinds = new Set<DemoReplayStep["kind"]>([
  "attack",
  "guard",
  "witch_save",
  "witch_poison",
  "divine",
]);

const publicChapterCopy: Record<string, { label: string; note: string }> = {
  首夜查杀: { label: "首日主线形成", note: "首日公开发言中出现核心怀疑方向，带动后续归票。" },
  警徽竞选: { label: "警徽竞选", note: "多名玩家参与警徽争夺，公开发言形成第一轮站边线索。" },
  第一天放逐: { label: "第一天放逐", note: "多名玩家依据发言和票型完成第一轮公开放逐。" },
  第二天误推出守卫: { label: "第二天放逐", note: "公开票型解释冲突扩大，白天放逐后留下下一轮讨论线索。" },
  女巫终局毒杀: { label: "终局公开结算", note: "最后一夜后对局进入收束，公开结果确认好人阵营胜利。" },
};

function formatNumber(value: number) {
  return new Intl.NumberFormat("zh-CN").format(value);
}

function playerLabel(player?: DemoReplayPlayer) {
  return player ? `${player.seat}号 ${player.name}` : "无目标";
}

function isPrivateStep(step: DemoReplayStep) {
  return step.phaseLabel.includes("夜晚") || privateActionKinds.has(step.kind);
}

function displayPhaseLabel(step: DemoReplayStep, viewMode: ReplayViewMode) {
  return viewMode === "audience" && isPrivateStep(step) ? "夜晚阶段" : step.phaseLabel;
}

function displayKindLabel(step: DemoReplayStep, viewMode: ReplayViewMode) {
  return viewMode === "audience" && isPrivateStep(step) ? "夜间结算" : step.kindLabel;
}

function displayStepText(step: DemoReplayStep, viewMode: ReplayViewMode) {
  if (viewMode === "global" || !isPrivateStep(step)) return step.text;
  return "夜间行动已按观众视角折叠。公开回放仅展示阶段推进，不暴露角色技能、阵营身份和具体目标。";
}

function displayRole(player: DemoReplayPlayer | undefined, viewMode: ReplayViewMode) {
  if (!player) return "";
  return viewMode === "global" ? roleLabels[player.role] : "身份未公开";
}

function displayTargetLabel(step: DemoReplayStep, target: DemoReplayPlayer | undefined, viewMode: ReplayViewMode) {
  if (viewMode === "audience" && isPrivateStep(step)) return "观众视角不可见";
  return target ? playerLabel(target) : "无目标";
}

function displayActorLabel(step: DemoReplayStep, actor: DemoReplayPlayer | undefined, viewMode: ReplayViewMode) {
  if (viewMode === "audience" && isPrivateStep(step)) return "夜间系统结算";
  return playerLabel(actor);
}

function displayActorRole(step: DemoReplayStep, actor: DemoReplayPlayer | undefined, viewMode: ReplayViewMode) {
  if (viewMode === "audience" && isPrivateStep(step)) return "公开信息折叠";
  return displayRole(actor, viewMode);
}

function playerTone(player: DemoReplayPlayer | undefined, viewMode: ReplayViewMode) {
  if (viewMode === "audience") return "bg-[#6f5a43] text-white";
  return player?.camp === "wolf" ? "bg-[#8d1d16] text-white" : "bg-[#176d37] text-white";
}

export default function FixedReplayDemoPage() {
  const [stepIndex, setStepIndex] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [replayViewMode, setReplayViewMode] = useState<ReplayViewMode>("audience");
  const playersById = useMemo(() => new Map(demoReplay.players.map((player) => [player.id, player])), []);
  const currentStep = demoReplay.steps[stepIndex];
  const actor = playersById.get(currentStep.actorId);
  const target = currentStep.targetId ? playersById.get(currentStep.targetId) : undefined;
  const timelineStart = Math.max(0, stepIndex - 7);
  const visibleSteps = demoReplay.steps.slice(timelineStart, stepIndex + 1);
  const progress = ((stepIndex + 1) / demoReplay.steps.length) * 100;
  const isGlobalView = replayViewMode === "global";
  const currentIsPrivate = isPrivateStep(currentStep);
  const currentActionTone = replayViewMode === "audience" && currentIsPrivate
    ? "border-stone-500/25 bg-stone-500/10 text-stone-950"
    : actionTone[currentStep.kind];
  const evidenceItems = isGlobalView ? demoReplay.evidence : [
    "观众视角仅展示公开发言、投票、遗言和阶段推进。",
    "夜间技能、阵营身份和目标信息在历史回放中保持折叠。",
    "切换到全局视角可查看完整身份、目标与 Track B/C 分析证据。",
  ];

  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => {
      setStepIndex((index) => {
        if (index >= demoReplay.steps.length - 1) return 0;
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
            <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-[#8a6231]">Historical Replay</p>
            <h1 className="font-display text-2xl font-bold text-[#5f2a0b]">历史对局回放</h1>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <div className="flex rounded-full border border-[#d8c7aa] bg-white/60 p-1 text-xs font-semibold" aria-label="回放视角">
              <button
                type="button"
                onClick={() => setReplayViewMode("audience")}
                className={`rounded-full px-3 py-1.5 transition ${replayViewMode === "audience" ? "bg-[#6f3510] text-white shadow-sm" : "text-[#6f5a43] hover:bg-[#f2e4cb]"}`}
              >
                观众视角
              </button>
              <button
                type="button"
                onClick={() => setReplayViewMode("global")}
                className={`rounded-full px-3 py-1.5 transition ${replayViewMode === "global" ? "bg-[#6f3510] text-white shadow-sm" : "text-[#6f5a43] hover:bg-[#f2e4cb]"}`}
              >
                全局视角
              </button>
            </div>
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
                <p className="font-semibold">{demoReplay.result.mvp} · {isGlobalView ? roleLabels[demoReplay.result.mvpRole] : "公开表现"}</p>
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
              <h2 className="font-display text-lg font-bold text-[#5f2a0b]">{isGlobalView ? "席位与身份" : "席位信息"}</h2>
              <span className="text-xs text-[#80684d]">{isGlobalView ? "全局视角" : "观众视角"}</span>
            </div>
            <div className="space-y-2">
              {demoReplay.players.map((player) => (
                <div key={player.id} className="grid grid-cols-[2.2rem_minmax(0,1fr)_4.4rem] items-center gap-2 rounded-lg border border-[#ead9bd] bg-white/55 px-3 py-2">
                  <div className={`flex h-8 w-8 items-center justify-center rounded-full text-sm font-bold ${playerTone(player, replayViewMode)}`}>
                    {player.seat}
                  </div>
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold">{player.name}</p>
                    <p className="truncate text-[11px] text-[#80684d]">{player.mbti} · {player.style}</p>
                  </div>
                  <div className="text-right text-xs">
                    <p className="font-semibold">{displayRole(player, replayViewMode)}</p>
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
                <h2 className="mt-1 font-display text-xl font-bold text-[#5f2a0b]">第 {currentStep.day} 天 · {displayPhaseLabel(currentStep, replayViewMode)}</h2>
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
              <div className={`rounded-card border p-5 ${currentActionTone}`}>
                <div className="mb-4 flex flex-wrap items-center gap-2">
                  <span className="rounded-full bg-white/70 px-3 py-1 text-xs font-bold">{displayKindLabel(currentStep, replayViewMode)}</span>
                  <span className="text-xs font-semibold">{stepIndex + 1} / {demoReplay.steps.length}</span>
                  {currentStep.retrievalUsed && isGlobalView && <span className="rounded-full bg-[#176d37] px-3 py-1 text-xs font-bold text-white">Track C 策略命中</span>}
                  {!isGlobalView && currentIsPrivate && <span className="rounded-full bg-[#6f5a43] px-3 py-1 text-xs font-bold text-white">公开折叠</span>}
                </div>
                <div className="mb-4 flex items-center gap-3">
                  <div className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-full text-base font-bold ${playerTone(actor, replayViewMode)}`}>
                    {!isGlobalView && currentIsPrivate ? "夜" : actor?.seat}
                  </div>
                  <div>
                    <p className="font-display text-2xl font-bold">{displayActorLabel(currentStep, actor, replayViewMode)}</p>
                    <p className="text-sm opacity-75">{displayActorRole(currentStep, actor, replayViewMode)}{target || (currentIsPrivate && !isGlobalView) ? ` → ${displayTargetLabel(currentStep, target, replayViewMode)}` : ""}</p>
                  </div>
                </div>
                <p className="whitespace-pre-line text-lg leading-relaxed">{displayStepText(currentStep, replayViewMode)}</p>
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
                    <dd className="font-semibold">{displayTargetLabel(currentStep, target, replayViewMode)}</dd>
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
                      <span>{displayPhaseLabel(step, replayViewMode)}</span>
                      <span>{displayKindLabel(step, replayViewMode)}</span>
                      {step.retrievalUsed && isGlobalView && <span className="rounded-full bg-[#dff1e5] px-2 py-0.5 text-[#176d37]">C</span>}
                      {!isGlobalView && isPrivateStep(step) && <span className="rounded-full bg-[#eee6d8] px-2 py-0.5 text-[#6f5a43]">折叠</span>}
                    </div>
                    <p className="mt-1 truncate text-sm font-semibold text-[#241c15]">
                      {displayActorLabel(step, stepActor, replayViewMode)}{stepTarget || (!isGlobalView && isPrivateStep(step)) ? ` → ${displayTargetLabel(step, stepTarget, replayViewMode)}` : ""}: {displayStepText(step, replayViewMode).replace(/\n+/g, " ")}
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
              {evidenceItems.map((item) => (
                <p key={item} className="rounded-lg bg-[#f8eddc] px-3 py-2 text-sm leading-relaxed text-[#5f4630]">{item}</p>
              ))}
            </div>
          </section>

          <section className="rounded-card border border-[#d8c7aa] bg-[#fffaf1] p-4 shadow-sm">
            <h2 className="font-display text-lg font-bold text-[#5f2a0b]">关键转折</h2>
            <div className="mt-3 space-y-3">
              {demoReplay.chapters.map((chapter) => (
                <button key={chapter.label} type="button" onClick={() => jumpTo(chapter.stepIndex)} className="block w-full rounded-lg border border-[#ead9bd] bg-white/55 px-3 py-3 text-left transition hover:border-[#b98745] hover:bg-[#f8eddc]">
                  <p className="font-semibold text-[#5f2a0b]">{isGlobalView ? chapter.label : publicChapterCopy[chapter.label]?.label ?? chapter.label}</p>
                  <p className="mt-1 text-sm leading-relaxed text-[#6f5a43]">{isGlobalView ? chapter.note : publicChapterCopy[chapter.label]?.note ?? chapter.note}</p>
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
                    <p className="truncate text-sm font-semibold">{player.seat}号 {player.name} · {displayRole(player, replayViewMode)}</p>
                    <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-[#ead9bd]">
                      <div className={isGlobalView ? (player.camp === "wolf" ? "h-full rounded-full bg-[#8d1d16]" : "h-full rounded-full bg-[#176d37]") : "h-full rounded-full bg-[#8a6231]"} style={{ width: `${Math.min(100, player.processScore)}%` }} />
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
