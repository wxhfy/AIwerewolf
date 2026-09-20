"use client";

import React, { createContext, useContext, useState, useEffect } from "react";
import { Language, ViewMode, AgentType, RoomRecord, GameState } from "@/types";

interface AppContextType {
  language: Language;
  setLanguage: (lang: Language) => void;
  viewMode: ViewMode;
  setViewMode: (mode: ViewMode) => void;
  agentType: AgentType;
  setAgentType: (type: AgentType) => void;
  room: RoomRecord | null;
  setRoom: (room: RoomRecord | null) => void;
  gameState: GameState | null;
  setGameState: (state: GameState | null) => void;
  isConnected: boolean;
  setIsConnected: (connected: boolean) => void;
  isPlaying: boolean;
  setIsPlaying: (playing: boolean) => void;
  speed: number;
  setSpeed: (speed: number) => void;
  seed: number;
  setSeed: (seed: number) => void;
  settingsLoaded: boolean;
}

const AppContext = createContext<AppContextType | undefined>(undefined);

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [language, setLanguage] = useState<Language>(Language.ZH);
  const [viewMode, setViewModeState] = useState<ViewMode>(ViewMode.MODERATOR);
  const setViewMode = (_mode: ViewMode) => setViewModeState(ViewMode.MODERATOR);
  // AI-only rooms are executed by the server-owned Harness runtime.
  // Keep the deprecated UI selector fixed to its only supported value.
  const [agentType, setAgentType] = useState<AgentType>(AgentType.LLM);
  const [room, setRoom] = useState<RoomRecord | null>(null);
  const [gameState, setGameState] = useState<GameState | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [speed, setSpeed] = useState(800);
  const [seed, setSeed] = useState(7);
  const [settingsLoaded, setSettingsLoaded] = useState(false);

  // 从 URL 恢复状态
  useEffect(() => {
    if (typeof window !== "undefined") {
      const savedSettings = localStorage.getItem("gameSettings");
      if (savedSettings) {
        try {
          const parsed = JSON.parse(savedSettings) as { language?: string; viewMode?: string; seed?: number };
          if (parsed.language === Language.EN || parsed.language === Language.ZH) {
            setLanguage(parsed.language);
          }
          setViewMode(ViewMode.MODERATOR);
          localStorage.setItem(
            "gameSettings",
            JSON.stringify({ ...parsed, viewMode: ViewMode.MODERATOR }),
          );
          if (typeof parsed.seed === "number" && Number.isFinite(parsed.seed)) {
            setSeed(Math.trunc(parsed.seed));
          }
        } catch {
          // Ignore stale settings; individual pages still provide defaults.
        }
      }
      const params = new URLSearchParams(window.location.search);
      const langParam = params.get("lang");

      if (langParam === "en" || langParam === "zh") {
        setLanguage(langParam as Language);
      }
      // Ignore stale agent_type query parameters from pre-Harness links.
    }
    setSettingsLoaded(true);
  }, []);

  // 更新 URL 参数
  useEffect(() => {
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      params.set("lang", language);
      params.set("agent_type", agentType);
      if (room) {
        params.set("room", room.id);
      }
      const newUrl = `${window.location.pathname}?${params.toString()}`;
      window.history.replaceState({}, "", newUrl);
    }
  }, [language, agentType, room]);

  return (
    <AppContext.Provider
      value={{
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
        isConnected,
        setIsConnected,
        isPlaying,
        setIsPlaying,
        speed,
        setSpeed,
        seed,
        setSeed,
        settingsLoaded,
      }}
    >
      {children}
    </AppContext.Provider>
  );
}

export function useAppContext() {
  const context = useContext(AppContext);
  if (!context) {
    throw new Error("useAppContext must be used within an AppProvider");
  }
  return context;
}
