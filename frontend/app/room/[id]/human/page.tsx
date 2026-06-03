"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useParams } from "next/navigation";
import { t, tRole } from "@/lib/i18n";
import { ActionPanel } from "@/components/game/ActionPanel";
import { BadgePanel } from "@/components/game/BadgePanel";
import { EventTimeline } from "@/components/game/EventTimeline";
import { GameEndPanel } from "@/components/game/GameEndPanel";
import { GameHeader } from "@/components/game/GameHeader";
import { MobilePlayerRail, PlayerRail } from "@/components/game/PlayerRail";
import { PhaseOverlayCoordinator } from "@/components/game/PhaseOverlayCoordinator";
import { DayNightBlinkTransition } from "@/components/game/DayNightBlinkTransition";
import { ThinkingBubble } from "@/components/game/ThinkingBubble";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";
import { Button } from "@/components/ui/Button";
import { useGamePageController } from "@/hooks/useGamePageController";
import { useHumanDisplayState } from "@/hooks/useHumanDisplayState";

// ── Same StatusBar as AI page ─────────────────────────────────────
function StatusBar({ statusTitle, display, lang, displayPhase }: {
  statusTitle: string; display: any; lang: any; displayPhase?: string;
}) {
  const PHASE_LABEL: Record<string, string> = {
    SETUP: "准备阶段", NIGHT_START: "夜幕降临", NIGHT_GUARD_ACTION: "守卫行动",
    NIGHT_WOLF_ACTION: "狼人行动", NIGHT_WITCH_ACTION: "女巫行动", NIGHT_SEER_ACTION: "预言家行动",
    NIGHT_RESOLVE: "夜晚结算", DAY_START: "天亮了", DAY_BADGE_SIGNUP: "警徽报名",
    DAY_BADGE_SPEECH: "警徽竞选发言", DAY_BADGE_ELECTION: "警徽投票",
    DAY_PK_SPEECH: "PK 发言", DAY_SPEECH: "自由发言", DAY_VOTE: "投票放逐",
    DAY_LAST_WORDS: "遗言", DAY_RESOLVE: "白天结算", HUNTER_SHOOT: "猎人开枪",
    BADGE_TRANSFER: "警徽移交", GAME_END: "游戏结束",
  };
  // Use displayPhase (typewriter-driven) NOT raw gameState.phase
  const visiblePhase = displayPhase || display.phase;
  const phaseLabel = PHASE_LABEL[visiblePhase] || visiblePhase;

  return (
    <div className="flex items-center gap-3 border-b border-border bg-cardBackground px-5 py-2.5 text-base font-medium">
      <span className="font-semibold text-textPrimary">{display.cycle} · {phaseLabel}</span>
      {display.currentActor && (
        <span className="text-text-sub">
          · <span className="text-primary font-medium">{display.currentActor.seat}号 {display.currentActor.name} {
            display.currentActor.name === display.myName
              ? (display.canAct ? (lang === "zh" ? "轮到你了" : "Your turn") : "")
              : (lang === "zh" ? "行动中" : "acting")
          }</span>
        </span>
      )}
      <span className="text-text-sub/60 ml-auto text-sm">
        {t("aliveCount", lang)}: {display.aliveCount}/{display.totalCount}
      </span>
    </div>
  );
}

export default function HumanGamePage() {
  const params = useParams<{ id: string }>();
  const ctrl = useGamePageController(params.id);
  const { gameState: gs, derived, phase } = ctrl;
  const human = gs?.players?.find((p: any) => p.seat === ctrl.humanSeat);
  const display = useHumanDisplayState(gs, human, ctrl.viewMode);
  const language = ctrl.language;

  const isEndPhase = phase.visualPhaseGroup === "end" || display.isOver;
  const showNight = phase.isVisualNight && !isEndPhase;

  // ── Target selection via PlayerCards ───────────────────────────
  const [selectedTarget, setSelectedTarget] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [speech, setSpeech] = useState("");
  const pending = (gs as any)?.pending_input;
  const needsTarget = !!(pending && (pending.action_type === "vote" || pending.action_type === "night_action" || pending.action_type === "special"));
  const isSpeech = pending?.action_type === "speech";

  useEffect(() => { setSelectedTarget(""); setSubmitted(false); setSpeech(""); }, [pending?.player_id, pending?.request]);

  function submitAction() {
    if (submitted) return;
    setSubmitted(true);
    ctrl.handleHumanAction({ target_id: needsTarget ? (selectedTarget || null) : null, speech: isSpeech ? (speech.trim() || null) : null, save: false });
  }

  const targetPlayer = gs?.players?.find((p: any) => p.id === selectedTarget);
  const canSubmit = !needsTarget || !!selectedTarget;

  // ── Typewriter queue (same as AI page) ─────────────────────────
  const completedRef = useRef<Set<string>>(new Set());
  const [, ct] = useState(0);
  const onComplete = useCallback((id: string) => { completedRef.current.add(id); ct(n => n + 1); }, []);

  // ── Role reveal ────────────────────────────────────────────────
  const [revealDone, setRevealDone] = useState(false);
  useEffect(() => { if (display.isMyTurn && !revealDone) { const t = setTimeout(() => setRevealDone(true), 3000); return () => clearTimeout(t); } }, [display.isMyTurn, revealDone]);

  return (
    <ErrorBoundary>
    <div className="h-screen [height:100dvh] flex flex-col overflow-hidden bg-background night-stars" data-phase={phase.visualPhaseGroup} data-phase-aware>
      {/* ── 昼夜眨眼转场（z-index 1500，覆盖一切） ── */}
      <DayNightBlinkTransition
        blinkPhase={ctrl.blinkPhase}
        onCloseComplete={ctrl.onBlinkCloseComplete}
        onPauseComplete={ctrl.onBlinkPauseComplete}
        onOpenComplete={ctrl.onBlinkOpenComplete}
      />
      <PhaseOverlayCoordinator phaseAnnouncement={phase.phaseAnnouncement} />
      {ctrl.fetchError && (
        <div className="fixed inset-x-0 top-16 z-[1100] mx-auto max-w-md rounded-card border border-danger/30 bg-cardBackground/95 p-4 shadow-lg backdrop-blur">
          <p className="text-sm text-danger mb-3">{ctrl.fetchError}</p>
          <div className="flex gap-2"><button onClick={ctrl.retryRoom} className="rounded-button bg-primary px-4 py-1.5 text-xs font-medium text-white">{t("retry", ctrl.language)}</button><button onClick={() => ctrl.router.push("/")} className="rounded-button border border-border px-4 py-1.5 text-xs font-medium text-text-sub">{t("backToLobby", ctrl.language)}</button></div>
        </div>
      )}
      {showNight && <div className="fixed inset-0 pointer-events-none z-0 bg-night-overlay transition-opacity duration-500" />}

      <GameHeader roomId={ctrl.roomId} day={gs?.day} winner={gs?.winner} language={ctrl.language} viewMode={ctrl.viewMode} isVisualNight={phase.isVisualNight} isHumanMode={true} canRun={false} onRun={ctrl.runGame} onStartHuman={ctrl.startHumanGame} onViewModeChange={ctrl.setViewMode} onLanguageChange={ctrl.setLanguage} />

      <MobilePlayerRail players={gs?.players || []} fallbackPlayers={ctrl.placeholder(1, gs?.players?.length || 7)}
        pendingPlayerId={derived.pendingInput?.player_id} activeSpeakerId={derived.activeSpeakerId} sheriffId={derived.sheriffId} badgeCandidateSet={derived.badgeCandidateSet}
        isHumanMode={true} humanSeat={ctrl.humanSeat} wolfTeammates={display.wolfTeammates}
        spokenInPhase={derived.spokenInPhase} votedSet={derived.votedSet} voteCount={derived.voteCount} voteTarget={derived.voteTarget} />

      <div className="relative z-10 flex flex-1 overflow-hidden">
        <PlayerRail side="left" players={derived.leftPlayers} fallbackPlayers={ctrl.placeholder(1, Math.ceil((gs?.players?.length || 7) / 2))}
          pendingPlayerId={derived.pendingInput?.player_id} activeSpeakerId={derived.activeSpeakerId} sheriffId={derived.sheriffId} badgeCandidateSet={derived.badgeCandidateSet}
          isHumanMode={true} humanSeat={ctrl.humanSeat} wolfTeammates={display.wolfTeammates}
          spokenInPhase={derived.spokenInPhase} votedSet={derived.votedSet} voteCount={derived.voteCount} voteTarget={derived.voteTarget}
          selectable={needsTarget && !submitted} selectedTargetId={selectedTarget} onSelectTarget={setSelectedTarget} />

        {/* ── Center: EXACT same structure as AI page ──────────── */}
        <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
          <StatusBar statusTitle={ctrl.statusTitle} display={display} lang={ctrl.language} displayPhase={ctrl.displayPhase} />
          {gs && (
            <BadgePanel gameState={gs} language={ctrl.language} activeSpeakerId={derived.activeSpeakerId} displayPhase={ctrl.displayPhase} completedIds={completedRef.current} />
          )}
          <div className="flex-1 overflow-y-auto px-4 py-3 timeline-scroll">
            {gs?.events?.length ? (
              <>
                <EventTimeline dayBlocks={derived.dayBlocks} language={ctrl.language} viewMode={ctrl.viewMode} isHumanMode={true} humanSeat={ctrl.humanSeat} completedIds={completedRef.current} onChatComplete={onComplete} hideDayHeaders />
                {/* AI 玩家正在组织发言 → 显示思考气泡（跳过真人自己） */}
                {(() => {
                  const pi = (gs as any)?.pending_input;
                  if (!pi || pi.action_type !== "speech") return null;
                  // 真人玩家自己有操作栏，不需要思考气泡
                  if (pi.seat === ctrl.humanSeat) return null;
                  return (
                    <ThinkingBubble
                      playerName={pi.player_name}
                      playerSeat={pi.seat}
                      language={ctrl.language}
                    />
                  );
                })()}
              </>
            ) : (
              <div className="flex h-full flex-col items-center justify-center py-20 text-center">
                <div className="mb-5 h-10 w-10 animate-spin rounded-full border-2 border-primary/30 border-t-primary" />
                <p className="mb-2 font-display text-lg text-textPrimary">{t("statusStreaming", ctrl.language)}</p>
                <p className="text-sm text-text-sub">{t("statusHint", ctrl.language)}</p>
              </div>
            )}
          </div>

          {/* ── Human action bar (the only addition vs AI page) ── */}
          {display.isMyTurn && revealDone && display.canAct && !submitted && !ctrl.isBlinking && (
            <div className="border-t border-border bg-cardBackground px-4 py-2">
              {isSpeech ? (
                <div className="flex items-end gap-2">
                  <textarea value={speech} onChange={(e) => setSpeech(e.target.value)} placeholder={pending?.placeholder || "输入发言..."}
                    className="flex-1 h-20 resize-none rounded-lg border border-border bg-background px-3 py-3 text-sm text-textPrimary" />
                  <Button onClick={submitAction} size="sm">{pending?.request === "BADGE_SPEECH" ? "提交竞选发言" : pending?.request === "LAST_WORDS" ? "结束遗言" : "发送"}</Button>
                  {pending?.request === "BADGE_SPEECH" && <button onClick={() => { setSpeech(""); submitAction(); }} className="text-[11px] text-text-sub/60 hover:text-text-sub shrink-0">不竞选</button>}
                </div>
              ) : (
                <div className="flex items-center justify-between">
                  <span className="text-xs text-text-sub truncate">{pending?.prompt || (needsTarget ? (language === "zh" ? "点击玩家卡片投票 / 轮到你了" : "Tap player cards to vote / Your turn") : "")}</span>
                  <div className="flex items-center gap-2 shrink-0">
                    {targetPlayer && (
                      <>
                        <span className="text-xs text-primary font-medium">{language === "zh" ? "你选择投票给" : "Voting for"} {targetPlayer.seat}号 {targetPlayer.name}</span>
                        <button onClick={() => setSelectedTarget("")} className="text-[11px] text-text-sub/60 hover:text-text-sub">{language === "zh" ? "取消" : "Cancel"}</button>
                      </>
                    )}
                    <Button onClick={submitAction} disabled={!canSubmit} size="sm">{pending?.request === "DIVINE" ? "确认查验" : pending?.request === "ATTACK" ? "确认击杀" : pending?.request === "GUARD" ? "确认守护" : pending?.request === "WITCH" ? "确认用药" : pending?.request === "SHOOT" ? "确认开枪" : pending?.action_type === "vote" ? "确认投票" : "确认"}</Button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Submitted state */}
          {submitted && (
            <div className="border-t border-border bg-cardBackground px-4 py-2 flex items-center gap-2 text-xs text-text-sub">
              <span className="h-3 w-3 animate-spin rounded-full border-2 border-primary/30 border-t-primary" />
              已提交，等待阶段推进
            </div>
          )}
        </main>

        <PlayerRail side="right" players={derived.rightPlayers} fallbackPlayers={ctrl.placeholder(derived.splitPoint + 1, gs?.players?.length || 7)}
          pendingPlayerId={derived.pendingInput?.player_id} activeSpeakerId={derived.activeSpeakerId} sheriffId={derived.sheriffId} badgeCandidateSet={derived.badgeCandidateSet}
          isHumanMode={true} humanSeat={ctrl.humanSeat} wolfTeammates={display.wolfTeammates}
          spokenInPhase={derived.spokenInPhase} votedSet={derived.votedSet} voteCount={derived.voteCount} voteTarget={derived.voteTarget}
          selectable={needsTarget && !submitted} selectedTargetId={selectedTarget} onSelectTarget={setSelectedTarget} />
      </div>

      {/* Role reveal */}
      {display.isMyTurn && !revealDone && human && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/80 backdrop-blur-sm">
          <div className="text-center animate-scale-in">
            <p className="text-5xl mb-4">{display.myAlignment === "wolf" ? "🐺" : "🏘️"}</p>
            <p className={`text-3xl font-bold ${display.myAlignment === "wolf" ? "text-danger" : "text-success"}`}>{tRole(human.role as any, ctrl.language)}</p>
            <p className="text-sm text-text-sub mt-1">{display.mySeat}号 {display.myName}</p>
            {display.wolfTeammates.length > 0 && <p className="text-xs text-danger/70 mt-2">狼队友：{display.wolfTeammates.join(" · ")}</p>}
            <p className="text-[10px] text-text-sub/30 mt-4 animate-pulse">即将进入游戏...</p>
          </div>
        </div>
      )}

      {gs?.winner && <GameEndPanel winner={gs.winner} day={gs.day} aliveCount={display.aliveCount} eventCount={gs.event_count || 0} language={ctrl.language} showPanel={ctrl.showWinnerPanel} ballPos={ctrl.ballPos} dragRef={ctrl.dragRef} onOpen={() => ctrl.setShowWinnerPanel(true)} onClose={() => ctrl.setShowWinnerPanel(false)} onBallMove={ctrl.setBallPos} onLobby={() => ctrl.router.push("/")} onReport={gs.id ? () => ctrl.router.push(`/games/${gs.id}/report`) : undefined} />}
    </div>
    </ErrorBoundary>
  );
}
