"use client";

import React from "react";
import { cn } from "@/lib/utils";
import { Player } from "@/types";
import { PlayerPortrait } from "@/components/game/PlayerPortrait";

export interface SpeechCardProps {
  /** 玩家信息 */
  player?: Player;
  /** 玩家座位号（兼容旧版） */
  seat?: number;
  /** 玩家姓名（兼容旧版） */
  name: string;
  /** 发言正文 */
  children: React.ReactNode;
  /** 当前正在发言（高亮卡片） */
  isSpeaking?: boolean;
  /** header 右侧额外内容（如 "发言中" 标签） */
  headerRight?: React.ReactNode;
  /** 附加样式 */
  className?: string;
}

/**
 * 发言卡片共享骨架 — ChatBubble 和 ThinkingBubble 共用。
 *
 * 结构：
 *   ┌─ header: 座位号 + 姓名 + 右侧状态 ─┐
 *   │                                     │
 *   │  body: 发言正文 / 思考占位           │
 *   └─────────────────────────────────────┘
 */
export function SpeechCard({ player, seat, name, children, isSpeaking, headerRight, className }: SpeechCardProps) {
  const displaySeat = seat ?? player?.seat;
  const displayName = player?.name || name;
  
  return (
    <div className={cn("py-1.5 animate-slide-in", className)}>
      <div
        className={cn(
          "rounded-xl overflow-hidden transition-shadow duration-300 flex",
          "bg-cardBackground/95 border border-border/80",
          isSpeaking && "border-primary/50 bg-primary/[0.04] shadow-[0_0_16px_rgb(var(--color-primary-rgb)/0.08)]",
        )}
      >
        {/* 立绘区域 - 左侧 */}
        {player && (
          <div className="shrink-0 p-3 border-r border-border/50">
            <PlayerPortrait 
              player={player} 
              size="md" 
              isHighlighted={isSpeaking}
            />
          </div>
        )}

        {/* 内容区域 - 右侧 */}
        <div className="flex-1 min-w-0">
          {/* Header */}
          <div className="flex items-center gap-2 px-4 pt-3 pb-1.5">
            {displaySeat != null && (
              <span className="text-sm font-semibold text-primary/70 tabular-nums tracking-wide">
                {displaySeat}号
              </span>
            )}
            <span className="text-base font-medium text-textPrimary">{displayName}</span>
            {headerRight && (
              <span className="text-xs text-primary font-medium animate-pulse">
                {headerRight}
              </span>
            )}
          </div>

          {/* Body */}
          <div className="px-4 pb-3 text-base leading-relaxed whitespace-pre-wrap break-words">
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}
