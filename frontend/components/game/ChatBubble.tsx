"use client";

import React from "react";
import { cn } from "@/lib/utils";

interface ChatBubbleProps {
  speakerName: string;
  content: string;
  phaseLabel?: string;
  isOwn?: boolean;
  isSystem?: boolean;
}

export function ChatBubble({
  speakerName,
  content,
  phaseLabel,
  isOwn = false,
  isSystem = false,
}: ChatBubbleProps) {
  const avatarLetter = speakerName.charAt(0);

  if (isSystem) {
    return (
      <div className="flex justify-center py-2.5">
        <span className="rounded-full bg-background px-5 py-1.5 text-sm italic text-text-sub/70">
          {content}
        </span>
      </div>
    );
  }

  return (
    <div className={cn("flex gap-2.5 py-2 animate-slide-in", isOwn && "flex-row-reverse")}>
      {/* Avatar */}
      <div
        className={cn(
          "w-10 h-10 rounded-full flex-shrink-0 flex items-center justify-center text-base font-bold",
          isOwn ? "bg-primary text-white" : "bg-primary/15 text-primary"
        )}
      >
        {avatarLetter}
      </div>

      {/* Bubble + meta */}
      <div className={cn("flex flex-col max-w-[75%]", isOwn ? "items-end" : "items-start")}>
        {/* Name + phase */}
        <div className={cn("flex items-center gap-2 mb-1", isOwn && "flex-row-reverse")}>
          <span className="text-sm font-medium text-textPrimary">{speakerName}</span>
          {phaseLabel && (
            <span className="text-xs text-text-sub">{phaseLabel}</span>
          )}
        </div>

        {/* Bubble */}
        {content && (
          <div
            className={cn(
              "px-4 py-2.5 text-base leading-relaxed",
              isOwn ? "rounded-[16px_4px_16px_16px] bg-primary text-white" : "rounded-[4px_16px_16px_16px] bg-background text-textPrimary",
            )}
          >
            {content}
          </div>
        )}
      </div>
    </div>
  );
}
