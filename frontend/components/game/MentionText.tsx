"use client";

import React from "react";
import { Player } from "@/types";
import { cn } from "@/lib/utils";

interface MentionTextProps {
  text: string;
  players?: Player[];
  className?: string;
}

export function MentionText({ text, players = [], className }: MentionTextProps) {
  const parts: React.ReactNode[] = [];
  const regex = /@?(\d{1,2})号/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(text)) !== null) {
    const seat = Number(match[1]);
    const player = players.find((item) => item.seat === seat);

    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }

    parts.push(
      <span
        key={`${match.index}-${seat}`}
        className="mx-0.5 inline align-baseline font-semibold text-info"
        title={player ? `${seat}号 ${player.name}` : `${seat}号`}
      >
        @{seat}号
      </span>,
    );

    lastIndex = regex.lastIndex;
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return (
    <span className={cn("whitespace-pre-wrap break-words", className)}>
      {parts.length > 0 ? parts : text}
    </span>
  );
}
