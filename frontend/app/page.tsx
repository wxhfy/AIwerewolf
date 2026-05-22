"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import { useAppContext } from "@/context/AppContext";
import { Language, AgentType } from "@/types";
import { Button } from "@/components/ui/Button";

export default function LobbyPage() {
  const router = useRouter();
  const { language, setLanguage, agentType, setAgentType } = useAppContext();

  const [playerCount, setPlayerCount] = useState(7);
  const [mode, setMode] = useState<"ai" | "human">("ai");
  const [humanSeat, setHumanSeat] = useState(1);
  const [seed, setSeed] = useState(Math.floor(Math.random() * 1000));
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState("");

  async function handleStart() {
    setIsCreating(true);
    setError("");
    try {
      const params = new URLSearchParams({
        name: "Demo Room",
        seed: String(seed),
        player_count: String(playerCount),
        agent_type: agentType,
      });
      if (mode === "human") {
        params.set("human_seat", String(humanSeat));
      }
      const res = await fetch(`/api/rooms?${params.toString()}`, { method: "POST" });
      if (!res.ok) throw new Error(`Failed to create room (${res.status})`);
      const room = await res.json();
      router.push(`/room/${room.id}/prepare?human_seat=${humanSeat}&mode=${mode}`);
    } catch (e: any) {
      setError(e.message || "创建房间失败");
      setIsCreating(false);
    }
  }

  const t = (zh: string, en: string) => (language === "zh" ? zh : en);

  return (
    <div
      className="min-h-screen flex flex-col items-center justify-center px-4"
      style={{
        background: "var(--color-bg)",
        transition: "background var(--transition-daynight) var(--ease-in-out)",
      }}
    >
      {/* Language toggle */}
      <div className="absolute top-4 right-4 flex rounded-button border overflow-hidden"
        style={{ borderColor: "var(--color-border)" }}>
        <button onClick={() => setLanguage(Language.ZH)}
          className={`px-3 py-1.5 text-xs font-medium transition-colors ${
            language === "zh" ? "bg-primary text-white" : "bg-transparent text-text-sub hover:text-textPrimary"
          }`}>中文</button>
        <button onClick={() => setLanguage(Language.EN)}
          className={`px-3 py-1.5 text-xs font-medium transition-colors ${
            language === "en" ? "bg-primary text-white" : "bg-transparent text-text-sub hover:text-textPrimary"
          }`}>EN</button>
      </div>

      {/* Brand */}
      <div className="text-center mb-10">
        <svg width="56" height="56" viewBox="0 0 24 24"
          fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round"
          className="mx-auto mb-4 text-primary" aria-hidden="true">
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
        </svg>
        <h1 className="font-display text-3xl font-bold text-primary">
          AI Werewolf
        </h1>
        <p className="mt-2 text-text-sub text-sm max-w-xs mx-auto">
          {t("配置游戏参数，开始一局 AI 狼人杀对战", "Configure your game and start an AI Werewolf match")}
        </p>
      </div>

      {/* Config Card */}
      <div
        className="w-full max-w-md rounded-card p-6 space-y-5"
        style={{
          background: "var(--color-card)",
          border: "1px solid var(--color-border)",
          boxShadow: "0 4px 24px rgba(0,0,0,0.05), 0 1px 4px rgba(0,0,0,0.03)",
        }}
      >
        {/* Mode toggle */}
        <div>
          <label className="block text-sm font-medium text-textPrimary mb-2">
            {t("游戏模式", "Game Mode")}
          </label>
          <div className="flex rounded-button border overflow-hidden"
            style={{ borderColor: "var(--color-border)" }}>
            {(["ai", "human"] as const).map((m) => (
              <button key={m} onClick={() => setMode(m)}
                className={`flex-1 py-2 text-sm font-medium transition-colors ${
                  mode === m ? "bg-primary text-white" : "bg-transparent text-text-sub hover:text-textPrimary"
                }`}>
                {m === "ai" ? t("AI 对战", "AI vs AI") : t("真人参与", "Human Play")}
              </button>
            ))}
          </div>
        </div>

        {/* Player count */}
        <div>
          <label className="block text-sm font-medium text-textPrimary mb-2">
            {t("玩家数量", "Player Count")}
          </label>
          <select value={playerCount} onChange={(e) => {
            const n = Number(e.target.value);
            setPlayerCount(n);
            if (humanSeat > n) setHumanSeat(n);
          }}
            className="w-full h-10 px-3 rounded-button border text-sm text-textPrimary"
            style={{ background: "var(--color-bg)", borderColor: "var(--color-border)" }}>
            {[7, 8, 9, 10, 11, 12].map((n) => (
              <option key={n} value={n}>{n} {t("人", " players")}</option>
            ))}
          </select>
        </div>

        {/* Human seat (only in human mode) */}
        {mode === "human" && (
          <div>
            <label className="block text-sm font-medium text-textPrimary mb-2">
              {t("你的座位号", "Your Seat")}
            </label>
            <select value={humanSeat} onChange={(e) => setHumanSeat(Number(e.target.value))}
              className="w-full h-10 px-3 rounded-button border text-sm text-textPrimary"
              style={{ background: "var(--color-bg)", borderColor: "var(--color-border)" }}>
              {Array.from({ length: playerCount }, (_, i) => i + 1).map((s) => (
                <option key={s} value={s}>{t("座位", "Seat")} {s}</option>
              ))}
            </select>
          </div>
        )}

        {/* Agent type */}
        <div>
          <label className="block text-sm font-medium text-textPrimary mb-2">
            {t("AI 类型", "Agent Type")}
          </label>
          <div className="flex rounded-button border overflow-hidden"
            style={{ borderColor: "var(--color-border)" }}>
            {(["heuristic", "llm"] as const).map((t2) => (
              <button key={t2} onClick={() => setAgentType(t2 as AgentType)}
                className={`flex-1 py-2 text-sm font-medium transition-colors ${
                  agentType === t2 ? "bg-primary text-white" : "bg-transparent text-text-sub hover:text-textPrimary"
                }`}>
                {t2 === "heuristic" ? t("启发式", "Heuristic") : "LLM"}
              </button>
            ))}
          </div>
        </div>

        {/* Seed */}
        <div>
          <label className="block text-sm font-medium text-textPrimary mb-2">
            Seed
          </label>
          <input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value) || 0)}
            className="w-full h-10 px-3 rounded-button border text-sm text-textPrimary"
            style={{ background: "var(--color-bg)", borderColor: "var(--color-border)" }} />
        </div>

        {/* Error */}
        {error && (
          <p className="text-sm text-danger text-center">{error}</p>
        )}

        {/* Start button */}
        <Button onClick={handleStart} disabled={isCreating} className="w-full h-11 text-base">
          {isCreating ? t("创建中...", "Creating...") : t("开始游戏", "Start Game")}
        </Button>
      </div>

      {/* Footer */}
      <p className="mt-8 text-xs text-text-sub">
        <span className="font-display">AI Werewolf</span>
        <span className="mx-2">·</span>
        <span>{t("观战 & 对战", "Spectate & Play")}</span>
      </p>
    </div>
  );
}
