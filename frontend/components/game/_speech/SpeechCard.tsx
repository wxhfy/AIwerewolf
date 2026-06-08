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
  testId?: string;
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
export function SpeechCard({ player, seat, name, children, isSpeaking, headerRight, className, testId }: SpeechCardProps) {
  const displaySeat = seat ?? player?.seat;
  const displayName = player?.name || name;
  
  return (
    <div className={cn("py-1.5 animate-slide-in", className)} data-testid={testId}>
      <div
        className={cn(
          // 基础样式
          "speech-card rounded-2xl overflow-hidden transition-all duration-300 flex",
          // 白天：暖白底 + 微妙边框 + 柔和阴影
          "bg-[#FFFBF7] border border-amber-100/60",
          "shadow-[0_2px_8px_rgba(0,0,0,0.06),0_1px_2px_rgba(0,0,0,0.04)]",
          "text-gray-700",
          // 正在发言时的高亮
          isSpeaking && "shadow-xl ring-2 ring-primary/25 border-primary/30",
        )}
      >
        {/* 立绘区域 - 左侧 */}
        {player && (
          <div className="speech-card-portrait shrink-0 p-3 bg-amber-50/40">
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
              <span className="speech-card-seat text-sm font-semibold text-amber-700 tabular-nums tracking-wide">
                {displaySeat}号
              </span>
            )}
            <span className="speech-card-name text-base font-medium text-gray-800">{displayName}</span>
            {headerRight && (
              <span className="text-xs text-primary font-medium animate-pulse">
                {headerRight}
              </span>
            )}
          </div>

          {/* Body */}
          <div className="speech-card-body px-4 pb-3 text-base leading-relaxed whitespace-pre-wrap break-words text-gray-700">
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}
