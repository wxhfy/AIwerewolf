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
}

const AppContext = createContext<AppContextType | undefined>(undefined);

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [language, setLanguage] = useState<Language>(Language.ZH);
  const [viewMode, setViewMode] = useState<ViewMode>(ViewMode.PUBLIC);
  // The user wants every game LLM-driven. Heuristic remains a code path only
  // as LLMAgent's automatic fallback after 3 retry failures, never as a
  // user-selectable mode. Default to LLM and reject any URL override below.
  const [agentType, setAgentType] = useState<AgentType>(AgentType.LLM);
  const [room, setRoom] = useState<RoomRecord | null>(null);
  const [gameState, setGameState] = useState<GameState | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [speed, setSpeed] = useState(80);
  const [seed, setSeed] = useState(7);

  // 从 URL 恢复状态
  useEffect(() => {
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      const langParam = params.get("lang");
      const roomParam = params.get("room");

      if (langParam === "en" || langParam === "zh") {
        setLanguage(langParam as Language);
      }
      // We intentionally ignore ?agent_type=heuristic from old links — the
      // public surface is LLM-only now; honoring stale URLs would silently
      // downgrade users back to heuristic.
    }
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
