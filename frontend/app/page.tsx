"use client";

import React, { useState, useEffect, useRef, useMemo } from "react";
import { useAppContext } from "@/context/AppContext";
import { t, tPhase } from "@/lib/i18n";
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

  const isNight = useMemo(() => {
    const phase = gameState?.phase || "";
    return phase.startsWith("NIGHT") || phase === Phase.NIGHT_START || phase === Phase.NIGHT_RESOLVE;
  }, [gameState?.phase]);

  useEffect(() => {
    document.documentElement.setAttribute("data-phase", isNight ? "night" : "day");
  }, [isNight]);

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

  // Reference image: left sidebar = seats 1-4, right sidebar = seats 5-7
  const leftPlayers = useMemo(
    () => (gameState?.players || []).filter((p) => p.seat <= 4),
    [gameState?.players]
  );
  const rightPlayers = useMemo(
    () => (gameState?.players || []).filter((p) => p.seat > 4),
    [gameState?.players]
  );

  const aliveCount =
    gameState?.alive_count ||
    gameState?.players.filter((p) => p.alive).length ||
    0;

  const phaseName = gameState?.phase
    ? tPhase(gameState.phase, language)
    : "-";

  return (
    <div
      className="h-screen flex flex-col overflow-hidden"
      style={{
        background: "var(--color-bg)",
        transition: "background var(--transition-daynight) var(--ease-in-out)",
      }}
    >
      {/* Night overlay */}
      <div
        className="fixed inset-0 pointer-events-none z-0"
        style={{
          background: "var(--color-overlay)",
          transition: "background var(--transition-daynight) var(--ease-in-out)",
        }}
      />

      {/* ====== Top Header Bar ====== */}
      <header
        className="relative z-10 flex items-center gap-4 px-6 py-3 border-b flex-wrap"
        style={{
          background: "var(--color-card)",
          borderColor: "var(--color-border)",
          transition: "background var(--transition-daynight) var(--ease-in-out)",
        }}
      >
        {/* Left: Room/Game info */}
        <div className="flex items-center gap-3">
          <span className="font-display text-lg font-semibold text-primary">
            AI Werewolf
          </span>
          <span className="text-xs text-text-sub">
            {t("roomLabel", language)}: {room ? truncate(room.id, 8) : "-"}
          </span>
          <span className="text-xs text-text-sub">
            {t("gameLabel", language)}: {gameState ? truncate(gameState.id, 8) : "-"}
          </span>
        </div>

        {/* Center: Phase info */}
        <div className="flex items-center gap-2 mx-auto">
          <svg width="20" height="20" viewBox="0 0 24 24"
            fill="none" stroke="currentColor" strokeWidth="1.5"
            strokeLinecap="round" strokeLinejoin="round"
            className={isNight ? "text-primary" : "text-accent"}
          >
            {isNight ? (
              <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
            ) : (
              <>
                <circle cx="12" cy="12" r="5" />
                <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" />
              </>
            )}
          </svg>
          <span className="font-display text-sm font-semibold text-textPrimary">
            {gameState ? (
              language === "zh"
                ? `第${gameState.day}天 · ${phaseName}`
                : `Day ${gameState.day} · ${phaseName}`
            ) : t("statusReady", language)}
          </span>
          {gameState?.winner && (
            <Badge variant="warning">
              {gameState.winner === "village" ? t("village", language) : t("wolf", language)}
            </Badge>
          )}
        </div>

        {/* Right: Controls */}
        <div className="flex items-center gap-2 flex-wrap">
          {/* View mode */}
          <div className="flex rounded-button border border-border overflow-hidden">
            <button
              onClick={() => setViewMode(ViewMode.PUBLIC)}
              className={`px-2.5 py-1 text-xs font-medium transition-colors ${
                viewMode === ViewMode.PUBLIC
                  ? "bg-primary text-white" : "bg-transparent text-text-sub hover:text-textPrimary"
              }`}
            >
              {t("public", language)}
            </button>
            <button
              onClick={() => setViewMode(ViewMode.MODERATOR)}
              className={`px-2.5 py-1 text-xs font-medium transition-colors ${
                viewMode === ViewMode.MODERATOR
                  ? "bg-primary text-white" : "bg-transparent text-text-sub hover:text-textPrimary"
              }`}
            >
              {t("private", language)}
            </button>
          </div>

          {/* Agent type */}
          <select
            value={agentType}
            onChange={(e) => setAgentType(e.target.value === "llm" ? AgentType.LLM : AgentType.HEURISTIC)}
            disabled={isPlaying}
            className="h-8 px-2 rounded-button border border-border text-xs text-textPrimary disabled:opacity-50"
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
            className="h-8 w-16 px-1.5 rounded-button border border-border text-xs text-textPrimary disabled:opacity-50"
            style={{ background: "var(--color-bg)" }}
            title={t("seed", language)}
          />

          {/* Run button */}
          <Button onClick={runGame} disabled={isPlaying} size="sm"
            className={isPlaying ? "animate-pulse-loading" : ""}>
            {isPlaying ? t("statusStreaming", language) : t("run", language)}
          </Button>

          {/* Language */}
          <div className="flex rounded-button border border-border overflow-hidden">
            <button
              onClick={() => setLanguage(Language.ZH)}
              className={`px-2 py-1 text-xs font-medium transition-colors ${
                language === "zh" ? "bg-primary text-white" : "bg-transparent text-text-sub hover:text-textPrimary"
              }`}
            >
              中
            </button>
            <button
              onClick={() => setLanguage(Language.EN)}
              className={`px-2 py-1 text-xs font-medium transition-colors ${
                language === "en" ? "bg-primary text-white" : "bg-transparent text-text-sub hover:text-textPrimary"
              }`}
            >
              EN
            </button>
          </div>
        </div>
      </header>

      {/* ====== Main Content: Three Columns ====== */}
      <div className="flex-1 flex relative z-10 overflow-hidden">
        {/* Left sidebar — Players 1-4 */}
        <aside
          className="hidden lg:flex flex-col gap-3 p-4 w-[22%] min-w-[140px] max-w-[220px] overflow-y-auto"
          style={{
            borderRight: `1px solid var(--color-border)`,
            transition: "border-color var(--transition-daynight) var(--ease-in-out)",
          }}
        >
          {(leftPlayers.length > 0 ? leftPlayers : placeholderPlayers(1, 4)).map((player, i) => (
            <PlayerCard
              key={player.id || `lp-${i}`}
              player={player}
              isSpeaking={false}
            />
          ))}
        </aside>

        {/* Center — Event Timeline */}
        <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
          {/* Status bar */}
          <div
            className="px-5 py-2 border-b text-xs text-text-sub"
            style={{
              background: "var(--color-card)",
              borderColor: "var(--color-border)",
              transition: "background var(--transition-daynight) var(--ease-in-out)",
            }}
          >
            {statusTitle}
            {" · "}
            {t("aliveCount", language)}: {aliveCount > 0 ? `${aliveCount} / ${gameState?.players.length || 0}` : "-"}
            {" · "}
            {t("events", language)}: {gameState?.event_count || 0}
            {gameState?.winner && (
              <>
                {" · "}
                {t("winner", language)}: {gameState.winner === "village" ? t("village", language) : t("wolf", language)}
              </>
            )}
          </div>

          {/* Timeline content */}
          <div className="flex-1 overflow-y-auto px-5 py-4">
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
              <div className="flex flex-col items-center justify-center h-full text-center py-20">
                {/* Moon icon */}
                <svg
                  width="56" height="56" viewBox="0 0 24 24"
                  fill="none" stroke="currentColor" strokeWidth="1"
                  strokeLinecap="round" strokeLinejoin="round"
                  className="text-text-sub/25 mb-6"
                  aria-hidden="true"
                >
                  <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
                </svg>
                <p className="font-display text-xl text-textPrimary mb-3">
                  {t("readyHint", language)}
                </p>
                <p className="text-sm text-text-sub max-w-xs leading-relaxed">
                  {t("statusHint", language)}
                </p>
              </div>
            )}
          </div>
        </main>

        {/* Right sidebar — Players 5-7 */}
        <aside
          className="hidden lg:flex flex-col gap-3 p-4 w-[15%] min-w-[120px] max-w-[180px] overflow-y-auto"
          style={{
            borderLeft: `1px solid var(--color-border)`,
            transition: "border-color var(--transition-daynight) var(--ease-in-out)",
          }}
        >
          {(rightPlayers.length > 0 ? rightPlayers : placeholderPlayers(5, 7)).map((player, i) => (
            <PlayerCard
              key={player.id || `rp-${i}`}
              player={player}
              isSpeaking={false}
            />
          ))}
        </aside>
      </div>

      {/* Mobile players */}
      <div className="lg:hidden relative z-10">
        <div className="flex gap-2 overflow-x-auto px-4 py-3">
          {((gameState?.players.length || 0) > 0 ? gameState!.players : placeholderPlayers(1, 7)).map((player, i) => (
            <div key={player.id || `mp-${i}`} className="flex-shrink-0 w-[110px]">
              <PlayerCard player={player} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/** Generate placeholder players for empty state display */
function placeholderPlayers(from: number, to: number) {
  const list = [];
  for (let seat = from; seat <= to; seat++) {
    list.push({
      id: `placeholder-${seat}`,
      seat,
      name: `玩家 ${seat}`,
      alive: true,
      is_ai: true,
    } as any);
  }
  return list;
}
