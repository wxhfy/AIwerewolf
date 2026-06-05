"use client";

import React from "react";
import { cn } from "@/lib/utils";
import { Player } from "@/types";

interface PlayerPortraitProps {
  player: Player;
  size?: "sm" | "md" | "lg" | "xl";
  isHighlighted?: boolean;
  className?: string;
}

const sizeClasses = {
  sm: "w-16 h-24",
  md: "w-24 h-36",
  lg: "w-32 h-48",
  xl: "w-48 h-72",
};

export function PlayerPortrait({ player, size = "md", isHighlighted = false, className }: PlayerPortraitProps) {
  // 优先使用portraitId，否则用seat号
  const portraitId = player.portraitId || player.seat;
  // 容错：如果没有立绘，显示默认1号
  const portraitPath = `/portraits/${Math.min(Math.max(portraitId, 1), 12)}.svg`;
  
  return (
    <div className={cn(
      "relative flex items-center justify-center",
      sizeClasses[size],
      !player.alive && "grayscale opacity-60",
      isHighlighted && "animate-pulse",
      className
    )}>
      <img 
        src={portraitPath} 
        alt={`${player.name} 的立绘`}
        className="w-full h-full object-contain"
        onError={(e) => {
          // 加载失败时显示备用1号立绘
          (e.target as HTMLImageElement).src = "/portraits/1.svg";
        }}
      />
      {isHighlighted && (
        <div className="absolute inset-0 rounded-lg ring-4 ring-primary/30 animate-pulse" />
      )}
    </div>
  );
}
