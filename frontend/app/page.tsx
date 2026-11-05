"use client";

import React, { useRef, useState, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { gsap } from "gsap";
import { useGSAP } from "@gsap/react";
import { useAppContext } from "@/context/AppContext";
import { Language, AgentType, PrepareSnapshot, RoomInfoRow, RoomLlmConfig, RoomRecord, ViewMode } from "@/types";
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
  viewMode: ViewMode.MODERATOR,
  language: Language.ZH,
  seed: Math.floor(Math.random() * 1000),
  modelProvider: "anthropic",
  modelName: "deepseek-v4-flash",
  apiKey: "",
  baseUrl: "https://api.deepseek.com/anthropic",
  apiFormat: "anthropic_messages",
  authEnvVar: "ANTHROPIC_AUTH_TOKEN",
};

function normalizeGameSettings(raw: unknown): GameSettings {
  const data = raw && typeof raw === "object" ? raw as Partial<GameSettings> & { customApiKey?: string } : {};
  const viewMode = ViewMode.MODERATOR;
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
    baseUrl: typeof data.baseUrl === "string" && data.baseUrl.trim() ? data.baseUrl.replace(/\/+$/, "") : defaultGameSettings.baseUrl,
    apiFormat: typeof data.apiFormat === "string" && data.apiFormat.trim() ? data.apiFormat : defaultGameSettings.apiFormat,
    authEnvVar: typeof data.authEnvVar === "string" && data.authEnvVar.trim() ? data.authEnvVar : defaultGameSettings.authEnvVar,
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
    if (viewMode !== ViewMode.MODERATOR) {
      setViewMode(ViewMode.MODERATOR);
    }
    if (gameSettings.seed !== seed) {
      setSeed(gameSettings.seed);
    }
  }, [agentType, setAgentType, gameSettings.language, gameSettings.seed, language, seed, setLanguage, setSeed, setViewMode, viewMode]);

  function persistGameSettings(newSettings: GameSettings) {
    setGameSettings(newSettings);
    if (typeof window !== "undefined") {
      localStorage.setItem("gameSettings", JSON.stringify(newSettings));
    }
  }

  const handleSaveSettings = (newSettings: GameSettings) => {
    const normalizedSettings = normalizeGameSettings(newSettings);
    persistGameSettings(normalizedSettings);
    setLanguage(normalizedSettings.language);
    setViewMode(ViewMode.MODERATOR);
    setSeed(normalizedSettings.seed);
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
        .from("[data-home-intro='moon']", { opacity: 0, y: -4, duration: 0.2 })
        .from("[data-home-intro='title']", { opacity: 0, y: 4, duration: 0.2 }, "-=0.15")
        .from("[data-home-intro='subtitle']", { opacity: 0, duration: 0.2 }, "-=0.15")
        .from("[data-home-intro='card']", { opacity: 0, y: 6, duration: 0.25 }, "-=0.15")
        .from("[data-home-intro='footer']", { opacity: 0, duration: 0.2 }, "-=0.15");
    });

    return () => media.revert();
  }, { scope: pageRef });

  function getErrorMessage(error: unknown, fallback: string) {
    return error instanceof Error && error.message === "requestTimeout" ? t("requestTimeout", language) : error instanceof Error ? error.message : fallback;
  }

  function buildRoomLlmConfig(settings: GameSettings): RoomLlmConfig | undefined {
    const config: RoomLlmConfig = {};
    const provider = settings.modelProvider.trim();
    const model = settings.modelName.trim();
    const baseUrl = settings.baseUrl.trim().replace(/\/+$/, "");
    if (!provider && !model && !baseUrl) return undefined;
    if (provider) config.provider = provider;
    if (model) config.model = model;
    if (baseUrl) config.base_url = baseUrl;
    if (settings.apiFormat.trim()) config.api_format = settings.apiFormat.trim();
    return config;
  }

  async function handleCreateRoom() {
    setIsCreating(true); setError(""); setPrepareSnapshot(null);
    try {
      const room = await createRoom({
        seed,
        playerCount,
        agentType: AgentType.LLM,
        mode,
        humanSeat,
        llmConfig: buildRoomLlmConfig(gameSettings),
      });
      setCreatedRoom(room);
      if (mode === "ai") setPrepareSnapshot(await prepareRoom(room.id, true));
      setShowModal(true);
    } catch (e) { setError(getErrorMessage(e, "创建房间失败")); }
    finally { setIsCreating(false); }
  }

  const roomInfoRows: RoomInfoRow[] = createdRoom ? [
    { label: t("room", language), value: `${createdRoom.id.slice(0, 8)}...` },
    { label: t("gameMode", language), value: mode === "human" ? t("humanPlay", language) : t("aiVsAi", language) },
    { label: t("players", language), value: String(playerCount) },
    { label: t("agent", language), value: t("agentLlm", language) },
    { label: language === Language.ZH ? "模型" : "Model", value: gameSettings.modelName || createdRoom.llm_model || "-" },
    ...(mode === "human" ? [{ label: t("yourSeat", language), value: `${t("seat", language)} ${humanSeat}` }] : []),
  ] : [];

  async function handleConfirmStart() {
    if (!createdRoom) return;
    setIsStarting(true); setError("");
    try {
      if (mode === "ai") {
        setGameState(prepareSnapshot ?? await prepareRoom(createdRoom.id, true));
      } else {
        setGameState(null);
      }
      const gamePath = mode === "human"
        ? `/room/${createdRoom.id}/play?mode=human&human_seat=${humanSeat}`
        : `/room/${createdRoom.id}/play?mode=ai`;
      router.push(gamePath);
    } catch (e) { setError(getErrorMessage(e, "启动失败")); setIsStarting(false); }
  }

  return (
    <main ref={pageRef} data-theme="dark" className="relative flex min-h-screen min-h-[100dvh] flex-col items-center overflow-x-hidden bg-background px-4 pb-[max(2rem,env(safe-area-inset-bottom))] pt-24 text-textPrimary sm:px-6 sm:pt-20">
      <AnimatedWerewolfBackground />
      <div className="pointer-events-none fixed inset-0 z-[1] bg-background/75" aria-hidden="true" />
      <BackgroundMusic language={language} />

      {/* ── Top nav ────────────────────────────────────────────── */}
      <nav aria-label={language === "zh" ? "大厅导航" : "Lobby navigation"} className="absolute left-4 right-16 top-4 z-20 flex flex-wrap items-center justify-end gap-2 sm:left-auto sm:right-16 sm:flex-nowrap">
        <Link href="/personas" className="inline-flex min-h-10 items-center rounded-button border border-border bg-cardBackground/80 px-3 text-xs font-medium text-textSecondary backdrop-blur-sm transition-colors duration-200 hover:border-primary/50 hover:text-primary">
          {language === "zh" ? "角色库" : "Personas"}
        </Link>

        <button
          data-testid="open-settings-button"
          type="button"
          onClick={() => setShowSettings(true)}
          className="inline-flex min-h-10 items-center gap-2 rounded-button border border-border bg-cardBackground/80 px-3 text-xs font-medium text-textSecondary backdrop-blur-sm transition-colors duration-200 hover:border-primary/50 hover:text-primary"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="3" />
            <path d="M12 1v6m0 6v6m-5.196-13.804l4.243 4.243m0 6.122l4.243 4.243M1 12h6m6 0h6m-13.804 5.196l4.243-4.243m0-6.122l4.243-4.243" />
          </svg>
          {language === "zh" ? "设置" : "Settings"}
        </button>
      </nav>

      {/* ── Brand — stable height, no jump on mode switch ────────── */}
      <header className="relative z-10 mb-7 shrink-0 text-center sm:mb-8">
        {/* Moon icon with glow */}
        <div data-home-intro="moon" className="relative mb-3 inline-block sm:mb-4">
          <div className="absolute inset-0 mx-auto h-12 w-12 rounded-full bg-primary/15 blur-xl" />
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" className="relative h-10 w-10 text-primary drop-shadow-[0_0_12px_rgba(183,131,63,0.4)] sm:h-12 sm:w-12">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
          </svg>
        </div>
        <p className="mb-2 text-xs font-medium tracking-[0.24em] text-textSecondary">
          {language === "zh" ? "狼人杀 · 对局大厅" : "WEREWOLF · MATCH LOBBY"}
        </p>
        <h1 data-home-intro="title" className="font-display text-3xl font-bold tracking-tight text-primary sm:text-4xl">
          AI Werewolf
        </h1>
        <p data-home-intro="subtitle" className="mx-auto mt-3 max-w-sm text-sm leading-relaxed text-textSecondary">
          {language === "zh" ? "黑夜降临，狼人出没。" : "Night falls. The wolves are among us."}
        </p>
      </header>

      {/* ── Config card ─────────────────────────────────────────── */}
      <div data-home-intro="card" className="relative z-10 w-full max-w-lg">
        <LobbyConfigCard
          language={language} playerCount={playerCount} mode={mode} humanSeat={humanSeat}
          isCreating={isCreating} error={showModal ? "" : error}
          onPlayerCountChange={(nextCount) => { setPlayerCount(nextCount); if (humanSeat > nextCount) setHumanSeat(nextCount); }}
          onModeChange={setMode} onHumanSeatChange={setHumanSeat}
          onCreateRoom={handleCreateRoom}
        />
      </div>

      {/* ── Footer ──────────────────────────────────────────────── */}
      <p data-home-intro="footer" className="relative z-10 mt-7 text-center text-xs leading-relaxed text-textSecondary">
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
    </main>
  );
}
