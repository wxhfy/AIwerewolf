"use client";

import React, { useMemo } from "react";
import { cn } from "@/lib/utils";
import { Player } from "@/types";

interface PlayerPortraitProps {
  player: Player;
  size?: "sm" | "md" | "lg" | "xl";
  isHighlighted?: boolean;
  className?: string;
}

const sizeClasses = {
  sm: "h-16 w-16",
  md: "h-24 w-24",
  lg: "h-32 w-32",
  xl: "h-48 w-48",
};

export function PlayerPortrait({ player, size = "md", isHighlighted = false, className }: PlayerPortraitProps) {
  const portraitId = Math.min(Math.max(player.portraitId || player.seat || 1, 1), 12);
  const portraitPath = `/portraits/ai/${portraitId}.webp`;

  const accentClass = useMemo(() => {
    const accents = [
      "from-amber-200/60 via-stone-100 to-rose-100/50",
      "from-sky-200/50 via-stone-100 to-amber-100/60",
      "from-emerald-200/45 via-stone-100 to-amber-100/60",
      "from-red-200/45 via-stone-100 to-zinc-200/70",
      "from-slate-200/60 via-stone-100 to-amber-100/60",
      "from-green-200/45 via-stone-100 to-stone-200/70",
      "from-teal-200/45 via-stone-100 to-amber-100/60",
      "from-zinc-200/70 via-stone-100 to-slate-100/70",
      "from-blue-200/40 via-stone-100 to-amber-100/70",
      "from-rose-200/45 via-stone-100 to-zinc-100/70",
      "from-indigo-200/40 via-stone-100 to-amber-100/60",
      "from-emerald-200/40 via-stone-100 to-amber-100/60",
    ];
    return accents[portraitId - 1] || accents[0];
  }, [portraitId]);

  return (
    <div className={cn(
      "group relative flex items-center justify-center overflow-hidden rounded-2xl",
      sizeClasses[size],
      "border border-amber-100/70 bg-gradient-to-br shadow-[0_8px_22px_rgba(72,45,19,0.12)]",
      accentClass,
      !player.alive && "grayscale opacity-60",
      isHighlighted && "ring-2 ring-primary/35 shadow-[0_0_28px_rgba(183,131,63,0.24)]",
      className
    )}>
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_16%,rgba(255,255,255,0.46),transparent_34%),linear-gradient(180deg,transparent_58%,rgba(57,35,18,0.16))]" />
      <img
        src={portraitPath}
        alt={`${player.name} 的立绘`}
        loading="lazy"
        decoding="async"
        className="relative h-full w-full object-cover transition-transform duration-500 ease-out group-hover:scale-[1.035]"
        onError={(e) => {
          (e.target as HTMLImageElement).src = "/portraits/1.svg";
        }}
      />
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-1/3 bg-gradient-to-t from-stone-950/18 to-transparent" />
      {isHighlighted && (
        <div className="absolute inset-0 rounded-2xl ring-4 ring-primary/20 motion-safe:animate-pulse" />
      )}
    </div>
  );
}
