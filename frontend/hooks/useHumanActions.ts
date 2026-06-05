"use client";

import { useState, useEffect } from "react";
import type { GameState, Player } from "@/types";

interface UseHumanActionsOptions {
  gameState: GameState | null;
  humanSeat: number;
  humanDisplay: { isMyTurn: boolean; canAct: boolean };
  onSubmit: (data: { target_id?: string | null; speech?: string | null; save?: boolean }) => void;
}

interface HumanActionsState {
  selectedTarget: string;
  setSelectedTarget: (id: string) => void;
  submitted: boolean;
  speech: string;
  setSpeech: (s: string) => void;
  revealDone: boolean;
  setRevealDone: (v: boolean) => void;
  needsTarget: boolean;
  isSpeech: boolean;
  canSubmit: boolean;
  targetPlayer: Player | undefined;
}

/**
 * 真人模式操作状态 — 从 page.tsx 提取。
 *
 * 管理：目标选择、发言输入、提交状态、身份揭示计时器。
 */
export function useHumanActions({
  gameState, humanSeat, humanDisplay, onSubmit,
}: UseHumanActionsOptions): HumanActionsState {
  const [selectedTarget, setSelectedTarget] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [speech, setSpeech] = useState("");
  const [revealDone, setRevealDone] = useState(false);

  const pending = gameState?.pending_input;

  const needsTarget = !!(
    pending &&
    (pending.action_type === "vote" || pending.action_type === "night_action" ||
     (pending.action_type as string) === "special")
  );
  const isSpeech = pending?.action_type === "speech";
  const canSubmit = !needsTarget || !!selectedTarget;
  const targetPlayer = gameState?.players?.find(p => p.id === selectedTarget);

  // Reset when pending changes
  useEffect(() => {
    setSelectedTarget("");
    setSubmitted(false);
    setSpeech("");
  }, [pending?.player_id, pending?.request]);

  return {
    selectedTarget, setSelectedTarget,
    submitted, speech, setSpeech,
    revealDone, setRevealDone,
    needsTarget, isSpeech: isSpeech || false,
    canSubmit, targetPlayer,
  };
}
