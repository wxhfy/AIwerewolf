"use client";

import { useParams } from "next/navigation";
import { t, tPhase } from "@/lib/i18n";
import { ActionPanel } from "@/components/game/ActionPanel";
import { EventTimeline } from "@/components/game/EventTimeline";
import { GameEndPanel } from "@/components/game/GameEndPanel";
import { GameHeader } from "@/components/game/GameHeader";
import { MobilePlayerRail, PlayerRail } from "@/components/game/PlayerRail";
import { PhaseAnnouncement } from "@/components/game/PhaseAnnouncement";
import { useGamePageController } from "@/hooks/useGamePageController";

export default function GamePage() {
  const params = useParams<{ id: string }>();
  const controller = useGamePageController(params.id);
  const { gameState, derived, phase, scroll } = controller;
  const isEndPhase = phase.visualPhaseGroup === "end" || Boolean(gameState?.winner);
  const showNightOverlay = phase.isVisualNight && !isEndPhase;

  return (
    <div className="h-screen flex flex-col overflow-hidden bg-background night-stars" data-phase={phase.visualPhaseGroup} data-phase-aware>
      {phase.phaseAnnouncement && (
        <PhaseAnnouncement group={phase.phaseAnnouncement.group} visible={phase.phaseAnnouncement.visible} />
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
        canRun={!controller.isPlaying && !gameState?.winner}
        onRun={controller.runGame}
        onStartHuman={controller.startHumanGame}
        onViewModeChange={controller.setViewMode}
        onLanguageChange={controller.setLanguage}
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
        />

        <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
          <div className="flex items-center gap-3 border-b border-border bg-cardBackground px-5 py-2.5 text-base font-medium text-text-sub">
            <span className="font-semibold">{controller.statusTitle}</span>
            {gameState?.phase && <span>· {tPhase(gameState.phase, controller.language)}</span>}
            <span>· {t("aliveCount", controller.language)}: {derived.aliveCount}/{gameState?.players?.length || 0}</span>
            <span>· {t("events", controller.language)}: {gameState?.event_count || 0}</span>
          </div>
          <div ref={scroll.scrollRef} onScroll={scroll.handleScroll} className="flex-1 overflow-y-auto px-4 py-3 [&::-webkit-scrollbar]:hidden [-ms-overflow-style:none] [scrollbar-width:none]">
            {gameState?.events?.length ? (
              <EventTimeline
                dayBlocks={derived.dayBlocks}
                language={controller.language}
                viewMode={controller.viewMode}
                isHumanMode={controller.isHumanMode}
                humanSeat={controller.humanSeat}
              />
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
        />
      </div>

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
      />

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
        />
      )}
    </div>
  );
}
