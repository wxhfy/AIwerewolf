"use client";

import React, { useState, useEffect, useRef, useMemo } from "react";
import { useAppContext } from "@/context/AppContext";
import { t } from "@/lib/i18n";
import { truncate } from "@/lib/utils";
import {
  WebSocketMessage,
  WebSocketRequest,
  Language,
  AgentType,
  ViewMode,
  Phase,
} from "@/types";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { PhaseBanner } from "@/components/game/PhaseBanner";
import { PlayerCard } from "@/components/game/PlayerCard";
import { DayBlock } from "@/components/game/DayBlock";

export default function SpectatorPage() {
  const {
    language,
    setLanguage,
    viewMode,
    setViewMode,
    agentType,
    setAgentType,
    room,
    setRoom,
    gameState,
    setGameState,
    isPlaying,
    setIsPlaying,
    speed,
    setSpeed,
    seed,
    setSeed,
  } = useAppContext();

  const [statusTitle, setStatusTitle] = useState(t("statusReady", language));
  const wsRef = useRef<WebSocket | null>(null);

  // Detect night phase for CSS attribute
  const isNight = useMemo(() => {
    const phase = gameState?.phase || "";
    return phase.startsWith("NIGHT") || phase === Phase.NIGHT_START || phase === Phase.NIGHT_RESOLVE;
  }, [gameState?.phase]);

  // Apply data-phase to document for CSS variables
  useEffect(() => {
    document.documentElement.setAttribute("data-phase", isNight ? "night" : "day");
  }, [isNight]);

  // Create room
  async function createRoom() {
    try {
      setStatusTitle(t("statusLoading", language));
      const response = await fetch(
        `/api/rooms?name=Demo+Room&seed=${seed}&player_count=7&agent_type=${agentType}`,
        { method: "POST", headers: { Accept: "application/json" } }
      );
      if (!response.ok) throw new Error(`Failed to create room: ${response.status}`);
      const roomData = await response.json();
      setRoom(roomData);
      setStatusTitle(t("roomReady", language));
    } catch (error) {
      console.error("Failed to create room:", error);
      setStatusTitle(t("statusError", language));
    }
  }

  // Run game via WebSocket
  function runGame() {
    if (!room) {
      createRoom().then(() => setTimeout(runGame, 100));
      return;
    }
    if (wsRef.current) wsRef.current.close();
    setIsPlaying(true);
    setStatusTitle(t("statusStreaming", language));
    setGameState(null);

    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${window.location.host}/ws/rooms/${room.id}`);
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(
        JSON.stringify({
          action: "start",
          seed,
          agent_type: agentType,
          show_private: viewMode === ViewMode.MODERATOR,
          delay_ms: speed,
        } as WebSocketRequest)
      );
    };

    ws.onmessage = (event) => {
      const msg: WebSocketMessage = JSON.parse(event.data);
      if (msg.type === "room" && msg.room) setRoom(msg.room);
      if (msg.type === "snapshot" && msg.state) setGameState(msg.state);
      if (msg.type === "complete") {
        if (msg.state) setGameState(msg.state);
        if (msg.room) setRoom(msg.room);
        setIsPlaying(false);
        setStatusTitle(t("statusLoaded", language));
      }
      if (msg.type === "error") {
        console.error("WS error:", msg.message);
        setIsPlaying(false);
        setStatusTitle(t("statusError", language));
      }
    };

    ws.onerror = () => { setIsPlaying(false); setStatusTitle(t("statusError", language)); };
    ws.onclose = () => setIsPlaying(false);
  }

  // Restore room from URL
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const roomId = params.get("room");
    if (roomId && !room) {
      fetch(`/api/rooms/${roomId}`, { headers: { Accept: "application/json" } })
        .then((res) => (res.ok ? res.json() : null))
        .then((data) => { if (data) setRoom(data); })
        .catch(() => {});
    }
  }, []);

  // Group events by day
  const dayBlocks = useMemo(() => {
    if (!gameState?.events) return {};
    const blocks: Record<number, typeof gameState.events> = {};
    for (const event of gameState.events) {
      const d = event.day || 0;
      if (!blocks[d]) blocks[d] = [];
      blocks[d].push(event);
    }
    return blocks;
  }, [gameState?.events]);

  // Split players: seats 1-3 left, 4-6 right
  const leftPlayers = useMemo(
    () => (gameState?.players || []).filter((p) => p.seat <= 3),
    [gameState?.players]
  );
  const rightPlayers = useMemo(
    () => (gameState?.players || []).filter((p) => p.seat > 3),
    [gameState?.players]
  );

  const aliveCount =
    gameState?.alive_count ||
    gameState?.players.filter((p) => p.alive).length ||
    0;

  return (
    <div className="min-h-screen" style={{ background: "var(--color-bg)", transition: "background var(--transition-daynight) var(--ease-in-out)" }}>
      {/* Night overlay */}
      <div
        className="fixed inset-0 pointer-events-none z-0"
        style={{
          background: "var(--color-overlay)",
          transition: "background var(--transition-daynight) var(--ease-in-out)",
        }}
      />

      <div className="relative z-10 max-w-screen-2xl mx-auto px-4 md:px-6 lg:px-8 py-6">
        {/* === Phase Banner === */}
        <PhaseBanner
          day={gameState?.day || 0}
          phase={gameState?.phase || "SETUP"}
          isNight={isNight}
        />

        {/* === Info badges row === */}
        <div className="flex flex-wrap items-center justify-center gap-2 mb-6 -mt-2">
          <Badge variant="default">
            {t("roomLabel", language)}: {room ? truncate(room.id) : "-"}
          </Badge>
          <Badge variant="default">
            {t("gameLabel", language)}: {gameState ? truncate(gameState.id) : "-"}
          </Badge>
          <Badge variant={viewMode === "moderator" ? "warning" : "default"}>
            {viewMode === "moderator" ? t("private", language) : t("publicMode", language)}
          </Badge>
          <Badge variant="default">
            {t("aliveCount", language)}: {aliveCount} / {gameState?.players.length || 0}
          </Badge>
          {gameState?.winner && (
            <Badge variant="warning">
              {t("winner", language)}:{" "}
              {gameState.winner === "village" ? t("village", language) : t("wolf", language)}
            </Badge>
          )}
        </div>

        {/* === Main Three-Column Layout === */}
        <div className="flex flex-col lg:flex-row gap-6">
          {/* Left column — Players 1-3 */}
          <aside className="hidden lg:flex flex-col gap-3 w-full lg:w-[20%] min-w-[140px]">
            {leftPlayers.length > 0 ? (
              leftPlayers.map((player) => (
                <PlayerCard key={player.id} player={player} />
              ))
            ) : (
              <div className="flex-1 flex items-center justify-center">
                <p className="text-xs text-text-sub/40 italic text-center">
                  {t("players", language)}<br/>1–3
                </p>
              </div>
            )}
          </aside>

          {/* Center column — Controls + Timeline */}
          <main className="flex-1 lg:w-[60%] space-y-6">
            {/* Control Panel */}
            <div
              className="rounded-card p-4 md:p-6 space-y-4"
              style={{
                background: "var(--color-card)",
                border: "1px solid var(--color-border)",
                transition: "background var(--transition-daynight) var(--ease-in-out), border var(--transition-daynight) var(--ease-in-out)",
              }}
            >
              <div className="flex flex-wrap items-center gap-3">
                {/* Run button */}
                <Button
                  onClick={runGame}
                  disabled={isPlaying}
                  className={isPlaying ? "animate-pulse-loading" : ""}
                >
                  {isPlaying ? t("statusStreaming", language) : t("run", language)}
                </Button>

                {/* Language */}
                <div className="flex rounded-button border border-border overflow-hidden">
                  <button
                    onClick={() => setLanguage(Language.ZH)}
                    className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                      language === "zh" ? "bg-primary text-white" : "bg-transparent text-textSecondary hover:text-textPrimary"
                    }`}
                  >
                    中文
                  </button>
                  <button
                    onClick={() => setLanguage(Language.EN)}
                    className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                      language === "en" ? "bg-primary text-white" : "bg-transparent text-textSecondary hover:text-textPrimary"
                    }`}
                  >
                    EN
                  </button>
                </div>

                {/* Agent type */}
                <select
                  value={agentType}
                  onChange={(e) => setAgentType(e.target.value === "llm" ? AgentType.LLM : AgentType.HEURISTIC)}
                  disabled={isPlaying}
                  className="h-9 px-3 rounded-button border border-border text-sm text-textPrimary disabled:opacity-50"
                  style={{ background: "var(--color-bg)" }}
                >
                  <option value="heuristic">{t("agentHeuristic", language)}</option>
                  <option value="llm">{t("agentLlm", language)}</option>
                </select>

                {/* Seed */}
                <input
                  type="number"
                  value={seed}
                  onChange={(e) => setSeed(parseInt(e.target.value) || 7)}
                  disabled={isPlaying}
                  className="h-9 w-20 px-2 rounded-button border border-border text-sm text-textPrimary disabled:opacity-50"
                  style={{ background: "var(--color-bg)" }}
                  title={t("seed", language)}
                />

                {/* Speed */}
                <input
                  type="number"
                  value={speed}
                  onChange={(e) => setSpeed(parseInt(e.target.value) || 80)}
                  disabled={isPlaying}
                  className="h-9 w-20 px-2 rounded-button border border-border text-sm text-textPrimary disabled:opacity-50"
                  style={{ background: "var(--color-bg)" }}
                  title={t("speed", language)}
                />

                {/* View toggle */}
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() =>
                    setViewMode(viewMode === ViewMode.MODERATOR ? ViewMode.PUBLIC : ViewMode.MODERATOR)
                  }
                  disabled={isPlaying}
                >
                  {viewMode === ViewMode.MODERATOR ? t("public", language) : t("private", language)}
                </Button>
              </div>

              {/* Status */}
              {statusTitle && (
                <p className="text-xs text-textSecondary">
                  <span className="font-medium">{statusTitle}</span>
                </p>
              )}
            </div>

            {/* Mobile players */}
            <div className="lg:hidden">
              <div className="flex gap-2 overflow-x-auto pb-2">
                {(gameState?.players || []).map((player) => (
                  <div key={player.id} className="flex-shrink-0 w-[120px]">
                    <PlayerCard player={player} />
                  </div>
                ))}
              </div>
            </div>

            {/* Event Timeline */}
            <div
              className="rounded-card p-4 md:p-6"
              style={{
                background: "var(--color-card)",
                border: "1px solid var(--color-border)",
                transition: "background var(--transition-daynight) var(--ease-in-out), border var(--transition-daynight) var(--ease-in-out)",
              }}
            >
              <h2 className="font-display text-lg font-semibold text-textPrimary mb-4">
                {t("timeline", language)}
              </h2>
              <div className="max-h-[55vh] overflow-y-auto">
                {gameState?.events.length ? (
                  Object.keys(dayBlocks)
                    .sort((a, b) => Number(b) - Number(a))
                    .map((dayKey) => (
                      <DayBlock
                        key={dayKey}
                        day={Number(dayKey)}
                        events={dayBlocks[Number(dayKey)]}
                      />
                    ))
                ) : (
                  <div className="text-center py-16 text-text-sub">
                    {/* Decorative moon SVG */}
                    <svg
                      width="48" height="48" viewBox="0 0 24 24"
                      fill="none" stroke="currentColor" strokeWidth="1"
                      strokeLinecap="round" strokeLinejoin="round"
                      className="mx-auto mb-5 opacity-30"
                      aria-hidden="true"
                    >
                      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
                    </svg>
                    <p className="font-display text-xl text-textPrimary mb-2">
                      {t("readyHint", language)}
                    </p>
                    <p className="text-sm max-w-xs mx-auto leading-relaxed">
                      {t("statusHint", language)}
                    </p>
                  </div>
                )}
              </div>
            </div>
          </main>

          {/* Right column — Players 4-6 */}
          <aside className="hidden lg:flex flex-col gap-3 w-full lg:w-[20%] min-w-[140px]">
            {rightPlayers.length > 0 ? (
              rightPlayers.map((player) => (
                <PlayerCard key={player.id} player={player} />
              ))
            ) : (
              <div className="flex-1 flex items-center justify-center">
                <p className="text-xs text-text-sub/40 italic text-center">
                  {t("players", language)}<br/>4–6
                </p>
              </div>
            )}
          </aside>
        </div>

        {/* Footer */}
        <footer className="mt-8 text-center text-xs text-textSecondary">
          <span className="font-display">AI Werewolf</span>
          <span className="mx-2">·</span>
          <span>{t("streamingLabel", language)}</span>
        </footer>
      </div>
    </div>
  );
}
