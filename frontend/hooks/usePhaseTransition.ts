"use client";

import { useLayoutEffect, useMemo, useRef } from "react";
import { getPhaseGroup } from "@/lib/gamePhase";
import type { GameState } from "@/types";

export type VisualPhaseGroup = "day" | "night" | "end";
export type PhaseAnnouncementGroup = VisualPhaseGroup | "ready";

export interface PhaseAnnouncementState {
  group: PhaseAnnouncementGroup;
  visible: boolean;
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

  return {
    visualPhaseGroup,
    isVisualNight: visualPhaseGroup === "night",
    phaseAnnouncement: null as PhaseAnnouncementState | null,
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
