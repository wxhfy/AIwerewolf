"use client";

import { useParams, useSearchParams } from "next/navigation";
import { t } from "@/lib/i18n";
import { ActionPanel } from "@/components/game/ActionPanel";
import { BadgePanel } from "@/components/game/BadgePanel";
import { EventTimeline } from "@/components/game/EventTimeline";
import { GameEndPanel } from "@/components/game/GameEndPanel";
import { GameHeader } from "@/components/game/GameHeader";
import { MobilePlayerRail, PlayerRail } from "@/components/game/PlayerRail";
import { ThinkingBubble } from "@/components/game/ThinkingBubble";
import { VotePanel } from "@/components/game/VotePanel";
import { BottomDialogueDock } from "@/components/game/BottomDialogueDock";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";
import { Button } from "@/components/ui/Button";
import { EmptyState, Skeleton } from "@/components/ui/Feedback";
import { useGamePageController } from "@/hooks/useGamePageController";
import { useHumanDisplayState } from "@/hooks/useHumanDisplayState";
import { useHumanActions } from "@/hooks/useHumanActions";
import { AIStatusBar } from "./_components/AIStatusBar";
import { HumanStatusBar } from "./_components/HumanStatusBar";
import { HumanActionBar, SubmittedIndicator } from "./_components/HumanActionBar";
import { RoleRevealOverlay } from "./_components/RoleRevealOverlay";
import { ViewMode, type Player } from "@/types";

export default function GamePage() {
  const params = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const mode = searchParams.get("mode") || "ai";
  const isHuman = mode === "human";

  const controller = useGamePageController(params.id);
  const { gameState, derived, phase, scroll, voteDisplay } = controller;
  const language = controller.language;
  const isGlobalView = controller.viewMode === ViewMode.MODERATOR || isHuman;

  const isEndPhase = phase.visualPhaseGroup === "end" || Boolean(gameState?.winner);
  const showNightOverlay = phase.isVisualNight && !isEndPhase;
  const isLocked = false;

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
    nightRoleInfo: isGlobalView ? derived.nightRoleInfo : null,
    currentPhase: gameState?.phase,
    speakerState: derived.speakerState,
    // Human mode: make cards selectable when choosing target
    selectable: isHuman && humanActions.needsTarget && !humanActions.submitted,
    selectableIds: humanActions.optionIds,
    selectedTargetId: humanActions.selectedTarget,
    onSelectTarget: isHuman
      ? (id: string) => {
          if (humanActions.optionIds.size > 0 && !humanActions.optionIds.has(id)) return;
          humanActions.setSelectedTarget(id);
        }
      : undefined,
  };

  // ── Player list helpers ───────────────────────────────────────────
  const playerCount = gameState?.players?.length || 7;
  const leftFallback = controller.placeholder(1, Math.ceil(playerCount / 2));
  const rightFallback = controller.placeholder(derived.splitPoint + 1, playerCount);

  return (
    <ErrorBoundary>
    <div
      className="game-shell h-screen [height:100dvh] flex flex-col overflow-hidden bg-background text-textPrimary night-stars"
      data-phase={phase.visualPhaseGroup}
      data-phase-aware
    >
      {showNightOverlay && (
        <div className="fixed inset-0 pointer-events-none z-0 bg-night-overlay transition-opacity duration-500 motion-reduce:transition-none" />
      )}

      {/* ── Header ── */}
      <GameHeader
        roomId={controller.roomId}
        day={gameState?.day}
        winner={gameState?.winner}
        language={language}
        isVisualNight={phase.isVisualNight}
        isHumanMode={controller.isHumanMode}
        isPlaying={controller.isPlaying}
        isPaused={controller.isPaused}
        canRun={!isHuman && !controller.isPlaying && !gameState?.winner && !!controller.fetchError}
        onRun={controller.runGame}
        onStartHuman={controller.startHumanGame}
        onPause={controller.pauseGame}
        onResume={controller.resumeGame}
      />

      {controller.fetchError && (
        <div role="alert" className="relative z-20 flex max-h-[25dvh] shrink-0 flex-wrap items-center justify-between gap-2 overflow-y-auto border-b border-danger/25 bg-cardBackground px-3 py-2 sm:px-5">
          <p className="min-w-0 flex-1 basis-48 break-words text-sm text-danger">{controller.fetchError}</p>
          <div className="flex shrink-0 gap-2">
            <Button size="sm" variant="secondary" onClick={controller.retryRoom}>{t("retry", language)}</Button>
            <Button size="sm" variant="ghost" onClick={() => controller.router.push("/")}>{t("backToLobby", language)}</Button>
          </div>
        </div>
      )}

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
        nightRoleInfo={isGlobalView ? derived.nightRoleInfo : null}
        currentPhase={gameState?.phase}
        speakerState={derived.speakerState}
        selectable={railBase.selectable}
        selectableIds={railBase.selectableIds}
        selectedTargetId={railBase.selectedTargetId}
        onSelectTarget={railBase.onSelectTarget}
      />

      {/* ── Main 3-column layout ── */}
      <div className="relative z-10 flex min-h-0 flex-1 overflow-hidden">
        <PlayerRail
          side="left"
          players={derived.leftPlayers}
          fallbackPlayers={leftFallback}
          {...railBase}
        />

        <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden [@media(max-height:600px)]:overflow-y-auto">
          {/* ═══ StatusBar: mode-polymorphic ═══ */}
          {isHuman ? (
            <HumanStatusBar
              display={humanDisplay}
              displayPhase={controller.displayPhase}
              language={language}
              speakerState={derived.speakerState}
              players={gameState?.players}
              runtimeProgress={gameState?.runtime_progress}
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

          {/* ═══ Event timeline (scrollable) ═══ */}
          <div
            ref={scroll.scrollRef}
            onScroll={scroll.handleScroll}
            aria-label={t("timeline", language)}
            tabIndex={0}
            className={`min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 py-4 sm:px-5 timeline-scroll [@media(max-height:600px)]:min-h-24 [@media(max-height:600px)]:shrink-0 ${isLocked ? "pointer-events-none" : ""}`}
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
            ) : (!gameState || controller.isPlaying) && !controller.fetchError ? (
              <div role="status" aria-live="polite" className="mx-auto max-w-2xl space-y-4 py-4 sm:py-8">
                <p className="flex items-center gap-2 text-sm text-textSecondary">
                  <span aria-hidden="true" className="h-3.5 w-3.5 shrink-0 animate-spin rounded-full border-2 border-primary/30 border-t-primary" />
                  {language === "zh" ? "正在同步对局，请稍候…" : "Syncing the match, please wait…"}
                </p>
                {[0, 1, 2].map((item) => (
                  <div key={item} aria-hidden="true" className="space-y-3 rounded-card border border-border bg-cardBackground p-4">
                    <div className="flex items-center gap-3"><Skeleton className="h-8 w-8" /><Skeleton className="h-3 w-24" /></div>
                    <Skeleton className="h-3 w-full" />
                    <Skeleton className="h-3 w-3/4" />
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState
                title={controller.fetchError ? t("statusError", language) : t("readyHint", language)}
                description={controller.fetchError
                  ? (language === "zh" ? "暂时无法连接房间。请重试，或返回大厅选择新对局。" : "The room is unavailable. Retry or return to the lobby.")
                  : (language === "zh" ? "玩家就位后，发言与关键事件会按顺序显示在这里。" : "Speeches and key events will appear here as the match progresses.")}
                icon={<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
                </svg>}
              />
            )}
          </div>

          {/* ═══ Current phase action strip: vote progress is fixed outside log ═══ */}
          {voteDisplay.mode.type === "LIVE_VOTING" && Object.keys(voteDisplay.mode.votes).length > 0 && (
            <div className="shrink-0 px-4 pb-2">
              <VotePanel
                votes={voteDisplay.mode.votes}
                players={gameState!.players}
                language={language}
                phase={voteDisplay.mode.phase}
              />
            </div>
          )}
          {/* VoteResultPanel is now inline in EventTimeline (part of chat narrative flow) */}

          <BottomDialogueDock
            players={gameState?.players || []}
            currentChat={controller.currentDialogueChat}
            pendingPlayerId={derived.pendingInput?.player_id || undefined}
            pendingPlayerName={isHuman && humanDisplay.isMyTurn ? undefined : derived.pendingInput?.player_name || undefined}
            phase={gameState?.phase}
            language={language}
            isLocked={isLocked}
            onChatComplete={controller.onChatComplete}
          />

          {/* ═══ AI mode: ActionPanel ═══ */}
          {!isHuman && isGlobalView && derived.pendingInput && (
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
              savePotion={humanActions.savePotion}
              setSavePotion={humanActions.setSavePotion}
              selectedTarget={humanActions.selectedTarget}
              selectedPlayer={humanActions.targetPlayer as Player | undefined}
              setSelectedTarget={humanActions.setSelectedTarget}
              onSubmit={humanActions.submitAction}
              onSkip={humanActions.submitSkip}
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

      {/* ═══ Human mode: role reveal — show immediately when role is known, before game starts ═══ */}
      {isHuman && humanPlayer?.role && !humanActions.revealDone && (
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
          players={gameState.players}
          language={language}
          showPanel={controller.showWinnerPanel}
          ballPos={controller.ballPos}
          dragRef={controller.dragRef}
          onOpen={() => controller.setShowWinnerPanel(true)}
          onClose={() => controller.setShowWinnerPanel(false)}
          onBallMove={controller.setBallPos}
          onLobby={() => controller.router.push("/")}
          onReport={gameState.id ? () => controller.router.push(`/games/${gameState.id}/report`) : undefined}
          onExport={() => controller.exportGameRecord()}
          reportReady={controller.reportReady}
          reportChecking={controller.reportChecking}
        />
      )}
    </div>
    </ErrorBoundary>
  );
}
