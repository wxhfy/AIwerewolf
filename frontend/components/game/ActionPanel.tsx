"use client";

import React, { useState, useEffect, useRef } from "react";
import { Button } from "@/components/ui/Button";
import { CountdownTimer } from "@/components/game/CountdownTimer";
import { VoteTargetGrid } from "@/components/game/VoteTargetGrid";
import { Language } from "@/types";

interface ActionPanelProps {
  pendingInput: any;
  onAction: (data: { target_id?: string | null; speech?: string | null; save?: boolean }) => void;
  language: Language;
  votes?: Record<string, string>;
  players?: Array<{ id: string; name: string; seat: number }>;
}

const SPEECH_REQUESTS = new Set(["TALK", "BADGE_SPEECH", "LAST_WORDS"]);
const HUMAN_TIMER_SECONDS = 60;

export function ActionPanel({ pendingInput, onAction, language, votes, players }: ActionPanelProps) {
  const pi = pendingInput;
  if (!pi) return null;

  const isSpeech = pi.action_type === "speech";
  const isVote = pi.action_type === "vote";
  const isNight = pi.action_type === "night_action" || pi.action_type === "special";
  const hasTimer = SPEECH_REQUESTS.has(pi.request);
  const isWitch = pi.request === "WITCH";

  const [speech, setSpeech] = useState("");
  const [targetId, setTargetId] = useState("");
  const [savePotion, setSavePotion] = useState(false);
  const [timerActive, setTimerActive] = useState(hasTimer);
  const [submitted, setSubmitted] = useState(false);
  const timerKey = useRef(0);

  // Reset state when pendingInput changes
  useEffect(() => {
    setSpeech("");
    setTargetId("");
    setSavePotion(false);
    setTimerActive(hasTimer);
    setSubmitted(false);
    timerKey.current += 1;
  }, [pi.player_id, pi.request]);

  function submit() {
    if (submitted) return;
    setSubmitted(true);
    setTimerActive(false);
    onAction({
      target_id: isSpeech ? null : (targetId || null),
      speech: isSpeech ? (speech.trim() || null) : null,
      save: isWitch ? savePotion : false,
    });
  }

  function handleTimerExpire() {
    if (submitted) return;
    setSubmitted(true);
    setTimerActive(false);
    onAction({
      target_id: isSpeech ? null : (targetId || null),
      speech: isSpeech ? (speech.trim() || null) : null,
      save: isWitch ? savePotion : false,
    });
  }

  const t = (zh: string, en: string) => (language === "zh" ? zh : en);

  return (
    <div className="border-t px-4 py-3 space-y-3"
      style={{ background: "var(--color-card)", borderColor: "var(--color-border)" }}>
      {/* Guidance */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold text-textPrimary">
            {pi.player_name} · {pi.phase}
          </p>
          <p className="text-xs text-text-sub mt-0.5">
            {pi.prompt || (isSpeech ? t("轮到你了，输入发言", "Your turn — type your speech") : t("请选择目标", "Please select a target"))}
          </p>
        </div>
        {hasTimer && (
          <div className="w-40">
            <CountdownTimer key={timerKey.current} seconds={HUMAN_TIMER_SECONDS} onExpire={handleTimerExpire} isActive={timerActive && !submitted} />
          </div>
        )}
      </div>

      {/* Speech input */}
      {isSpeech && (
        <textarea
          value={speech}
          onChange={(e) => setSpeech(e.target.value)}
          placeholder={pi.placeholder || t("输入你的发言...", "Type your speech...")}
          className="w-full h-24 px-3 py-2 rounded-lg border text-sm resize-none"
          style={{ background: "var(--color-bg)", borderColor: "var(--color-border)", color: "var(--color-text)" }}
          disabled={submitted}
          onKeyDown={(e) => { if (e.key === "Enter" && e.ctrlKey) submit(); }}
        />
      )}

      {/* Vote / Night action progress */}
      {(isVote || isNight) && votes && Object.keys(votes).length > 0 && (
        <div className="space-y-1 mb-2">
          <p className="text-[11px] text-text-sub font-medium mb-1.5">
            {isVote ? t("已投票：", "Votes cast:") : t("狼队选择：", "Wolf picks:")}
          </p>
          {Object.entries(votes).map(([voterId, targetId]) => {
            const voter = players?.find((p: any) => p.id === voterId);
            const target = players?.find((p: any) => p.id === targetId);
            return (
              <div key={voterId} className="flex items-center gap-1.5 text-xs">
                <span className="font-medium text-textPrimary">{voter?.name || voterId}</span>
                <span className="text-text-sub">→</span>
                <span className="font-medium text-textPrimary">{target?.name || targetId}</span>
                {target && <span className="text-text-sub">({target.seat}{language === "zh" ? "号" : ""})</span>}
              </div>
            );
          })}
        </div>
      )}

      {/* Vote target grid */}
      {isVote && (
        <VoteTargetGrid
          players={pi.options || []}
          selectedId={targetId}
          onSelect={setTargetId}
          disabled={submitted}
        />
      )}

      {/* Night action target — visual grid like vote */}
      {isNight && !isVote && (
        <div className="space-y-3">
          <VoteTargetGrid
            players={pi.options || []}
            selectedId={targetId}
            onSelect={setTargetId}
            disabled={submitted}
          />
          {isWitch && (
            <label className="flex items-center gap-2 text-sm text-textPrimary">
              <input type="checkbox" checked={savePotion} onChange={(e) => setSavePotion(e.target.checked)} disabled={submitted}
                className="w-4 h-4 rounded" />
              {t("使用解药", "Use healing potion")}
            </label>
          )}
          {pi.can_skip && (
            <button onClick={() => { setTargetId(""); submit(); }}
              disabled={submitted}
              className="text-xs text-text-sub underline hover:text-textPrimary">
              {t("跳过", "Skip")}
            </button>
          )}
        </div>
      )}

      {/* Submit */}
      <div className="flex justify-end">
        <Button onClick={submit} disabled={submitted || (isVote && !targetId)} size="sm">
          {submitted ? t("已提交", "Submitted") : t("提交", "Submit")}
        </Button>
      </div>
    </div>
  );
}
