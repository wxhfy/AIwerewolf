"use client";

import React, { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAppContext } from "@/context/AppContext";
import { Language, AgentType, PrepareSnapshot, RoomInfoRow, RoomRecord } from "@/types";
import { createRoom, prepareRoom } from "@/lib/gameApi";
import { t } from "@/lib/i18n";
import { LobbyConfigCard } from "@/components/game/LobbyConfigCard";
import { PrepareModal } from "@/components/game/PrepareModal";

export default function LobbyPage() {
  const router = useRouter();
  const { language, setLanguage, agentType, setAgentType, setGameState } = useAppContext();

  // Force LLM as the only public agent type. The user wants every game to be
  // LLM-driven; the heuristic agent stays in the codebase but only as the
  // automatic fallback inside LLMAgent (triggered after 3 LLM retries fail).
  useEffect(() => {
    if (agentType !== "llm") setAgentType("llm" as AgentType);
  }, [agentType, setAgentType]);

  const [playerCount, setPlayerCount] = useState(7);
  const [mode, setMode] = useState<"ai" | "human">("ai");
  const [humanSeat, setHumanSeat] = useState(1);
  const [seed, setSeed] = useState(Math.floor(Math.random() * 1000));
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState("");

  // Modal state
  const [showModal, setShowModal] = useState(false);
  const [createdRoom, setCreatedRoom] = useState<RoomRecord | null>(null);
  // Snapshot returned by /api/rooms/{id}/prepare — populated for AI mode at
  // create time so the confirm modal can show the assigned roles + personas
  // before the user clicks "确认开始". For human mode it stays null and the
  // modal falls back to the seat-only layout.
  const [prepareSnapshot, setPrepareSnapshot] = useState<PrepareSnapshot | null>(null);
  const [isStarting, setIsStarting] = useState(false);

  // Step 1: Create room → (AI) call /prepare so the modal can show real roles
  // → show modal. We hardcode agent_type="llm" instead of reading from
  // context: the lobby toggle is gone and the underlying agentType state may
  // still be HEURISTIC for a tick on first paint before the useEffect above
  // settles it.
  function getErrorMessage(error: unknown, fallback: string) {
    return error instanceof Error && error.message === "requestTimeout" ? t("requestTimeout", language) : error instanceof Error ? error.message : fallback;
  }

  async function handleCreateRoom() {
    setIsCreating(true);
    setError("");
    setPrepareSnapshot(null);
    try {
      const room = await createRoom({
        seed,
        playerCount,
        agentType: AgentType.LLM,
        mode,
        humanSeat,
      });
      setCreatedRoom(room);
      if (mode === "ai") setPrepareSnapshot(await prepareRoom(room.id));
      setShowModal(true);
    } catch (e) {
      setError(getErrorMessage(e, "创建房间失败"));
    } finally {
      setIsCreating(false);
    }
  }

  // Step 2: Confirm → for human mode call /start (needs first human turn
  // ready); for AI-vs-AI we already have the prepared snapshot from step 1,
  // just plant it into context and navigate. The play page sees gameState
  // populated and auto-opens the WebSocket which streams the live game.
  const roomInfoRows: RoomInfoRow[] = createdRoom ? [
    { label: t("room", language), value: `${createdRoom.id.slice(0, 8)}...` },
    { label: t("gameMode", language), value: mode === "human" ? t("humanPlay", language) : t("aiVsAi", language) },
    { label: t("players", language), value: String(playerCount) },
    { label: t("agent", language), value: t("agentLlm", language) },
    ...(mode === "human" ? [{ label: t("yourSeat", language), value: `${t("seat", language)} ${humanSeat}` }] : []),
  ] : [];

  async function handleConfirmStart() {
    if (!createdRoom) return;
    setIsStarting(true);
    setError("");
    try {
      setGameState(prepareSnapshot ?? await prepareRoom(createdRoom.id));
      router.push(`/room/${createdRoom.id}/play?human_seat=${humanSeat}&mode=${mode}`);
    } catch (e) {
      setError(getErrorMessage(e, "启动失败"));
      setIsStarting(false);
    }
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-background px-4 transition-colors duration-500">
      {/* Language toggle */}
      <div className="absolute top-4 right-4 flex overflow-hidden rounded-button border border-border">
        <button onClick={() => setLanguage(Language.ZH)}
          className={`px-3 py-1.5 text-xs font-medium ${language === "zh" ? "bg-primary text-white" : "bg-transparent text-text-sub"}`}>中文</button>
        <button onClick={() => setLanguage(Language.EN)}
          className={`px-3 py-1.5 text-xs font-medium ${language === "en" ? "bg-primary text-white" : "bg-transparent text-text-sub"}`}>EN</button>
      </div>

      {/* Brand */}
      <div className="text-center mb-10">
        <svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1"
          strokeLinecap="round" strokeLinejoin="round" className="mx-auto mb-4 text-primary">
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
        </svg>
        <h1 className="font-display text-3xl font-bold text-primary">AI Werewolf</h1>
        <p className="mt-2 text-text-sub text-sm max-w-xs mx-auto">
          {t("configureGameDescription", language)}
        </p>
      </div>

      <LobbyConfigCard
        language={language}
        playerCount={playerCount}
        mode={mode}
        humanSeat={humanSeat}
        seed={seed}
        isCreating={isCreating}
        error={showModal ? "" : error}
        onPlayerCountChange={(nextCount) => { setPlayerCount(nextCount); if (humanSeat > nextCount) setHumanSeat(nextCount); }}
        onModeChange={setMode}
        onHumanSeatChange={setHumanSeat}
        onSeedChange={setSeed}
        onCreateRoom={handleCreateRoom}
      />

      <p className="mt-8 text-xs text-text-sub">
        <span className="font-display">AI Werewolf</span><span className="mx-2">·</span>
        <span>{t("spectateAndPlay", language)}</span>
      </p>

      {showModal && createdRoom && (
        <PrepareModal
          language={language}
          roomInfoRows={roomInfoRows}
          mode={mode}
          prepareSnapshot={prepareSnapshot}
          playerCount={playerCount}
          humanSeat={humanSeat}
          error={error}
          isStarting={isStarting}
          onClose={() => { setShowModal(false); setError(""); }}
          onConfirm={handleConfirmStart}
        />
      )}
    </div>
  );
}
