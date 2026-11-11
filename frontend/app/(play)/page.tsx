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
  modelProvider: "siliconflow",
  modelName: "THUDM/GLM-4-9B-0414",
  apiKey: "",
  baseUrl: "https://api.siliconflow.cn/v1",
  apiFormat: "openai_chat",
  authEnvVar: "SILICONFLOW_API_KEY",
};

function normalizeGameSettings(raw: unknown): GameSettings {
  const data = raw && typeof raw === "object" ? raw as Partial<GameSettings> & { customApiKey?: string } : {};
  const viewMode = data.viewMode && Object.values(ViewMode).includes(data.viewMode as ViewMode)
    ? (data.viewMode as ViewMode)
    : ViewMode.PUBLIC;
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
    if (gameSettings.viewMode !== viewMode) {
      setViewMode(gameSettings.viewMode);
    }
    if (gameSettings.seed !== seed) {
      setSeed(gameSettings.seed);
    }
  }, [agentType, setAgentType, gameSettings.language, gameSettings.viewMode, gameSettings.seed, language, seed, setLanguage, setSeed, setViewMode, viewMode]);

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
    setViewMode(normalizedSettings.viewMode);
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
      if (mode === "ai") setPrepareSnapshot(await prepareRoom(room.id, false));
      setShowModal(true);
    } catch (e) { setError(getErrorMessage(e, "创建房间失败")); }
    finally { setIsCreating(false); }
  }

  const roomInfoRows: RoomInfoRow[] = createdRoom ? [
    { label: t("room", language), value: `${createdRoom.id.slice(0, 8)}...` },
    { label: t("gameMode", language), value: mode === "human" ? t("humanPlay", language) : t("aiVsAi", language) },
    { label: t("players", language), value: `${playerCount} ${language === "zh" ? "人桌" : "players"}` },
    ...(mode === "human" ? [{ label: t("yourSeat", language), value: `${t("seat", language)} ${humanSeat}` }] : []),
  ] : [];

  async function handleConfirmStart() {
    if (!createdRoom) return;
    setIsStarting(true); setError("");
    try {
      if (mode === "ai") {
        setGameState(prepareSnapshot ?? await prepareRoom(createdRoom.id, false));
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
    <main ref={pageRef} data-theme="dark" className="relative flex min-h-screen min-h-[100dvh] flex-col items-center overflow-x-hidden bg-background px-4 pb-[max(2rem,env(safe-area-inset-bottom))] pt-20 text-textPrimary sm:px-6 sm:pt-16">
      {/* Still tavern plate — no starfield, fog drift, or particle rain */}
      <div className="pointer-events-none fixed inset-0 z-0" aria-hidden="true">
        <img
          src="/images/lobby-tavern.webp"
          alt=""
          className="h-full w-full object-cover object-center"
        />
        {/* Dim + vignette so the entrance card reads; keep the table visible */}
        <div className="absolute inset-0 bg-gradient-to-b from-[#100804]/55 via-[#100804]/35 to-[#0a0604]/75" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,transparent_0%,transparent_42%,rgba(10,6,4,0.55)_100%)]" />
      </div>
      <BackgroundMusic language={language} />

      {/* ── Top nav: Small Language control ────────────────────────────── */}
      <nav aria-label={language === "zh" ? "语言设置" : "Language settings"} className="absolute right-4 top-4 z-20 flex items-center gap-2 sm:right-6">
        <button
          type="button"
          onClick={() => {
            const nextLang = language === Language.ZH ? Language.EN : Language.ZH;
            setLanguage(nextLang);
            persistGameSettings({ ...gameSettings, language: nextLang });
          }}
          className="inline-flex min-h-8 items-center rounded-full border border-amber-800/40 bg-[#160d07]/80 px-3 py-1 text-xs font-serif text-amber-200/80 backdrop-blur-sm transition-colors hover:border-amber-600 hover:text-amber-100"
          aria-label={language === "zh" ? "Switch to English" : "切换为中文"}
        >
          <span>🌐</span>
          <span className="ml-1.5 font-sans font-medium">{language === Language.ZH ? "EN" : "中"}</span>
        </button>
      </nav>

      {/* ── Brand: Tavern Entrance Header ────────── */}
      <header className="relative z-10 mb-7 shrink-0 text-center sm:mb-8">
        <div data-home-intro="moon" className="relative mb-3 inline-block sm:mb-4">
          <div className="absolute inset-0 mx-auto h-12 w-12 rounded-full bg-amber-500/15 blur-xl" />
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" className="relative h-10 w-10 text-amber-400 drop-shadow-[0_0_12px_rgba(245,158,11,0.5)] sm:h-12 sm:w-12">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
          </svg>
        </div>
        <p className="mb-2 text-xs font-serif tracking-[0.24em] text-amber-400/80">
          {language === "zh" ? "月下村庄 · 围炉夜话" : "MOONLIT VILLAGE · TAVERN TALES"}
        </p>
        <h1 data-home-intro="title" className="font-display text-3xl font-bold tracking-tight text-amber-100 sm:text-4xl drop-shadow">
          AI Werewolf
        </h1>
        <p data-home-intro="subtitle" className="mx-auto mt-2 max-w-sm text-xs sm:text-sm leading-relaxed text-amber-200/70 font-serif">
          {language === "zh" ? "酒馆炉火正旺，推门围桌，静听暗夜杀机。" : "The hearth burns warm. Enter the tavern and take your seat."}
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
          onOpenSettings={() => setShowSettings(true)}
        />
      </div>

      {/* ── Discreet Footer Links ──────────────────────────────── */}
      <footer data-home-intro="footer" className="relative z-10 mt-8 flex flex-col items-center gap-2 text-center text-xs text-amber-300/40">
        <p>
          <span className="font-display font-semibold text-amber-300/60">AI Werewolf</span>
          <span className="mx-2">·</span>
          <span>{t("spectateAndPlay", language)}</span>
        </p>
        <div className="flex items-center gap-4 text-[11px] text-amber-400/50">
          <Link href="/admin" className="hover:text-amber-200 transition-colors">
            {language === "zh" ? "管理后台" : "Admin"}
          </Link>
          <span>·</span>
          <Link href="/admin/personas" className="hover:text-amber-200 transition-colors">
            {language === "zh" ? "角色库" : "Personas"}
          </Link>
        </div>
      </footer>

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

      {/* ── Settings modal (opened via collapsed dev settings) ───── */}
      <SettingsModal
        isOpen={showSettings}
        onClose={() => setShowSettings(false)}
        currentSettings={gameSettings}
        onSave={handleSaveSettings}
      />
    </main>
  );
}
