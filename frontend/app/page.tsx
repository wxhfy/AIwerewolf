"use client";

import React, { useRef, useState, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { gsap } from "gsap";
import { useGSAP } from "@gsap/react";
import { useAppContext } from "@/context/AppContext";
import { Language, AgentType, PrepareSnapshot, RoomInfoRow, RoomRecord, ViewMode } from "@/types";
import { createRoom, prepareRoom } from "@/lib/gameApi";
import { t } from "@/lib/i18n";
import { AnimatedWerewolfBackground } from "@/components/game/AnimatedWerewolfBackground";
import { LobbyConfigCard } from "@/components/game/LobbyConfigCard";
import { PrepareModal } from "@/components/game/PrepareModal";
import { SettingsModal, GameSettings } from "@/components/SettingsModal";
import { BackgroundMusic } from "@/components/game/BackgroundMusic";

if (typeof window !== "undefined") {
  gsap.registerPlugin(useGSAP);
}

const defaultGameSettings: GameSettings = {
  viewMode: ViewMode.PUBLIC,
  language: Language.ZH,
  seed: Math.floor(Math.random() * 1000),
  modelProvider: "ark",
  modelName: "doubao-seed-2.0-pro",
  apiKey: "",
  baseUrl: "",
};

function normalizeGameSettings(raw: unknown): GameSettings {
  const data = raw && typeof raw === "object" ? raw as Partial<GameSettings> & { customApiKey?: string } : {};
  const viewMode = data.viewMode === ViewMode.MODERATOR ? ViewMode.MODERATOR : ViewMode.PUBLIC;
  const language = data.language === Language.EN ? Language.EN : Language.ZH;
  const seed = typeof data.seed === "number" && Number.isFinite(data.seed)
    ? Math.trunc(data.seed)
    : defaultGameSettings.seed;

  return {
    viewMode,
    language,
    seed,
    modelProvider: typeof data.modelProvider === "string" && data.modelProvider.trim() ? data.modelProvider : defaultGameSettings.modelProvider,
    modelName: typeof data.modelName === "string" && data.modelName.trim() ? data.modelName : defaultGameSettings.modelName,
    apiKey: typeof data.apiKey === "string" ? data.apiKey : typeof data.customApiKey === "string" ? data.customApiKey : "",
    baseUrl: typeof data.baseUrl === "string" ? data.baseUrl : "",
  };
}

export default function LobbyPage() {
  const router = useRouter();
  const pageRef = useRef<HTMLDivElement>(null);
  const { language, setLanguage, viewMode, setViewMode, agentType, setAgentType, setGameState, seed, setSeed } = useAppContext();

  // Settings state
  const [showSettings, setShowSettings] = useState(false);
  const [gameSettings, setGameSettings] = useState<GameSettings>(() => {
    let settings = defaultGameSettings;
    if (typeof window !== "undefined") {
      const saved = localStorage.getItem("gameSettings");
      if (saved) {
        try {
          settings = normalizeGameSettings(JSON.parse(saved));
        } catch {
          settings = defaultGameSettings;
        }
      }
      const langParam = new URLSearchParams(window.location.search).get("lang");
      if (langParam === Language.EN || langParam === Language.ZH) {
        settings = { ...settings, language: langParam };
      }
    }
    return settings;
  });

  useEffect(() => {
    if (agentType !== "llm") setAgentType("llm" as AgentType);
    // Sync language from settings
    if (gameSettings.language !== language) {
      setLanguage(gameSettings.language);
    }
    if (gameSettings.viewMode !== viewMode) {
      setViewMode(gameSettings.viewMode);
    }
    if (gameSettings.seed !== seed) {
      setSeed(gameSettings.seed);
    }
  }, [agentType, setAgentType, gameSettings.language, gameSettings.seed, gameSettings.viewMode, language, seed, setLanguage, setSeed, setViewMode, viewMode]);

  function persistGameSettings(newSettings: GameSettings) {
    setGameSettings(newSettings);
    if (typeof window !== "undefined") {
      localStorage.setItem("gameSettings", JSON.stringify(newSettings));
    }
  }

  const handleSaveSettings = (newSettings: GameSettings) => {
    persistGameSettings(newSettings);
    setLanguage(newSettings.language);
    setViewMode(newSettings.viewMode);
    setSeed(newSettings.seed);
  };

  const [playerCount, setPlayerCount] = useState(7);
  const [mode, setMode] = useState<"ai" | "human">("ai");
  const [humanSeat, setHumanSeat] = useState(1);
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState("");

  const [showModal, setShowModal] = useState(false);
  const [createdRoom, setCreatedRoom] = useState<RoomRecord | null>(null);
  const [prepareSnapshot, setPrepareSnapshot] = useState<PrepareSnapshot | null>(null);
  const [isStarting, setIsStarting] = useState(false);

  useGSAP(() => {
    const media = gsap.matchMedia();
    media.add("(prefers-reduced-motion: no-preference)", () => {
      const timeline = gsap.timeline({ defaults: { ease: "power2.out" } });
      timeline
        .from("[data-home-intro='moon']", { opacity: 0, y: -8, duration: 0.35 })
        .from("[data-home-intro='title']", { opacity: 0, y: 8, duration: 0.35 }, "-=0.2")
        .from("[data-home-intro='subtitle']", { opacity: 0, duration: 0.3 }, "-=0.22")
        .from("[data-home-intro='card']", { opacity: 0, scale: 0.98, y: 10, duration: 0.4 }, "-=0.2")
        .from("[data-home-intro='footer']", { opacity: 0, duration: 0.25 }, "-=0.2");
    });

    return () => media.revert();
  }, { scope: pageRef });

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
    <div ref={pageRef} className="relative min-h-screen flex flex-col items-center justify-start overflow-x-hidden overflow-y-auto bg-background px-4 pb-8 pt-24 sm:justify-center sm:px-6 sm:pt-20">
      <AnimatedWerewolfBackground />
      <BackgroundMusic language={language} />

      {/* ── Top nav ────────────────────────────────────────────── */}
      <div className="absolute left-3 right-16 top-4 z-20 flex flex-wrap items-center justify-end gap-2 sm:left-auto sm:right-16 sm:flex-nowrap">
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
      </div>

      {/* ── Brand — stable height, no jump on mode switch ────────── */}
      <div className="relative z-10 mb-5 shrink-0 text-center sm:mb-8">
        {/* Moon icon with glow */}
        <div data-home-intro="moon" className="relative mb-3 inline-block sm:mb-4">
          <div className="absolute inset-0 w-12 h-12 mx-auto rounded-full bg-primary/20 blur-xl animate-[pulse_3s_ease-in-out_infinite]" />
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" className="relative h-10 w-10 text-primary drop-shadow-[0_0_12px_rgba(183,131,63,0.4)] sm:h-12 sm:w-12">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
          </svg>
        </div>
        <h1 data-home-intro="title" className="font-display text-2xl font-bold text-primary tracking-tight sm:text-3xl" style={{ textShadow: "0 0 60px rgba(183,131,63,0.2)" }}>
          AI Werewolf
        </h1>
        <p data-home-intro="subtitle" className="mx-auto mt-1 max-w-xs text-sm leading-relaxed text-text-sub/60 sm:mt-2">
          {language === "zh" ? "黑夜降临，狼人出没。" : "Night falls. The wolves are among us."}
        </p>
      </div>

      {/* ── Config card ─────────────────────────────────────────── */}
      <div data-home-intro="card" className="relative z-10 w-full max-w-md">
        <LobbyConfigCard
          language={language} playerCount={playerCount} mode={mode} humanSeat={humanSeat}
          isCreating={isCreating} error={showModal ? "" : error}
          onPlayerCountChange={(nextCount) => { setPlayerCount(nextCount); if (humanSeat > nextCount) setHumanSeat(nextCount); }}
          onModeChange={setMode} onHumanSeatChange={setHumanSeat}
          onCreateRoom={handleCreateRoom}
        />
      </div>

      {/* ── Footer ──────────────────────────────────────────────── */}
      <p data-home-intro="footer" className="relative z-10 mt-6 text-xs text-text-sub/30">
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
