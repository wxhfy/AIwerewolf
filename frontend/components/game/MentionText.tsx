"use client";

import React from "react";
import { Player } from "@/types";
import { cn } from "@/lib/utils";

interface MentionTextProps {
  text: string;
  players?: Player[];
  className?: string;
}

function PlayerAvatar({ player }: { player: Player }) {
  const initials = player.name?.slice(0, 1) || String(player.seat);

  return (
    <span className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-info/15 text-[9px] font-bold text-info ring-1 ring-info/20">
      {initials}
    </span>
  );
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
        className="mx-0.5 inline-flex items-center gap-1 align-baseline text-[0.92em] font-semibold text-info"
        title={player ? `${seat}号 ${player.name}` : `${seat}号`}
      >
        {player && <PlayerAvatar player={player} />}
        <span>@{seat}号</span>
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
