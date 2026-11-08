"use client";

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { getPhaseGroup } from "@/lib/gamePhase";
import type { GameState } from "@/types";

export type VisualPhaseGroup = "day" | "night" | "end";
export type PhaseAnnouncementGroup = VisualPhaseGroup | "ready";

export interface PhaseAnnouncementState {
  group: PhaseAnnouncementGroup;
  visible: boolean;
  text?: string;
}

export function usePhaseTransition(
  _sessionKey: string,
  gameState: GameState | null,
  hasWinner: boolean,
) {
  const flushResultRef = useRef<GameState | null>(null);
  const flushQueueRef = useRef<GameState[]>([]);

  const visualPhaseGroup = useMemo<VisualPhaseGroup>(() => {
    if (hasWinner) return "end";
    const group = getPhaseGroup(gameState?.phase);
    return group === "night" || group === "end" ? group : "day";
  }, [gameState?.phase, hasWinner]);

  useLayoutEffect(() => {
    document.documentElement.setAttribute("data-phase", visualPhaseGroup);
    return () => document.documentElement.setAttribute("data-phase", "day");
  }, [visualPhaseGroup]);

  const [announcement, setAnnouncement] = useState<PhaseAnnouncementState | null>(null);
  const prevPhaseRef = useRef<string | undefined>(undefined);
  const prevGroupRef = useRef<VisualPhaseGroup | undefined>(undefined);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (hasWinner || visualPhaseGroup === "end") {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      setAnnouncement(null);
      prevPhaseRef.current = gameState?.phase;
      prevGroupRef.current = "end";
      return;
    }

    const currentPhase = gameState?.phase;
    if (!currentPhase) return;
    const prevPhase = prevPhaseRef.current;
    const prevGroup = prevGroupRef.current;
    prevPhaseRef.current = currentPhase;
    prevGroupRef.current = visualPhaseGroup;

    if (prevPhase && prevPhase !== currentPhase) {
      let text = "";
      if (visualPhaseGroup === "night" && prevGroup !== "night") {
        text = `第 ${gameState?.day || 1} 夜 · 天黑请闭眼`;
      } else if (visualPhaseGroup === "day" && prevGroup !== "day") {
        text = `第 ${gameState?.day || 1} 天 · 天亮了`;
      } else if (currentPhase.includes("VOTE")) {
        text = `第 ${gameState?.day || 1} 天 · 投票阶段`;
      }

      if (text) {
        setAnnouncement({
          group: visualPhaseGroup,
          visible: true,
          text,
        });
        if (timerRef.current) clearTimeout(timerRef.current);
        timerRef.current = setTimeout(() => {
          setAnnouncement((prev) => (prev ? { ...prev, visible: false } : null));
        }, 2200);
      }
    }
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [gameState?.phase, gameState?.day, visualPhaseGroup, hasWinner]);

  return {
    visualPhaseGroup,
    isVisualNight: visualPhaseGroup === "night",
    phaseAnnouncement: hasWinner || visualPhaseGroup === "end" ? null : announcement,
    isBlinking: false,
    blinkPhase: null,
    isTransitioning: false,
    displayGameState: gameState,
    bufferSnapshot: (_state: GameState) => undefined,
    getIsBlinking: () => false,
    flushResultRef,
    flushQueueRef,
    onBlinkCloseComplete: () => undefined,
    onBlinkPauseComplete: () => undefined,
    onBlinkOpenComplete: () => undefined,
  };
}
