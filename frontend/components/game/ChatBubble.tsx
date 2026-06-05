"use client";

import React, { memo } from "react";
import { cn } from "@/lib/utils";
import { useTypewriter } from "@/hooks/useTypewriter";
import { SpeechCard } from "@/components/game/_speech/SpeechCard";
import { PhasePlaque } from "@/components/game/_speech/PhasePlaque";

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
}

export const ChatBubble = memo(function ChatBubble({
  speakerName, seat, content, phaseLabel,
  isOwn = false, isSystem = false, isSpeaking = false,
  eventType, eventPhase,
  animate = false, onTypewriterComplete,
}: ChatBubbleProps) {
  const shouldAnimate = animate && !isSystem && !!content;
  const { displayedText, finished } = useTypewriter(content, {
    enabled: shouldAnimate,
    charsPerSecond: 35,
    onComplete: onTypewriterComplete,
  });

  const isQueueManaged = onTypewriterComplete !== undefined;
  const displayContent = isQueueManaged ? displayedText : (shouldAnimate ? displayedText : content);
  const showCursor = isQueueManaged && !finished;

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
      headerRight={isSpeaking ? "发言中" : (phaseLabel || undefined)}
      className={cn(isOwn && "opacity-90")}
    >
      {displayContent ? (
        <span className="text-textPrimary">
          {displayContent}
          {showCursor && (
            <span className="inline-block w-0.5 h-[1em] bg-primary align-middle ml-0.5 animate-pulse" />
          )}
        </span>
      ) : (
        <span className="text-text-sub/40 italic">{" "}</span>
      )}
    </SpeechCard>
  );
});
