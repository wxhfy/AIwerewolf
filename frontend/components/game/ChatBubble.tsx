"use client";

import React, { memo } from "react";
import { cn } from "@/lib/utils";
import { SpeechCard } from "@/components/game/_speech/SpeechCard";
import { PhasePlaque } from "@/components/game/_speech/PhasePlaque";
import { MentionText } from "@/components/game/MentionText";
import { Player } from "@/types";

interface ChatBubbleProps {
  speakerName: string;
  seat?: number;
  content: string;
  phaseLabel?: string;
  isOwn?: boolean;
  isSystem?: boolean;
  /** Event type (PHASE_CHANGED / SYSTEM_MESSAGE etc.) for PhasePlaque classification */
  eventType?: string;
  /** Event phase (NIGHT_GUARD_ACTION etc.) for PhasePlaque classification */
  eventPhase?: string;
  isSpeaking?: boolean;
  animate?: boolean;
  onTypewriterComplete?: () => void;
  players?: Player[];
  testId?: string;
}

export const ChatBubble = memo(function ChatBubble({
  speakerName, seat, content, phaseLabel,
  isOwn = false, isSystem = false, isSpeaking = false,
  eventType, eventPhase,
  players,
  testId,
}: ChatBubbleProps) {
  const displayContent = content.trim();

  // System / phase messages → PhasePlaque with ceremony
  if (isSystem) {
    return (
      <PhasePlaque eventType={eventType} phase={eventPhase}>
        {content}
      </PhasePlaque>
    );
  }

  return (
    <SpeechCard
      seat={seat}
      name={speakerName}
      isSpeaking={isSpeaking}
      headerRight={phaseLabel || undefined}
      className={cn(isOwn && "opacity-90")}
      testId={testId}
    >
      {displayContent ? (
        <MentionText text={displayContent} players={players} className="text-textPrimary" />
      ) : (
        <span className="text-text-sub/60">{phaseLabel || "记录已生成"}</span>
      )}
    </SpeechCard>
  );
});
