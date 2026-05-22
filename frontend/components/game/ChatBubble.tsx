"use client";

import React from "react";
import { cn } from "@/lib/utils";

interface ChatBubbleProps {
  speakerName: string;
  content: string;
  phase?: string;
  phaseLabel?: string;
  isOwn?: boolean;
  isSystem?: boolean;
}

export function ChatBubble({
  speakerName,
  content,
  phase,
  phaseLabel,
  isOwn = false,
  isSystem = false,
}: ChatBubbleProps) {
  const avatarLetter = speakerName.charAt(0);

  // System message — centered muted text
  if (isSystem) {
    return (
      <div className="flex justify-center py-1.5">
        <span className="text-xs text-text-sub/60 italic px-3 py-1 rounded-full"
          style={{ background: "var(--color-bg)" }}>
          {content}
        </span>
      </div>
    );
  }

  const bubbleStyle = isOwn
    ? {
        background: "var(--color-primary)",
        color: "#fff",
        borderRadius: "16px 4px 16px 16px",
      }
    : {
        background: "var(--color-bg)",
        borderRadius: "4px 16px 16px 16px",
      };

  return (
    <div className={cn("flex gap-2.5 py-2 animate-slide-in", isOwn && "flex-row-reverse")}>
      {/* Avatar */}
      <div
        className={cn(
          "w-9 h-9 rounded-full flex-shrink-0 flex items-center justify-center text-sm font-bold",
          isOwn ? "bg-primary text-white" : "bg-primary/15 text-primary"
        )}
      >
        {avatarLetter}
      </div>

      {/* Bubble + meta */}
      <div className={cn("flex flex-col max-w-[75%]", isOwn ? "items-end" : "items-start")}>
        {/* Name + phase */}
        <div className={cn("flex items-center gap-2 mb-0.5", isOwn && "flex-row-reverse")}>
          <span className="text-xs font-medium text-textPrimary">{speakerName}</span>
          {phaseLabel && (
            <span className="text-[10px] text-text-sub">{phaseLabel}</span>
          )}
        </div>

        {/* Bubble */}
        <div
          className="px-3.5 py-2 text-sm leading-relaxed"
          style={bubbleStyle}
        >
          {content || (isOwn ? "..." : "")}
        </div>
      </div>
    </div>
  );
}
