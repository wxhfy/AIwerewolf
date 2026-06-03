"use client";

import { useParams } from "next/navigation";
import { t, tPhase } from "@/lib/i18n";
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
import { useGamePageController } from "@/hooks/useGamePageController";
import { GameState, Language } from "@/types";

function StatusBar({ statusTitle, displayPhase, gameState, derived, language }: {
  statusTitle: string;
  displayPhase?: string;
  gameState: GameState | null;
  derived: ReturnType<typeof import("@/hooks/useGameDerivedState").useGameDerivedState>;
  language: Language;
}) {
  const activeSpeaker = gameState?.players?.find(p => p.id === derived.activeSpeakerId && p.alive);
  const activeName = activeSpeaker?.name;
  const activeSeat = activeSpeaker?.seat;
  const badgeCandidates = new Set(gameState?.badge?.candidates || []);

  const phaseText = displayPhase ? tPhase(displayPhase, language) : "";

  function getActionHint(): string {
    if (!activeSpeaker || !activeName) return "";
    const p = displayPhase || "";
    if (p.includes("BADGE_SPEECH")) {
      return badgeCandidates.has(activeSpeaker.id) ? `正在竞选发言` : `正在发言`;
    }
    if (p.includes("BADGE_ELECTION")) return `正在进行警徽投票`;
    if (p.includes("PK_SPEECH")) return `正在进行 PK 发言`;
    if (p.includes("_VOTE") && (gameState?.pk_targets?.length ?? 0) > 0) return `正在进行 PK 投票`;
    if (p.includes("_VOTE")) return `正在思考放逐投票`;
    if (p.includes("SPEECH")) return `正在发言`;
    if (p.includes("LAST_WORDS")) return `正在发表遗言`;
    return `正在行动`;
  }

  const actionHint = getActionHint();
  const actionText = activeName
    ? `${activeSeat}号 ${activeName} ${actionHint}`
    : phaseText;

  return (
    <div className="flex items-center gap-3 border-b border-border bg-cardBackground px-5 py-2.5 text-base font-medium">
      <span className="font-semibold text-textPrimary">{statusTitle}</span>
      {actionText && (
        <span className="text-text-sub">
          · <span className="text-primary font-medium">{actionText}</span>
        </span>
      )}
      <span className="text-text-sub/60 ml-auto text-sm">
        {t("aliveCount", language)}: {derived.aliveCount}/{gameState?.players?.length || 0}
      </span>
    </div>
  );
}

export default function GamePage() {
  const params = useParams<{ id: string }>();
  const controller = useGamePageController(params.id);
  const { gameState, derived, phase, scroll } = controller;
  const isEndPhase = phase.visualPhaseGroup === "end" || Boolean(gameState?.winner);
  const showNightOverlay = phase.isVisualNight && !isEndPhase;

  return (
    <ErrorBoundary>
    <div className="h-screen [height:100dvh] flex flex-col overflow-hidden bg-background night-stars" data-phase={phase.visualPhaseGroup} data-phase-aware>
      {/* ── 昼夜眨眼转场（z-index 1500，覆盖一切） ── */}
      <DayNightBlinkTransition
        blinkPhase={controller.blinkPhase}
        onCloseComplete={controller.onBlinkCloseComplete}
        onPauseComplete={controller.onBlinkPauseComplete}
        onOpenComplete={controller.onBlinkOpenComplete}
      />
      <PhaseOverlayCoordinator phaseAnnouncement={phase.phaseAnnouncement} />
      {controller.fetchError && (
        <div className="fixed inset-x-0 top-16 z-[1100] mx-auto max-w-md rounded-card border border-danger/30 bg-cardBackground/95 p-4 shadow-lg backdrop-blur">
          <p className="text-sm text-danger mb-3">{controller.fetchError}</p>
          <div className="flex gap-2">
            <button onClick={controller.retryRoom} className="rounded-button bg-primary px-4 py-1.5 text-xs font-medium text-white hover:bg-primaryHover transition-colors">
              {t("retry", controller.language)}
            </button>
            <button onClick={() => controller.router.push("/")} className="rounded-button border border-border px-4 py-1.5 text-xs font-medium text-text-sub hover:text-textPrimary transition-colors">
              {t("backToLobby", controller.language)}
            </button>
          </div>
        </div>
      )}
      {showNightOverlay && (
        <div className="fixed inset-0 pointer-events-none z-0 bg-night-overlay transition-opacity duration-500 motion-reduce:transition-none" />
      )}

      <GameHeader
        roomId={controller.roomId}
        day={gameState?.day}
        winner={gameState?.winner}
        language={controller.language}
        viewMode={controller.viewMode}
        isVisualNight={phase.isVisualNight}
        isHumanMode={controller.isHumanMode}
        canRun={!controller.isPlaying && !gameState?.winner && (controller.isHumanMode || !!controller.fetchError)}
        onRun={controller.runGame}
        onStartHuman={controller.startHumanGame}
        onViewModeChange={controller.setViewMode}
        onLanguageChange={controller.setLanguage}
      />

      <MobilePlayerRail
        players={gameState?.players || []}
        fallbackPlayers={controller.placeholder(1, gameState?.players?.length || 7)}
        pendingPlayerId={derived.pendingInput?.player_id}
        activeSpeakerId={derived.activeSpeakerId}
        sheriffId={derived.sheriffId}
        badgeCandidateSet={derived.badgeCandidateSet}
        isHumanMode={controller.isHumanMode}
        humanSeat={controller.humanSeat}
        wolfTeammates={derived.wolfTeammates}
        spokenInPhase={derived.spokenInPhase}
        votedSet={derived.votedSet}
        voteCount={derived.voteCount}
        voteTarget={derived.voteTarget}
      />

      <div className="relative z-10 flex flex-1 overflow-hidden">
        <PlayerRail
          side="left"
          players={derived.leftPlayers}
          fallbackPlayers={controller.placeholder(1, Math.ceil((gameState?.players?.length || 7) / 2))}
          pendingPlayerId={derived.pendingInput?.player_id}
          activeSpeakerId={derived.activeSpeakerId}
          sheriffId={derived.sheriffId}
          badgeCandidateSet={derived.badgeCandidateSet}
          isHumanMode={controller.isHumanMode}
          humanSeat={controller.humanSeat}
          wolfTeammates={derived.wolfTeammates}
          spokenInPhase={derived.spokenInPhase}
          votedSet={derived.votedSet}
          voteCount={derived.voteCount}
          voteTarget={derived.voteTarget}
        />

        <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
          <StatusBar
            statusTitle={controller.statusTitle}
            displayPhase={controller.displayPhase}
            gameState={gameState}
            derived={derived}
            language={controller.language}
          />
          {gameState && (
            <BadgePanel
              gameState={gameState}
              language={controller.language}
              activeSpeakerId={derived.activeSpeakerId}
              displayPhase={controller.displayPhase}
              completedIds={controller.completedIdsRef.current}
            />
          )}
          <div ref={scroll.scrollRef} onScroll={scroll.handleScroll} className={`flex-1 overflow-y-auto px-4 py-3 timeline-scroll ${controller.isBlinking ? "pointer-events-none" : ""}`}>
            {gameState?.events?.length ? (
              <>
                <EventTimeline
                  dayBlocks={derived.dayBlocks}
                  language={controller.language}
                  viewMode={controller.viewMode}
                  isHumanMode={controller.isHumanMode}
                  humanSeat={controller.humanSeat}
                  completedIds={controller.completedIdsRef.current}
                  onChatComplete={controller.onChatComplete}
                />
                {/* AI 玩家正在组织发言 → 显示思考气泡（持续到 pending_input 切换） */}
                {(() => {
                  const pi = gameState?.pending_input;
                  if (!pi || pi.action_type !== "speech") return null;
                  return (
                    <ThinkingBubble
                      playerName={pi.player_name}
                      playerSeat={pi.seat}
                      language={controller.language}
                    />
                  );
                })()}
              </>
            ) : controller.isPlaying && !controller.fetchError ? (
              <div className="flex h-full flex-col items-center justify-center py-20 text-center">
                <div className="mb-5 h-10 w-10 animate-spin rounded-full border-2 border-primary/30 border-t-primary" />
                <p className="mb-2 font-display text-lg text-textPrimary">{t("statusStreaming", controller.language)}</p>
                <p className="text-sm text-text-sub">{t("statusHint", controller.language)}</p>
              </div>
            ) : (
              <div className="flex h-full flex-col items-center justify-center py-20 text-center">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" className="mb-5 text-text-sub/25"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" /></svg>
                <p className="mb-2 font-display text-lg text-textPrimary">{t("readyHint", controller.language)}</p>
                <p className="text-sm text-text-sub">{t("statusHint", controller.language)}</p>
              </div>
            )}
          </div>
          {derived.pendingInput && (
            <ActionPanel
              pendingInput={derived.pendingInput}
              onAction={controller.handleHumanAction}
              language={controller.language}
              votes={gameState?.votes}
              players={gameState?.players}
            />
          )}
        </main>

        <PlayerRail
          side="right"
          players={derived.rightPlayers}
          fallbackPlayers={controller.placeholder(derived.splitPoint + 1, gameState?.players?.length || 7)}
          pendingPlayerId={derived.pendingInput?.player_id}
          activeSpeakerId={derived.activeSpeakerId}
          sheriffId={derived.sheriffId}
          badgeCandidateSet={derived.badgeCandidateSet}
          isHumanMode={controller.isHumanMode}
          humanSeat={controller.humanSeat}
          wolfTeammates={derived.wolfTeammates}
          spokenInPhase={derived.spokenInPhase}
          votedSet={derived.votedSet}
          voteCount={derived.voteCount}
          voteTarget={derived.voteTarget}
        />
      </div>

      {gameState?.winner && (
        <GameEndPanel
          winner={gameState.winner}
          day={gameState.day}
          aliveCount={derived.aliveCount}
          eventCount={gameState.event_count || 0}
          language={controller.language}
          showPanel={controller.showWinnerPanel}
          ballPos={controller.ballPos}
          dragRef={controller.dragRef}
          onOpen={() => controller.setShowWinnerPanel(true)}
          onClose={() => controller.setShowWinnerPanel(false)}
          onBallMove={controller.setBallPos}
          onLobby={() => controller.router.push("/")}
          onReport={gameState.id ? () => controller.router.push(`/games/${gameState.id}/report`) : undefined}
        />
      )}
    </div>
    </ErrorBoundary>
  );
}
