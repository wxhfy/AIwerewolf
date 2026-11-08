"use client";

import React, { useMemo, useState } from "react";
import Link from "next/link";
import { GameState, Alignment, Role, Player } from "@/types";
import { useSpeechQueue } from "@/hooks/useSpeechQueue";
import { PhaseAnnouncement } from "@/components/game/PhaseAnnouncement";
import { DayNightBlinkTransition } from "@/components/game/DayNightBlinkTransition";

interface MoonlitVillageSpectatorProps {
  roomId: string;
  gameState: GameState | null;
  phase: any;
  controller: any;
}

const roleNames: Record<string, string> = {
  [Role.VILLAGER]: "村民",
  [Role.WEREWOLF]: "狼人",
  [Role.WHITE_WOLF_KING]: "白狼王",
  [Role.SEER]: "预言家",
  [Role.WITCH]: "女巫",
  [Role.HUNTER]: "猎人",
  [Role.GUARD]: "守卫",
  [Role.IDIOT]: "白痴",
  [Role.KNIGHT]: "骑士",
  [Role.ELDER]: "长老",
  [Role.CUPID]: "丘比特",
};

const PHASE_LABEL: Record<string, string> = {
  SETUP: "准备阶段",
  NIGHT_START: "天黑请闭眼",
  NIGHT_GUARD_ACTION: "守卫行动",
  NIGHT_WOLF_ACTION: "狼人行动",
  NIGHT_WITCH_ACTION: "女巫行动",
  NIGHT_SEER_ACTION: "预言家行动",
  NIGHT_RESOLVE: "夜晚结算",
  DAY_START: "天亮了",
  DAY_BADGE_SIGNUP: "警徽竞选报名",
  DAY_BADGE_SPEECH: "警徽竞选发言",
  DAY_BADGE_ELECTION: "警徽投票",
  DAY_PK_SPEECH: "PK 发言",
  DAY_SPEECH: "白天发言",
  DAY_SHERIFF_CLOSING: "警长归票",
  DAY_VOTE: "白天投票",
  DAY_LAST_WORDS: "遗言",
  DAY_RESOLVE: "白天结算",
  HUNTER_SHOOT: "猎人开枪",
  BADGE_TRANSFER: "警徽移交",
  WHITE_WOLF_KING_BOOM: "白狼王自爆",
  GAME_END: "游戏结束",
};

export function MoonlitVillageSpectator({
  roomId,
  gameState,
  phase,
  controller,
}: MoonlitVillageSpectatorProps) {
  const isNight = phase.isVisualNight;
  const currentTheme = isNight ? "night" : "day";
  const currentPhase = gameState?.phase || "SETUP";
  const day = gameState?.day || 1;
  const winner = gameState?.winner;

  // Active speaker ID
  const activeSpeakerId =
    gameState?.current_speaker_id ||
    gameState?.pending_input?.player_id ||
    controller.derived?.activeSpeakerId;

  // Typewriter speech queue
  const {
    displayedSpeeches,
    currentSpeech,
    isTyping,
    skipCurrent,
  } = useSpeechQueue(gameState?.events, {
    onSpeechComplete: controller.onChatComplete,
  });

  const [showHistory, setShowHistory] = useState(false);

  const players: Player[] = useMemo(() => {
    if (gameState?.players && gameState.players.length > 0) {
      return [...gameState.players].sort((a, b) => a.seat - b.seat);
    }
    return controller.placeholder(1, 7);
  }, [gameState?.players, controller]);

  const playerCount = players.length;

  // Extract votes for display
  const votes = useMemo(() => {
    if (gameState?.votes && Object.keys(gameState.votes).length > 0) {
      return gameState.votes;
    }
    const voteHistory = gameState?.vote_history as Record<number, Record<string, string>> | undefined;
    if (voteHistory) {
      const days = Object.keys(voteHistory).map(Number).filter((n) => !isNaN(n));
      if (days.length > 0) {
        const latestDay = Math.max(...days);
        return voteHistory[latestDay] || {};
      }
    }
    return {};
  }, [gameState?.votes, gameState?.vote_history]);

  const voteList = useMemo(() => {
    const list: Array<{ voterSeat: number; targetSeat: number; voterName: string; targetName: string }> = [];
    for (const [voterId, targetId] of Object.entries(votes)) {
      const voter = players.find((p: Player) => p.id === voterId || String(p.seat) === voterId);
      const target = players.find((p: Player) => p.id === targetId || String(p.seat) === targetId);
      if (voter && target) {
        list.push({
          voterSeat: voter.seat,
          targetSeat: target.seat,
          voterName: voter.name,
          targetName: target.name,
        });
      }
    }
    return list;
  }, [votes, players]);

  // Center judge announcement text
  const judgeAnnouncement = useMemo(() => {
    if (winner) {
      return winner === Alignment.WOLF ? "对局结束，狼人阵营获胜！" : "对局结束，好人阵营获胜！";
    }
    if (gameState?.pending_input?.request) {
      return gameState.pending_input.request;
    }
    if (currentPhase.includes("NIGHT")) {
      return "夜深人静，请闭眼入眠...";
    }
    if (currentPhase.includes("VOTE")) {
      return "放逐投票进行中，请村民们做出裁决。";
    }
    if (currentPhase.includes("SPEECH")) {
      const activePlayer = players.find((p) => p.id === activeSpeakerId);
      return activePlayer ? `请 ${activePlayer.seat} 号玩家 ${activePlayer.name} 发言` : "自由发言讨论中...";
    }
    return controller.statusTitle || "等待游戏进程推进...";
  }, [winner, gameState?.pending_input, currentPhase, activeSpeakerId, players, controller.statusTitle]);

  // Seat ellipse geometry for desktop
  const seatPositions = useMemo(() => {
    const coords: Record<number, { x: number; y: number }> = {};
    for (let i = 0; i < playerCount; i++) {
      const seat = players[i].seat;
      const angle = -Math.PI / 2 + (2 * Math.PI * i) / playerCount;
      // Ellipse radii in percentages (42% X, 38% Y)
      const x = 50 + 42 * Math.cos(angle);
      const y = 50 + 38 * Math.sin(angle);
      coords[seat] = { x, y };
    }
    return coords;
  }, [playerCount, players]);

  // Active speech for bottom dialogue dock
  const activeSpeech =
    currentSpeech ||
    (displayedSpeeches.length > 0 ? displayedSpeeches[displayedSpeeches.length - 1] : null);

  const speakerPlayer = activeSpeech
    ? players.find((p) => p.id === activeSpeech.actorId || p.seat === activeSpeech.actorSeat)
    : null;
  const speakerName =
    speakerPlayer?.name ||
    activeSpeech?.actorName ||
    (isNight ? "月下村庄" : "村庄广播");
  const speakerSeat =
    speakerPlayer?.seat ??
    (activeSpeech?.actorSeat && activeSpeech.actorSeat > 0 ? activeSpeech.actorSeat : undefined);
  const speakerInitial = speakerPlayer?.name
    ? speakerPlayer.name.slice(0, 1)
    : activeSpeech?.actorName
    ? activeSpeech.actorName.slice(0, 1)
    : isNight
    ? "🌙"
    : "☀️";
  const speechPhaseLabel = activeSpeech
    ? PHASE_LABEL[activeSpeech.phase] || activeSpeech.phase
    : PHASE_LABEL[currentPhase] || "等待中";
  const speechBody = activeSpeech
    ? activeSpeech.displayedText || "..."
    : isNight
    ? "夜幕低垂，村庄寂静。等待玩家发言..."
    : "天亮了，等待玩家开始发言...";

  return (
    <div
      data-theme={currentTheme}
      data-phase={phase.visualPhaseGroup}
      className="relative flex h-screen [height:100dvh] w-full max-w-full flex-col overflow-hidden bg-[var(--color-bg)] text-[var(--color-text)] transition-colors duration-700"
    >
      {/* ── DayNight Blink Transition ── */}
      <DayNightBlinkTransition
        blinkPhase={phase.blinkPhase}
        onCloseComplete={phase.onBlinkCloseComplete}
        onPauseComplete={phase.onBlinkPauseComplete}
        onOpenComplete={phase.onBlinkOpenComplete}
      />

      {/* ── Phase Announcement Overlay (hidden on winner) ── */}
      {!winner && phase.phaseAnnouncement && (
        <PhaseAnnouncement
          group={phase.phaseAnnouncement.group}
          visible={phase.phaseAnnouncement.visible}
          text={phase.phaseAnnouncement.text}
        />
      )}

      {/* ── Top Bar / Header ── */}
      <header className="relative z-30 flex h-14 shrink-0 items-center justify-between border-b border-[var(--color-border)] bg-[var(--color-card)]/80 px-4 backdrop-blur-sm sm:px-6">
        <div className="flex items-center gap-3">
          <Link
            href="/"
            className="flex items-center gap-1.5 text-xs text-[var(--color-text-sub)] transition-colors hover:text-[var(--color-primary)]"
          >
            <span>←</span>
            <span className="hidden sm:inline">大厅</span>
          </Link>
          <div className="h-4 w-px bg-[var(--color-border)]" />
          <div className="flex items-center gap-2">
            <span className="text-base" role="img" aria-label="moon-village">
              {isNight ? "🌙" : "☀️"}
            </span>
            <h1 className="font-display text-sm font-bold tracking-wider text-[var(--color-text)] sm:text-base">
              月下村庄 · AI 观战
            </h1>
          </div>
          <span className="hidden rounded-full border border-[var(--color-border)] bg-[var(--color-bg)]/50 px-2.5 py-0.5 text-xs font-mono text-[var(--color-text-sub)] sm:inline">
            房间: {roomId.slice(0, 8)}
          </span>
        </div>

        <div className="flex items-center gap-3">
          {/* Reconnect Indicator */}
          {controller.isReconnecting && (
            <div
              data-testid="reconnect-indicator"
              role="status"
              className="flex items-center gap-1.5 rounded-full border border-amber-500/40 bg-amber-500/20 px-2.5 py-1 text-xs font-medium text-amber-300 animate-pulse"
            >
              <span className="h-2 w-2 rounded-full bg-amber-400" />
              <span>网络重连中...</span>
            </div>
          )}

          {/* God view 403 fallback notice */}
          {controller.godViewNotice && (
            <div
              role="alert"
              className="flex items-center gap-1.5 rounded-md border border-[var(--color-danger)]/30 bg-[var(--color-danger)]/15 px-2.5 py-1 text-xs text-[var(--color-danger)]"
            >
              <span>{controller.godViewNotice}</span>
              <button
                type="button"
                onClick={() => controller.setGodViewNotice(null)}
                className="ml-1 opacity-70 hover:opacity-100"
                aria-label="关闭提示"
              >
                ✕
              </button>
            </div>
          )}

          {/* Pause / Resume Controls */}
          {!winner && (
            <div className="flex items-center gap-2">
              {controller.isPaused ? (
                <button
                  type="button"
                  onClick={controller.resumeGame}
                  className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-1 text-xs font-medium text-[var(--color-text)] hover:border-[var(--color-primary)]"
                >
                  继续
                </button>
              ) : (
                <button
                  type="button"
                  onClick={controller.pauseGame}
                  className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-1 text-xs font-medium text-[var(--color-text-sub)] hover:text-[var(--color-text)]"
                >
                  暂停
                </button>
              )}
            </div>
          )}
        </div>
      </header>

      {/* ── Main View: Full Width Village Circle Arena ── */}
      <main className="relative flex flex-1 min-h-0 w-full flex-col overflow-hidden p-2 sm:p-4">
        {/* Mobile Top Seats Strip (<768px): Two rows horizontally scrollable */}
        <div className="block md:hidden w-full shrink-0 overflow-x-auto pb-2 scrollbar-none">
          <div className="grid grid-rows-2 grid-flow-col auto-cols-[105px] gap-2 min-w-max px-2">
            {players.map((player) => {
              const isActive = player.id === activeSpeakerId || player.seat === activeSpeakerId;
              const isAlive = player.alive;
              return (
                <div
                  key={player.seat}
                  data-testid={`seat-${player.seat}`}
                  data-alive={isAlive ? "true" : "false"}
                  data-active={isActive ? "true" : "false"}
                  className={`flex items-center gap-2 rounded-xl border p-2 text-xs transition-all duration-300 ${
                    isActive
                      ? "border-[var(--color-primary)] bg-[var(--color-card)] ring-2 ring-[var(--color-primary)] shadow-[0_0_12px_rgba(246,173,85,0.4)]"
                      : isAlive
                      ? "border-[var(--color-border)] bg-[var(--color-card)]/80"
                      : "border-stone-800/60 bg-stone-900/60 opacity-40 grayscale"
                  }`}
                >
                  <div
                    className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
                      isAlive
                        ? "bg-[var(--color-primary)]/20 text-[var(--color-primary)]"
                        : "bg-stone-800 text-stone-400"
                    }`}
                  >
                    {isAlive ? player.seat : "🪦"}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-semibold">{player.name}</p>
                    <p className="truncate text-[10px] text-[var(--color-text-sub)]">
                      {isAlive ? (isActive ? "发言中" : `${player.seat}号位`) : "阵亡"}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Mobile Vote Notice Strip (<768px) */}
        {voteList.length > 0 && (
          <div className="block md:hidden shrink-0 px-2 py-1 mb-1">
            <div className="flex flex-wrap items-center gap-1.5 rounded-lg border border-[var(--color-border)] bg-[var(--color-card)]/90 p-2 text-xs">
              <span className="font-semibold text-[var(--color-text-sub)]">投票:</span>
              {voteList.map((item) => (
                <span
                  key={`${item.voterSeat}-${item.targetSeat}`}
                  data-testid="vote-arrow"
                  className="rounded bg-[var(--color-primary)]/10 px-1.5 py-0.5 font-mono text-[11px] text-[var(--color-primary)]"
                >
                  {item.voterSeat}号 → {item.targetSeat}号
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Desktop Circular Ellipse Arena (>=768px) */}
        <div className="hidden md:flex relative flex-1 min-h-0 w-full items-center justify-center p-4 lg:p-6">
          <div className="relative w-full max-w-[880px] aspect-[16/10] max-h-full">
            {/* SVG Vote Arrows Overlay */}
            <svg className="absolute inset-0 h-full w-full pointer-events-none z-10" viewBox="0 0 100 100">
              <defs>
                <marker
                  id="arrowhead"
                  markerWidth="6"
                  markerHeight="6"
                  refX="5"
                  refY="3"
                  orient="auto"
                >
                  <polygon points="0 0, 6 3, 0 6" fill="var(--color-primary)" />
                </marker>
              </defs>
              {voteList.map((vote) => {
                const from = seatPositions[vote.voterSeat];
                const to = seatPositions[vote.targetSeat];
                if (!from || !to) return null;
                return (
                  <line
                    key={`${vote.voterSeat}-${vote.targetSeat}`}
                    data-testid="vote-arrow"
                    x1={from.x}
                    y1={from.y}
                    x2={to.x}
                    y2={to.y}
                    stroke="var(--color-primary)"
                    strokeWidth="0.8"
                    strokeDasharray="2,1"
                    markerEnd="url(#arrowhead)"
                    className="opacity-80"
                  />
                );
              })}
            </svg>

            {/* Center "Campfire" Panel */}
            <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-20 w-64 rounded-2xl border border-[var(--color-border)] bg-[var(--color-card)]/90 p-4 text-center shadow-lg backdrop-blur-md">
              {/* Campfire glow icon */}
              <div className="mx-auto mb-2 flex h-10 w-10 items-center justify-center rounded-full bg-[var(--color-primary)]/15 text-lg shadow-[0_0_16px_rgba(246,173,85,0.3)]">
                {isNight ? "🕯️" : "🔥"}
              </div>

              {/* Phase Banner */}
              <div data-testid="phase-banner" data-phase={currentPhase}>
                <p className="text-xs font-semibold tracking-wider text-[var(--color-primary)]">
                  第 {day} {isNight ? "夜" : "天"}
                </p>
                <h2 className="font-display text-base font-bold text-[var(--color-text)]">
                  {PHASE_LABEL[currentPhase] || currentPhase}
                </h2>
              </div>

              <div className="mt-2 border-t border-[var(--color-border)]/50 pt-2">
                <p className="line-clamp-2 text-xs leading-relaxed text-[var(--color-text-sub)]">
                  {judgeAnnouncement}
                </p>
              </div>
            </div>

            {/* Circular Seats Ring */}
            {players.map((player) => {
              const pos = seatPositions[player.seat] || { x: 50, y: 50 };
              const isActive = player.id === activeSpeakerId || player.seat === activeSpeakerId;
              const isAlive = player.alive;

              return (
                <div
                  key={player.seat}
                  data-testid={`seat-${player.seat}`}
                  data-alive={isAlive ? "true" : "false"}
                  data-active={isActive ? "true" : "false"}
                  style={{
                    left: `${pos.x}%`,
                    top: `${pos.y}%`,
                    transform: "translate(-50%, -50%)",
                  }}
                  className={`absolute z-20 flex w-28 flex-col items-center rounded-2xl border p-2.5 text-center transition-all duration-300 ${
                    isActive
                      ? "border-[var(--color-primary)] bg-[var(--color-card)] ring-4 ring-[var(--color-primary)]/50 shadow-[0_0_24px_rgba(246,173,85,0.5)] scale-105"
                      : isAlive
                      ? "border-[var(--color-border)] bg-[var(--color-card)]/85 hover:border-[var(--color-primary)]/40 shadow-sm"
                      : "rounded-t-2xl rounded-b-md border-stone-800/80 bg-stone-900/80 opacity-40 grayscale"
                  }`}
                >
                  {/* Seat number seal */}
                  <div
                    className={`mb-1.5 flex h-10 w-10 items-center justify-center rounded-full text-sm font-bold transition-transform ${
                      isAlive
                        ? isActive
                          ? "bg-[var(--color-primary)] text-[var(--color-on-primary)] shadow-md"
                          : "bg-[var(--color-primary)]/15 text-[var(--color-primary)]"
                        : "bg-stone-800 text-stone-400"
                    }`}
                  >
                    {isAlive ? `${player.seat}号` : "🪦"}
                  </div>

                  <p className="w-full truncate text-xs font-semibold text-[var(--color-text)]">
                    {player.name}
                  </p>

                  <p className="mt-0.5 text-[10px] text-[var(--color-text-sub)]">
                    {isAlive ? (isActive ? "发言中" : "就席") : "阵亡"}
                  </p>

                  {/* Revealed role (if post-game disclosure or public role) */}
                  {winner && player.role && (
                    <span className="mt-1 rounded bg-[var(--color-primary)]/15 px-1.5 py-0.5 text-[10px] font-medium text-[var(--color-primary)]">
                      {roleNames[player.role] || player.role}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </main>

      {/* ── Collapsible History Strip (if toggled) ── */}
      {showHistory && displayedSpeeches.length > 0 && (
        <div className="relative z-20 w-full px-3 sm:px-6">
          <div className="mx-auto max-h-48 w-full max-w-4xl overflow-y-auto rounded-xl border border-[var(--color-border)] bg-[var(--color-card)]/95 p-3 shadow-xl backdrop-blur-md timeline-scroll space-y-2">
            <div className="flex items-center justify-between border-b border-[var(--color-border)]/50 pb-1.5 text-xs text-[var(--color-text-sub)]">
              <span className="font-semibold text-[var(--color-text)]">发言历史记录 ({displayedSpeeches.length})</span>
              <button
                type="button"
                onClick={() => setShowHistory(false)}
                className="opacity-70 hover:opacity-100 text-xs px-1"
                aria-label="关闭历史记录"
              >
                ✕
              </button>
            </div>
            {displayedSpeeches.map((item, idx) => (
              <div key={`${item.id}-${idx}`} className="border-b border-[var(--color-border)]/30 pb-1.5 last:border-0 text-xs">
                <div className="flex items-center gap-2 text-[11px] text-[var(--color-primary)] font-medium">
                  <span>{item.actorSeat > 0 ? `${item.actorSeat}号 ` : ""}{item.actorName}</span>
                  <span className="text-[10px] text-[var(--color-text-sub)]">({PHASE_LABEL[item.phase] || item.phase})</span>
                  <span className="opacity-60 text-[10px]">第 {item.day} 天</span>
                </div>
                <p className="mt-0.5 text-[var(--color-text)] leading-relaxed whitespace-pre-wrap">{item.fullText}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Bottom Dialogue Dock ── */}
      <footer
        data-testid="bottom-dialogue-dock"
        data-phase-aware
        className="relative z-20 shrink-0 border-t border-[var(--color-border)] bg-[var(--color-card)]/95 px-3 py-2 sm:px-6 sm:py-2.5 backdrop-blur-md transition-colors"
      >
        <div className="mx-auto flex w-full max-w-4xl items-center gap-2.5 sm:gap-3">
          {/* Avatar & Seat Seal */}
          <div
            className={`relative flex h-11 w-11 sm:h-13 sm:w-13 shrink-0 items-center justify-center rounded-2xl border transition-all ${
              isTyping
                ? "border-[var(--color-primary)] bg-[var(--color-primary)]/15 ring-2 ring-[var(--color-primary)]/40 shadow-[0_0_12px_rgba(246,173,85,0.3)]"
                : "border-[var(--color-border)] bg-[var(--color-card)]"
            }`}
          >
            <span className="font-display text-lg sm:text-xl font-bold text-[var(--color-primary)]">
              {speakerInitial}
            </span>
            {speakerSeat != null && (
              <span className="absolute -bottom-1 -right-1 flex h-4 w-4 sm:h-5 sm:w-5 items-center justify-center rounded-full bg-[var(--color-primary)] text-[9px] sm:text-[10px] font-bold text-[var(--color-on-primary)] shadow-sm">
                {speakerSeat}
              </span>
            )}
          </div>

          {/* Dialogue Bubble */}
          <div
            data-testid={activeSpeech ? "speech-item" : undefined}
            data-event-id={activeSpeech?.id}
            className="flex min-h-[64px] sm:min-h-[72px] min-w-0 flex-1 flex-col justify-center rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg)]/80 px-3 py-1.5 sm:px-4 sm:py-2 backdrop-blur-sm shadow-sm"
          >
            {/* Header: Name, Phase, Status, Controls */}
            <div className="mb-0.5 sm:mb-1 flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 min-w-0">
                <p className="truncate text-xs sm:text-sm font-bold text-[var(--color-text)]">
                  {speakerSeat != null ? `${speakerSeat}号 ` : ""}{speakerName}
                </p>
                <span className="truncate rounded bg-[var(--color-primary)]/10 px-1.5 py-0.5 text-[10px] text-[var(--color-primary)]">
                  {speechPhaseLabel}
                </span>
              </div>

              <div className="flex items-center gap-1.5 sm:gap-2 shrink-0">
                <span className="rounded-full bg-[var(--color-primary)]/10 px-2 py-0.5 text-[10px] font-medium text-[var(--color-primary)]">
                  {isTyping ? "发言中" : activeSpeech ? "当前发言" : "等待中"}
                </span>

                {displayedSpeeches.length > 1 && (
                  <button
                    type="button"
                    onClick={() => setShowHistory((prev) => !prev)}
                    className="rounded border border-[var(--color-border)] bg-[var(--color-card)] px-2 py-0.5 text-[10px] text-[var(--color-text-sub)] hover:text-[var(--color-text)] transition-colors"
                  >
                    {showHistory ? "收起历史" : `历史 (${displayedSpeeches.length})`}
                  </button>
                )}

                <button
                  type="button"
                  data-testid="skip-typing"
                  onClick={skipCurrent}
                  disabled={!isTyping}
                  className={`rounded-lg border px-2.5 py-0.5 sm:px-3 sm:py-1 text-[11px] sm:text-xs font-medium transition-all ${
                    isTyping
                      ? "border-[var(--color-primary)] bg-[var(--color-primary)]/15 text-[var(--color-primary)] hover:bg-[var(--color-primary)]/25 cursor-pointer shadow-sm"
                      : "border-[var(--color-border)] text-[var(--color-text-sub)]/40 cursor-not-allowed opacity-50"
                  }`}
                >
                  跳过
                </button>
              </div>
            </div>

            {/* Typewriter Speech Text */}
            <div
              data-testid="bottom-dialogue-text-wrap"
              className="max-h-14 sm:max-h-16 overflow-y-auto timeline-scroll text-xs sm:text-sm leading-relaxed text-[var(--color-text)]"
            >
              <span data-testid="bottom-dialogue-text" className="whitespace-pre-wrap break-words">
                {speechBody}
              </span>
              {isTyping && (
                <span className="inline-block h-3.5 w-1 bg-[var(--color-primary)] ml-1 animate-pulse align-middle" />
              )}
            </div>
          </div>
        </div>
      </footer>

      {/* ── Game End Settlement Panel ── */}
      {winner && (
        <div
          data-testid="game-end-panel"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-md"
        >
          <div className="w-full max-w-lg rounded-2xl border border-[var(--color-border)] bg-[var(--color-card)] p-6 shadow-2xl text-center">
            {/* Winner Icon */}
            <div className="mx-auto mb-3 flex h-16 w-16 items-center justify-center rounded-full bg-[var(--color-primary)]/20 text-3xl">
              {winner === Alignment.WOLF ? "🐺" : "🌿"}
            </div>

            <h2 className="font-display text-2xl font-bold text-[var(--color-text)]">
              {winner === Alignment.WOLF ? "狼人阵营获胜" : "好人阵营获胜"}
            </h2>

            <p className="mt-1 text-xs text-[var(--color-text-sub)]">
              历经 {day} 天对决，胜负已分。公开身份已揭示：
            </p>

            {/* Revealed Roles Grid */}
            <div className="mt-4 max-h-56 overflow-y-auto rounded-xl border border-[var(--color-border)]/60 bg-[var(--color-bg)]/60 p-3">
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                {players.map((p) => (
                  <div
                    key={p.seat}
                    className="flex items-center gap-2 rounded-lg border border-[var(--color-border)]/40 bg-[var(--color-card)] p-2 text-left text-xs"
                  >
                    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--color-primary)]/15 font-bold text-[var(--color-primary)]">
                      {p.seat}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-semibold text-[var(--color-text)]">{p.name}</p>
                      <p className="truncate text-[10px] text-[var(--color-text-sub)]">
                        {p.role ? roleNames[p.role] || p.role : "未知"}
                        <span className="ml-1 opacity-70">({p.alive ? "存活" : "出局"})</span>
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Action Buttons */}
            <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
              <Link
                href="/"
                className="rounded-button border border-[var(--color-border)] bg-[var(--color-bg)] px-4 py-2 text-xs font-semibold text-[var(--color-text)] hover:border-[var(--color-primary)]"
              >
                返回大厅
              </Link>
              {gameState?.id && (
                <Link
                  href={`/games/${gameState.id}/report`}
                  className="rounded-button bg-[var(--color-primary)] px-4 py-2 text-xs font-semibold text-[var(--color-on-primary)] hover:opacity-90"
                >
                  查看对局复盘
                </Link>
              )}
              <button
                type="button"
                onClick={controller.exportGameRecord}
                className="rounded-button border border-[var(--color-border)] px-4 py-2 text-xs font-medium text-[var(--color-text-sub)] hover:text-[var(--color-text)]"
              >
                导出记录
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
