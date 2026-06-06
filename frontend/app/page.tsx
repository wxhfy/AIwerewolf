"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAppContext } from "@/context/AppContext";
import { Language, AgentType, PrepareSnapshot, RoomInfoRow, RoomRecord } from "@/types";
import { createRoom, prepareRoom } from "@/lib/gameApi";
import { t } from "@/lib/i18n";
import { LobbyConfigCard } from "@/components/game/LobbyConfigCard";
import { PrepareModal } from "@/components/game/PrepareModal";
import { SettingsModal, GameSettings } from "@/components/SettingsModal";

export default function LobbyPage() {
  const router = useRouter();
  const { language, setLanguage, agentType, setAgentType, setGameState } = useAppContext();

  // Settings state
  const [showSettings, setShowSettings] = useState(false);
  const [gameSettings, setGameSettings] = useState<GameSettings>(() => {
    if (typeof window !== "undefined") {
      const saved = localStorage.getItem("gameSettings");
      if (saved) {
        try {
          return JSON.parse(saved);
        } catch {}
      }
    }
    return { viewMode: "public", language: Language.ZH, customApiKey: "" };
  });

  useEffect(() => {
    if (agentType !== "llm") setAgentType("llm" as AgentType);
    // Sync language from settings
    if (gameSettings.language !== language) {
      setLanguage(gameSettings.language);
    }
  }, [agentType, setAgentType, gameSettings.language, language, setLanguage]);

  const handleSaveSettings = (newSettings: GameSettings) => {
    setGameSettings(newSettings);
    setLanguage(newSettings.language);
    if (typeof window !== "undefined") {
      localStorage.setItem("gameSettings", JSON.stringify(newSettings));
    }
  };

  const [playerCount, setPlayerCount] = useState(7);
  const [mode, setMode] = useState<"ai" | "human">("ai");
  const [humanSeat, setHumanSeat] = useState(1);
  const [seed, setSeed] = useState(Math.floor(Math.random() * 1000));
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState("");

  const [showModal, setShowModal] = useState(false);
  const [createdRoom, setCreatedRoom] = useState<RoomRecord | null>(null);
  const [prepareSnapshot, setPrepareSnapshot] = useState<PrepareSnapshot | null>(null);
  const [isStarting, setIsStarting] = useState(false);

  function getErrorMessage(error: unknown, fallback: string) {
    return error instanceof Error && error.message === "requestTimeout" ? t("requestTimeout", language) : error instanceof Error ? error.message : fallback;
  }

  async function handleCreateRoom() {
    setIsCreating(true); setError(""); setPrepareSnapshot(null);
    try {
      const room = await createRoom({ seed, playerCount, agentType: AgentType.LLM, mode, humanSeat });
      setCreatedRoom(room);
      if (mode === "ai") setPrepareSnapshot(await prepareRoom(room.id));
      setShowModal(true);
    } catch (e) { setError(getErrorMessage(e, "创建房间失败")); }
    finally { setIsCreating(false); }
  }

  const roomInfoRows: RoomInfoRow[] = createdRoom ? [
    { label: t("room", language), value: `${createdRoom.id.slice(0, 8)}...` },
    { label: t("gameMode", language), value: mode === "human" ? t("humanPlay", language) : t("aiVsAi", language) },
    { label: t("players", language), value: String(playerCount) },
    { label: t("agent", language), value: t("agentLlm", language) },
    ...(mode === "human" ? [{ label: t("yourSeat", language), value: `${t("seat", language)} ${humanSeat}` }] : []),
  ] : [];

  async function handleConfirmStart() {
    if (!createdRoom) return;
    setIsStarting(true); setError("");
    try {
      setGameState(prepareSnapshot ?? await prepareRoom(createdRoom.id));
      const gamePath = mode === "human"
        ? `/room/${createdRoom.id}/human?human_seat=${humanSeat}&mode=human`
        : `/room/${createdRoom.id}/play?mode=ai`;
      router.push(gamePath);
    } catch (e) { setError(getErrorMessage(e, "启动失败")); setIsStarting(false); }
  }

  return (
    <div className="relative min-h-screen flex flex-col items-center justify-center overflow-hidden bg-background">
      {/* ── Atmospheric background ────────────────────────────── */}
      <div className="absolute inset-0 pointer-events-none overflow-hidden">
        {/* Moon glow */}
        <div className="absolute -top-32 left-1/2 -translate-x-1/2 w-[600px] h-[600px] rounded-full bg-[radial-gradient(circle,_rgba(183,131,63,0.12)_0%,_transparent_60%)]" />
        {/* Subtle fog layers */}
        <div className="absolute bottom-0 left-0 right-0 h-64 bg-gradient-to-t from-black/20 to-transparent" />
        {/* Star particles */}
        <div className="absolute inset-0" style={{ backgroundImage: "radial-gradient(1px 1px at 20% 30%, rgba(255,255,255,0.15), transparent), radial-gradient(1px 1px at 60% 20%, rgba(255,255,255,0.1), transparent), radial-gradient(1px 1px at 40% 60%, rgba(255,255,255,0.12), transparent), radial-gradient(1px 1px at 80% 70%, rgba(255,255,255,0.08), transparent), radial-gradient(1.5px 1.5px at 15% 80%, rgba(255,255,255,0.15), transparent)" }} />
      </div>

      {/* ── Top nav ────────────────────────────────────────────── */}
      <div className="absolute top-4 right-4 z-20 flex items-center gap-2">
        <Link href="/personas" className="px-3 py-1.5 text-xs font-medium rounded-button border border-border/40 text-text-sub/70 hover:text-primary hover:border-primary/50 transition-colors backdrop-blur-sm">
          {language === "zh" ? "角色库" : "Personas"}
        </Link>
        <Link href="/evolution" className="px-3 py-1.5 text-xs font-medium rounded-button border border-border/40 text-text-sub/70 hover:text-primary hover:border-primary/50 transition-colors backdrop-blur-sm">
          {language === "zh" ? "进化看板" : "Evolution"}
        </Link>
        <button
          onClick={() => setShowSettings(true)}
          className="px-3 py-1.5 text-xs font-medium rounded-button border border-border/40 text-text-sub/70 hover:text-primary hover:border-primary/50 transition-colors backdrop-blur-sm flex items-center gap-1.5"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="3" />
            <path d="M12 1v6m0 6v6m-5.196-13.804l4.243 4.243m0 6.122l4.243 4.243M1 12h6m6 0h6m-13.804 5.196l4.243-4.243m0-6.122l4.243-4.243" />
          </svg>
          {language === "zh" ? "设置" : "Settings"}
        </button>
        <div className="flex overflow-hidden rounded-button border border-border/40 backdrop-blur-sm">
          <button onClick={() => setLanguage(Language.ZH)} className={`px-3 py-1.5 text-xs font-medium transition-colors ${language === "zh" ? "bg-primary text-white" : "bg-transparent text-text-sub/70 hover:text-textPrimary"}`}>中文</button>
          <button onClick={() => setLanguage(Language.EN)} className={`px-3 py-1.5 text-xs font-medium transition-colors ${language === "en" ? "bg-primary text-white" : "bg-transparent text-text-sub/70 hover:text-textPrimary"}`}>EN</button>
        </div>
      </div>

      {/* ── Brand — stable height, no jump on mode switch ────────── */}
      <div className="relative z-10 text-center mb-8 shrink-0">
        {/* Moon icon with glow */}
        <div className="relative inline-block mb-4">
          <div className="absolute inset-0 w-12 h-12 mx-auto rounded-full bg-primary/20 blur-xl animate-[pulse_3s_ease-in-out_infinite]" />
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" className="relative text-primary drop-shadow-[0_0_12px_rgba(183,131,63,0.4)]">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
          </svg>
        </div>
        <h1 className="font-display text-3xl font-bold text-primary tracking-tight" style={{ textShadow: "0 0 60px rgba(183,131,63,0.2)" }}>
          AI Werewolf
        </h1>
        <p className="mt-2 text-text-sub/60 text-sm max-w-xs mx-auto leading-relaxed">
          {language === "zh" ? "黑夜降临，狼人出没。" : "Night falls. The wolves are among us."}
        </p>
      </div>

      {/* ── Config card ─────────────────────────────────────────── */}
      <div className="relative z-10 w-full max-w-md">
        <LobbyConfigCard
          language={language} playerCount={playerCount} mode={mode} humanSeat={humanSeat}
          seed={seed} isCreating={isCreating} error={showModal ? "" : error}
          onPlayerCountChange={(nextCount) => { setPlayerCount(nextCount); if (humanSeat > nextCount) setHumanSeat(nextCount); }}
          onModeChange={setMode} onHumanSeatChange={setHumanSeat} onSeedChange={setSeed}
          onCreateRoom={handleCreateRoom}
        />
      </div>

      {/* ── Footer ──────────────────────────────────────────────── */}
      <p className="relative z-10 mt-6 text-xs text-text-sub/30">
        <span className="font-display">AI Werewolf</span>
        <span className="mx-2">·</span>
        <span>{t("spectateAndPlay", language)}</span>
      </p>

      {/* ── Prepare modal ───────────────────────────────────────── */}
      {showModal && createdRoom && (
        <PrepareModal
          language={language} roomInfoRows={roomInfoRows} mode={mode}
          prepareSnapshot={prepareSnapshot} playerCount={playerCount} humanSeat={humanSeat}
          error={error} isStarting={isStarting}
          onClose={() => { setShowModal(false); setError(""); }}
          onConfirm={handleConfirmStart}
        />
      )}

      {/* ── Settings modal ──────────────────────────────────────── */}
      <SettingsModal
        isOpen={showSettings}
        onClose={() => setShowSettings(false)}
        currentSettings={gameSettings}
        onSave={handleSaveSettings}
      />
    </div>
  );
}
