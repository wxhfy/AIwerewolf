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
  savePotion: boolean;
  setSavePotion: (v: boolean) => void;
  revealDone: boolean;
  setRevealDone: (v: boolean) => void;
  needsTarget: boolean;
  isSpeech: boolean;
  isWitch: boolean;
  canSubmit: boolean;
  targetPlayer: Player | undefined;
  optionIds: Set<string>;
  submitAction: () => void;
  submitSkip: () => void;
}

/**
 * 真人模式操作状态 — 从 page.tsx 提取。
 *
 * 管理：目标选择、发言输入、提交状态、身份揭示计时器。
 */
export function useHumanActions({
  gameState,
  onSubmit,
}: UseHumanActionsOptions): HumanActionsState {
  const [selectedTarget, setSelectedTarget] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [speech, setSpeech] = useState("");
  const [savePotion, setSavePotion] = useState(false);
  const [revealDone, setRevealDone] = useState(false);

  const pending = gameState?.pending_input;
  const optionIds = new Set((pending?.options || []).map(option => option.id));

  const needsTarget = !!(
    pending &&
    (pending.action_type === "vote" || pending.action_type === "night_action" ||
     (pending.action_type as string) === "special")
  );
  const isSpeech = pending?.action_type === "speech";
  const isWitch = pending?.request === "WITCH";
  const canSubmit = isSpeech || !needsTarget || !!selectedTarget || (isWitch && savePotion);
  const targetPlayer = gameState?.players?.find(p => p.id === selectedTarget);

  function submitAction() {
    if (submitted || !canSubmit) return;
    setSubmitted(true);
    onSubmit({
      target_id: needsTarget ? (selectedTarget || null) : null,
      speech: isSpeech ? (speech.trim() || null) : null,
      save: isWitch ? savePotion : false,
    });
  }

  function submitSkip() {
    if (submitted || !pending?.can_skip) return;
    setSubmitted(true);
    onSubmit({
      target_id: null,
      speech: null,
      save: false,
    });
  }

  // Reset when pending changes
  useEffect(() => {
    setSelectedTarget("");
    setSubmitted(false);
    setSpeech("");
    setSavePotion(false);
  }, [pending?.player_id, pending?.request]);

  return {
    selectedTarget, setSelectedTarget,
    submitted, speech, setSpeech, savePotion, setSavePotion,
    revealDone, setRevealDone,
    needsTarget, isSpeech: isSpeech || false, isWitch,
    canSubmit, targetPlayer, optionIds, submitAction, submitSkip,
  };
}
