"use client";

import React, { useState, useEffect, useRef } from "react";
import { Button } from "@/components/ui/Button";
import { CountdownTimer } from "@/components/game/CountdownTimer";
import { VoteTargetGrid } from "@/components/game/VoteTargetGrid";
import { Language, PendingInput, Player } from "@/types";
import { t, tPhase } from "@/lib/i18n";

interface ActionPanelProps {
  pendingInput: PendingInput;
  onAction: (data: { target_id?: string | null; speech?: string | null; save?: boolean }) => void;
  language: Language;
  votes?: Record<string, string>;
  players?: Player[];
}

const SPEECH_REQUESTS = new Set(["TALK", "BADGE_SPEECH", "LAST_WORDS"]);
const HUMAN_TIMER_SECONDS = 60;

const BUTTON_TEXT: Record<string, (l: Language) => string> = {
  DIVINE: (l) => l === "zh" ? "确认查验" : "Confirm Check",
  ATTACK: (l) => l === "zh" ? "确认击杀" : "Confirm Kill",
  GUARD: (l) => l === "zh" ? "确认守护" : "Confirm Guard",
  WITCH: (l) => l === "zh" ? "确认用药" : "Confirm",
  SHOOT: (l) => l === "zh" ? "确认开枪" : "Confirm Shoot",
  VOTE: (l) => l === "zh" ? "确认投票" : "Confirm Vote",
  BADGE_SPEECH: (l) => l === "zh" ? "提交竞选发言" : "Submit",
  LAST_WORDS: (l) => l === "zh" ? "结束遗言" : "Finish",
  TALK: (l) => l === "zh" ? "发送" : "Send",
};

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

  useEffect(() => {
    setSpeech(""); setTargetId(""); setSavePotion(false);
    setTimerActive(hasTimer); setSubmitted(false);
    timerKey.current += 1;
  }, [pi.player_id, pi.request]);

  function submit() {
    if (submitted) return;
    setSubmitted(true);
    setTimerActive(false);
    onAction({ target_id: isSpeech ? null : (targetId || null), speech: isSpeech ? (speech.trim() || null) : null, save: isWitch ? savePotion : false });
  }

  function handleTimerExpire() {
    if (submitted) return;
    setSubmitted(true);
    setTimerActive(false);
    onAction({ target_id: isSpeech ? null : (targetId || null), speech: isSpeech ? (speech.trim() || null) : null, save: isWitch ? savePotion : false });
  }

  const targetPlayer = players?.find(p => p.id === targetId);
  const btnTextFn = BUTTON_TEXT[pi.request] || BUTTON_TEXT[isVote ? "VOTE" : ""] || ((l: Language) => l === "zh" ? "确认" : "Confirm");
  const btnLabel = btnTextFn(language);

  return (
    <div className="border-t border-border bg-cardBackground px-4 py-2">
      {/* Header row: guidance + timer */}
      <div className="flex items-center justify-between mb-2">
        <div className="min-w-0">
          <p className="text-xs font-medium text-textPrimary truncate">{pi.player_name} · {tPhase(pi.phase, language)}</p>
          <p className="text-[11px] text-text-sub truncate">{pi.prompt || t("selectTarget", language)}</p>
        </div>
        {hasTimer && (
          <div className="w-32 shrink-0 ml-3">
            <CountdownTimer key={timerKey.current} seconds={HUMAN_TIMER_SECONDS} onExpire={handleTimerExpire} isActive={timerActive && !submitted} />
          </div>
        )}
      </div>

      {/* Submitted state */}
      {submitted && (
        <div className="flex items-center gap-2 text-xs text-text-sub py-2">
          <span className="h-3 w-3 animate-spin rounded-full border-2 border-primary/30 border-t-primary" />
          {language === "zh" ? "已提交，等待阶段推进" : "Submitted, waiting..."}
        </div>
      )}

      {/* Speech input */}
      {isSpeech && !submitted && (
        <div className="space-y-2">
          <textarea value={speech} onChange={(e) => setSpeech(e.target.value)}
            placeholder={pi.placeholder || t("typeSpeech", language)}
            className="h-16 w-full resize-none rounded-lg border border-border bg-background px-3 py-2 text-sm text-textPrimary"
            disabled={submitted}
            onKeyDown={(e) => { if (e.key === "Enter" && e.ctrlKey) submit(); }} />
          <div className="flex justify-between items-center">
            <button onClick={() => { setSpeech(""); submit(); }} disabled={submitted}
              className="text-[11px] text-text-sub/60 hover:text-text-sub">
              {pi.request === "BADGE_SPEECH" ? (language === "zh" ? "不竞选" : "Decline") : (language === "zh" ? "跳过发言" : "Skip")}
            </button>
            <Button onClick={submit} disabled={submitted} size="sm">{btnLabel}</Button>
          </div>
        </div>
      )}

      {/* Vote / Night target */}
      {(isVote || isNight) && !submitted && (
        <div className="space-y-2">
          <VoteTargetGrid players={pi.options || []} selectedId={targetId} onSelect={setTargetId} disabled={submitted} />
          {isWitch && (
            <label className="flex items-center gap-2 text-xs text-textPrimary">
              <input type="checkbox" checked={savePotion} onChange={(e) => setSavePotion(e.target.checked)} disabled={submitted} className="w-4 h-4 rounded" />
              {t("useHealingPotion", language)}
            </label>
          )}
          <div className="flex justify-between items-center">
            <span className="text-xs text-text-sub/60">
              {targetPlayer ? `${language === "zh" ? "已选择" : "Selected"}：${targetPlayer.seat}号 ${targetPlayer.name}` : (language === "zh" ? "请选择目标" : "Select target")}
            </span>
            <div className="flex gap-2 items-center">
              {pi.can_skip && (
                <button onClick={() => { setTargetId(""); submit(); }} disabled={submitted} className="text-[11px] text-text-sub/60 hover:text-text-sub">
                  {t("skip", language)}
                </button>
              )}
              <Button onClick={submit} disabled={!targetId} size="sm">{btnLabel}</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
