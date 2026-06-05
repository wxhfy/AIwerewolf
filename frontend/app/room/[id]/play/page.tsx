"use client";

import { useParams, useSearchParams } from "next/navigation";
import { t } from "@/lib/i18n";
import { ActionPanel } from "@/components/game/ActionPanel";
import { BadgePanel } from "@/components/game/BadgePanel";
import { EventTimeline } from "@/components/game/EventTimeline";
import { GameEndPanel } from "@/components/game/GameEndPanel";
import { GameHeader } from "@/components/game/GameHeader";
import { MobilePlayerRail, PlayerRail } from "@/components/game/PlayerRail";
import { PhaseOverlayCoordinator } from "@/components/game/PhaseOverlayCoordinator";
import { DayNightBlinkTransition } from "@/components/game/DayNightBlinkTransition";
import { ThinkingBubble } from "@/components/game/ThinkingBubble";
import { VotePanel } from "@/components/game/VotePanel";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";
import { useGamePageController } from "@/hooks/useGamePageController";
import { useHumanDisplayState } from "@/hooks/useHumanDisplayState";
import { useHumanActions } from "@/hooks/useHumanActions";
import { AIStatusBar } from "./_components/AIStatusBar";
import { HumanStatusBar } from "./_components/HumanStatusBar";
import { HumanActionBar, SubmittedIndicator } from "./_components/HumanActionBar";
import { RoleRevealOverlay } from "./_components/RoleRevealOverlay";
import type { Player } from "@/types";

export default function GamePage() {
  const params = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const mode = searchParams.get("mode") || "ai";
  const isHuman = mode === "human";

  const controller = useGamePageController(params.id);
  const { gameState, derived, phase, scroll, voteDisplay } = controller;
  const language = controller.language;

  const isEndPhase = phase.visualPhaseGroup === "end" || Boolean(gameState?.winner);
  const showNightOverlay = phase.isVisualNight && !isEndPhase;
  const isLocked = controller.isBlinking || controller.isTransitioning;

  // ── Human mode state ──────────────────────────────────────────────
  const humanPlayer = isHuman ? gameState?.players?.find(p => p.seat === controller.humanSeat) : undefined;
  const humanDisplay = useHumanDisplayState(gameState, humanPlayer, controller.viewMode);
  const humanActions = useHumanActions({
    gameState, humanSeat: controller.humanSeat, humanDisplay,
    onSubmit: (data) => controller.handleHumanAction(data),
  });

  // ── Shared PlayerRail props ───────────────────────────────────────
  const railBase = {
    pendingPlayerId: derived.pendingInput?.player_id,
    activeSpeakerId: derived.activeSpeakerId,
    sheriffId: derived.sheriffId,
    badgeCandidateSet: derived.badgeCandidateSet,
    isHumanMode: controller.isHumanMode,
    humanSeat: controller.humanSeat,
    wolfTeammates: derived.wolfTeammates,
    spokenInPhase: derived.spokenInPhase,
    nightRoleInfo: derived.nightRoleInfo,
    currentPhase: gameState?.phase,
    speakerState: derived.speakerState,
    // Human mode: make cards selectable when choosing target
    selectable: isHuman && humanActions.needsTarget && !humanActions.submitted,
    selectedTargetId: humanActions.selectedTarget,
    onSelectTarget: isHuman ? humanActions.setSelectedTarget : undefined,
  };

  // ── Player list helpers ───────────────────────────────────────────
  const playerCount = gameState?.players?.length || 7;
  const leftFallback = controller.placeholder(1, Math.ceil(playerCount / 2));
  const rightFallback = controller.placeholder(derived.splitPoint + 1, playerCount);

  return (
    <ErrorBoundary>
    <div
      className="h-screen [height:100dvh] flex flex-col overflow-hidden bg-background night-stars"
      data-phase={phase.visualPhaseGroup}
      data-phase-aware
    >
      {/* ── 昼夜眨眼转场（z-index 1500，覆盖一切） ── */}
      <DayNightBlinkTransition
        blinkPhase={controller.blinkPhase}
        onCloseComplete={controller.onBlinkCloseComplete}
        onPauseComplete={controller.onBlinkPauseComplete}
        onOpenComplete={controller.onBlinkOpenComplete}
      />
      <PhaseOverlayCoordinator phaseAnnouncement={phase.phaseAnnouncement} />

      {/* ── Fetch error ── */}
      {controller.fetchError && (
        <div className="fixed inset-x-0 top-16 z-[1100] mx-auto max-w-md rounded-card border border-danger/30 bg-cardBackground/95 p-4 shadow-lg backdrop-blur">
          <p className="text-sm text-danger mb-3">{controller.fetchError}</p>
          <div className="flex gap-2">
            <button onClick={controller.retryRoom} className="rounded-button bg-primary px-4 py-1.5 text-xs font-medium text-white hover:bg-primaryHover transition-colors">
              {t("retry", language)}
            </button>
            <button onClick={() => controller.router.push("/")} className="rounded-button border border-border px-4 py-1.5 text-xs font-medium text-text-sub hover:text-textPrimary transition-colors">
              {t("backToLobby", language)}
            </button>
          </div>
        </div>
      )}

      {showNightOverlay && (
        <div className="fixed inset-0 pointer-events-none z-0 bg-night-overlay transition-opacity duration-500 motion-reduce:transition-none" />
      )}

      {/* ── Header ── */}
      <GameHeader
        roomId={controller.roomId}
        day={gameState?.day}
        winner={gameState?.winner}
        language={language}
        viewMode={controller.viewMode}
        isVisualNight={phase.isVisualNight}
        isHumanMode={controller.isHumanMode}
        canRun={!isHuman && !controller.isPlaying && !gameState?.winner && !!controller.fetchError}
        onRun={controller.runGame}
        onStartHuman={controller.startHumanGame}
        onViewModeChange={controller.setViewMode}
        onLanguageChange={controller.setLanguage}
      />

      {/* ── Mobile player rail ── */}
      <MobilePlayerRail
        players={gameState?.players || []}
        fallbackPlayers={controller.placeholder(1, playerCount)}
        pendingPlayerId={derived.pendingInput?.player_id}
        activeSpeakerId={derived.activeSpeakerId}
        sheriffId={derived.sheriffId}
        badgeCandidateSet={derived.badgeCandidateSet}
        isHumanMode={controller.isHumanMode}
        humanSeat={controller.humanSeat}
        wolfTeammates={derived.wolfTeammates}
        spokenInPhase={derived.spokenInPhase}
        nightRoleInfo={derived.nightRoleInfo}
        currentPhase={gameState?.phase}
        speakerState={derived.speakerState}
      />

      {/* ── Main 3-column layout ── */}
      <div className="relative z-10 flex flex-1 overflow-hidden">
        <PlayerRail
          side="left"
          players={derived.leftPlayers}
          fallbackPlayers={leftFallback}
          {...railBase}
        />

        <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
          {/* ═══ StatusBar: mode-polymorphic ═══ */}
          {isHuman ? (
            <HumanStatusBar
              display={humanDisplay}
              displayPhase={controller.displayPhase}
              language={language}
              speakerState={derived.speakerState}
              players={gameState?.players}
            />
          ) : (
            <AIStatusBar
              gameState={gameState}
              derived={derived}
              language={language}
            />
          )}

          {/* ═══ Badge panel ═══ */}
          {gameState && (
            <BadgePanel
              gameState={gameState}
              language={language}
              activeSpeakerId={derived.activeSpeakerId}
              displayPhase={controller.displayPhase}
              completedIds={controller.completedIdsRef.current}
            />
          )}

          {/* ═══ Vote display: centralized via useVoteDisplay ═══ */}
          {voteDisplay.mode.type === "LIVE_VOTING" && Object.keys(voteDisplay.mode.votes).length > 0 && (
            <VotePanel
              votes={voteDisplay.mode.votes}
              players={gameState!.players}
              language={language}
              phase={voteDisplay.mode.phase}
            />
          )}
          {/* VoteResultPanel is now inline in EventTimeline (part of chat narrative flow) */}

          {/* ═══ Event timeline (scrollable) ═══ */}
          <div
            ref={scroll.scrollRef}
            onScroll={scroll.handleScroll}
            className={`flex-1 overflow-y-auto px-4 py-3 timeline-scroll ${isLocked ? "pointer-events-none" : ""}`}
          >
            {gameState?.events?.length ? (
              <>
                <EventTimeline
                  dayBlocks={derived.dayBlocks}
                  language={language}
                  viewMode={controller.viewMode}
                  isHumanMode={controller.isHumanMode}
                  humanSeat={controller.humanSeat}
                  completedIds={controller.completedIdsRef.current}
                  onChatComplete={controller.onChatComplete}
                  hideDayHeaders={isHuman}
                  dayVotes={gameState?.vote_history as Record<number, Record<string, string>> | undefined}
                  players={gameState?.players}
                  nightActions={gameState?.night_actions}
                  decisionRecords={gameState?.decision_records as any}
                  isTransitioning={controller.isTransitioning}
                  currentDay={gameState?.day}
                  speakerState={derived.speakerState}
                />

                {/* ── Thinking bubble: skip human player ── */}
                {(() => {
                  const pi = gameState?.pending_input;
                  if (!pi || pi.action_type !== "speech") return null;
                  // Human player has their own action bar, no thinking bubble
                  if (isHuman && pi.seat === controller.humanSeat) return null;
                  // Already has chat message → typewriter is playing
                  const hasChat = (gameState?.events || []).some(
                    e => e.type === "CHAT_MESSAGE" &&
                      (e.payload as any)?.actor_id === pi.player_id &&
                      e.phase === gameState.phase
                  );
                  if (hasChat) return null;
                  return (
                    <ThinkingBubble
                      playerName={pi.player_name}
                      playerSeat={pi.seat}
                      language={language}
                    />
                  );
                })()}
              </>
            ) : controller.isPlaying && !controller.fetchError ? (
              <div className="flex h-full flex-col items-center justify-center py-20 text-center">
                <div className="mb-5 h-10 w-10 animate-spin rounded-full border-2 border-primary/30 border-t-primary" />
                <p className="mb-2 font-display text-lg text-textPrimary">
                  {t("statusStreaming", language)}
                </p>
                <p className="text-sm text-text-sub">{t("statusHint", language)}</p>
              </div>
            ) : (
              <div className="flex h-full flex-col items-center justify-center py-20 text-center">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" className="mb-5 text-text-sub/25">
                  <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
                </svg>
                <p className="mb-2 font-display text-lg text-textPrimary">
                  {t("readyHint", language)}
                </p>
                <p className="text-sm text-text-sub">{t("statusHint", language)}</p>
              </div>
            )}
          </div>

          {/* ═══ AI mode: ActionPanel ═══ */}
          {!isHuman && derived.pendingInput && (
            <ActionPanel
              pendingInput={derived.pendingInput}
              onAction={controller.handleHumanAction}
              language={language}
              votes={gameState?.votes}
              players={gameState?.players}
            />
          )}

          {/* ═══ Human mode: ActionBar ═══ */}
          {isHuman && humanDisplay.isMyTurn && humanActions.revealDone && humanDisplay.canAct && !humanActions.submitted && !controller.isBlinking && (
            <HumanActionBar
              pending={gameState?.pending_input}
              isSpeech={humanActions.isSpeech}
              needsTarget={humanActions.needsTarget}
              canSubmit={humanActions.canSubmit}
              speech={humanActions.speech}
              setSpeech={humanActions.setSpeech}
              selectedTarget={humanActions.selectedTarget}
              selectedPlayer={humanActions.targetPlayer as Player | undefined}
              setSelectedTarget={humanActions.setSelectedTarget}
              onSubmit={() => {
                if (humanActions.submitted) return;
                controller.handleHumanAction({
                  target_id: humanActions.needsTarget ? (humanActions.selectedTarget || null) : null,
                  speech: humanActions.isSpeech ? (humanActions.speech.trim() || null) : null,
                  save: false,
                });
              }}
              language={language}
            />
          )}

          {/* ═══ Human mode: submitted indicator ═══ */}
          {isHuman && humanActions.submitted && (
            <SubmittedIndicator language={language} />
          )}
        </main>

        <PlayerRail
          side="right"
          players={derived.rightPlayers}
          fallbackPlayers={rightFallback}
          {...railBase}
        />
      </div>

      {/* ═══ Human mode: role reveal overlay ═══ */}
      {isHuman && humanDisplay.isMyTurn && !humanActions.revealDone && humanPlayer && (
        <RoleRevealOverlay
          role={(humanPlayer.role as string) || ""}
          alignment={(humanPlayer.alignment as string) || ""}
          seat={humanPlayer.seat}
          name={humanPlayer.name}
          wolfTeammates={humanDisplay.wolfTeammates}
          language={language}
          onRevealed={() => humanActions.setRevealDone(true)}
        />
      )}

      {/* ═══ Game end panel ═══ */}
      {gameState?.winner && (
        <GameEndPanel
          winner={gameState.winner}
          day={gameState.day}
          aliveCount={derived.aliveCount}
          eventCount={gameState.event_count || 0}
          language={language}
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
