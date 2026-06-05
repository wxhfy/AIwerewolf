"use client";

import React from "react";
import { cn } from "@/lib/utils";
import { Phase, EventType } from "@/types";

// ── Decorative SVG elements for 100% design restoration ───────────────
// 装饰元素：星光、菱形、箭头等，完全匹配设计图
const Decor = {
  // 大阶段左右的小菱形装饰
  diamond: (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M6 0L7.5 4.5L12 6L7.5 7.5L6 12L4.5 7.5L0 6L4.5 4.5L6 0Z" fill="currentColor" opacity="0.6"/>
    </svg>
  ),
  // 小星光装饰
  star: (
    <svg width="10" height="10" viewBox="0 0 10 10" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M5 0L5.5 2.5L8 2L6 4L8.5 5.5L5.5 5.5L5 8L4.5 5.5L1.5 5.5L4 4L2 2L4.5 2.5L5 0Z" fill="currentColor" opacity="0.7"/>
    </svg>
  ),
  // 两端箭头装饰
  arrowLeft: (
    <svg width="16" height="12" viewBox="0 0 16 12" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M16 6H2M2 6L6 10M2 6L6 2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" opacity="0.5"/>
    </svg>
  ),
  arrowRight: (
    <svg width="16" height="12" viewBox="0 0 16 12" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M0 6H14M14 6L10 2M14 6L10 10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" opacity="0.5"/>
    </svg>
  ),
  // 角色阶段两端装饰
  sideDotLeft: (
    <svg width="8" height="12" viewBox="0 0 8 12" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M8 6H2M2 6L5 9M2 6L5 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" opacity="0.4"/>
    </svg>
  ),
  sideDotRight: (
    <svg width="8" height="12" viewBox="0 0 8 12" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M0 6H6M6 6L3 9M6 6L3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" opacity="0.4"/>
    </svg>
  ),
  // 月牙图标（天黑请闭眼用）
  moon: (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
    </svg>
  ),
  // 太阳图标（天亮了用）
  sun: (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="5"/>
      <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>
    </svg>
  ),
};

// ── Role icon SVGs ────────────────────────────────────────────────────
// 保持线性、低饱和、非卡通风格，符合设计要求
const RoleIcon: Record<string, React.ReactNode> = {
  guard: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2L3 6v6c0 6 3.5 10.5 9 12 5.5-1.5 9-6 9-12V6L12 2z"/>
      <path d="M9 12l2 2 4-4" strokeWidth="2"/>
    </svg>
  ),
  wolf: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 4c-3 5-7 7-9 9l2 8h14l2-8c-2-2-6-4-9-9z"/>
      <circle cx="9.5" cy="10" r="1" fill="currentColor" opacity="0.6"/>
      <circle cx="14.5" cy="10" r="1" fill="currentColor" opacity="0.6"/>
    </svg>
  ),
  witch: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3l-3 8h6l-3-8z"/>
      <rect x="6" y="20" width="12" height="2" rx="1"/>
      <rect x="10" y="11" width="4" height="9" rx="1"/>
    </svg>
  ),
  seer: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="9"/>
      <circle cx="12" cy="12" r="3.5"/>
      <path d="M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21"/>
    </svg>
  ),
  hunter: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
      <path d="M9 12l2 2 4-4" strokeWidth="2"/>
    </svg>
  ),
  sheriff: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2z"/>
    </svg>
  ),
  death: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z"/>
      <path d="M15 9l-6 6M9 9l6 6"/>
    </svg>
  ),
  success: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
      <path d="M22 4L12 14.01 9 11.01"/>
    </svg>
  ),
};

const ROLE_PHASES: Record<string, { icon: keyof typeof RoleIcon; color: string }> = {
  [Phase.NIGHT_GUARD_ACTION]: { icon: "guard", color: "text-primary/90" },
  [Phase.NIGHT_WOLF_ACTION]: { icon: "wolf", color: "text-danger/90" },
  [Phase.NIGHT_WITCH_ACTION]: { icon: "witch", color: "text-purple-600 dark:text-purple-400/90" },
  [Phase.NIGHT_SEER_ACTION]: { icon: "seer", color: "text-info/90" },
  [Phase.HUNTER_SHOOT]: { icon: "hunter", color: "text-emerald-700 dark:text-emerald-400/90" },
};

// 大阶段枚举，使用PhaseDivider组件
const MAJOR_PHASES = new Set([
  Phase.NIGHT_START,
  Phase.NIGHT_RESOLVE,
  Phase.DAY_START,
  Phase.DAY_SPEECH,
  Phase.DAY_VOTE,
  Phase.GAME_END,
  "GAME_START",
]);

// 结算结果关键词，使用ResultNotice组件
const RESULT_KEYWORDS = [
  "死亡", "出局", "平安夜", "当选警长", "警徽", "投票平局", "PK", "自爆", "带走",
  "died", "eliminated", "no one died", "sheriff", "tie", "PK", "self-destruct", "take"
];

// ── 组件1: 大阶段提示 ───────────────────────────────────────────────────
// 居中流程分割节点，细线、轻量装饰、暖金色边框，完全还原设计图
interface PhaseDividerProps {
  children: React.ReactNode;
}
function PhaseDivider({ children }: PhaseDividerProps) {
  const content = String(children);
  // 根据内容显示对应图标
  let icon = null;
  if (content.includes("天黑") || content.includes("Night")) icon = Decor.moon;
  if (content.includes("天亮") || content.includes("Day")) icon = Decor.sun;

  return (
    <div className="flex items-center justify-center gap-2 py-5 select-none">
      {/* 左侧装饰线 + 菱形 */}
      <div className="flex items-center gap-1 flex-1 justify-end">
        <div className="h-px flex-1 bg-gradient-to-l from-transparent via-accent/45 to-transparent max-w-[60px]" />
        <span className="text-accent/85">{Decor.diamond}</span>
        <span className="text-accent/60">{Decor.arrowLeft}</span>
      </div>

      {/* 主体标签 */}
      <div className="relative px-6 py-2.5 rounded-full border border-accent/45 bg-gradient-to-r from-accent/12 via-accent/8 to-accent/12 font-display text-sm font-bold tracking-[0.1em] text-accent shadow-sm flex items-center gap-2">
        {/* 上下星光装饰 */}
        <span className="absolute -top-2 left-1/2 -translate-x-1/2 text-accent/85">{Decor.star}</span>
        {icon && <span className="text-accent/95">{icon}</span>}
        {children}
        <span className="absolute -bottom-2 left-1/2 -translate-x-1/2 text-accent/85">{Decor.star}</span>
      </div>

      {/* 右侧装饰线 + 菱形 */}
      <div className="flex items-center gap-1 flex-1 justify-start">
        <span className="text-accent/60">{Decor.arrowRight}</span>
        <span className="text-accent/85">{Decor.diamond}</span>
        <div className="h-px flex-1 bg-gradient-to-r from-transparent via-accent/45 to-transparent max-w-[60px]" />
      </div>
    </div>
  );
}

// ── 组件2: 角色阶段提示 ───────────────────────────────────────────────────
// 小一号角色流程标签，带线性SVG图标，高级低饱和，完全还原设计图
interface RolePhaseMarkerProps {
  icon: React.ReactNode;
  children: React.ReactNode;
  color?: string;
}
function RolePhaseMarker({ icon, children, color = "text-text-sub/80" }: RolePhaseMarkerProps) {
  return (
    <div className="flex justify-center items-center gap-1 py-3 select-none">
      {/* 左侧装饰 */}
      <span className={cn("text-current/65", color)}>{Decor.sideDotLeft}</span>
      
      {/* 主体标签 */}
      <div className={cn(
        "px-4 py-1.5 rounded-full border border-current/30 bg-current/8 flex items-center gap-2",
        color
      )}>
        <span className="shrink-0">
          {icon}
        </span>
        <span className="font-display text-[13px] font-semibold tracking-[0.06em]">
          {children}
        </span>
      </div>
      
      {/* 右侧装饰 */}
      <span className={cn("text-current/65", color)}>{Decor.sideDotRight}</span>
    </div>
  );
}

// ── 组件3: 结算结果提示 ───────────────────────────────────────────────────
// 轻量公告样式，比普通文本突出，非按钮，完全还原设计图
interface ResultNoticeProps {
  icon?: React.ReactNode;
  children: React.ReactNode;
  variant?: "default" | "success" | "danger" | "warning";
}
function ResultNotice({ icon, children, variant = "default" }: ResultNoticeProps) {
  const variantStyles = {
    default: "border-accent/35 bg-gradient-to-r from-accent/12 via-accent/7 to-accent/12 text-accent",
    success: "border-success/35 bg-gradient-to-r from-success/12 via-success/7 to-success/12 text-success",
    danger: "border-danger/35 bg-gradient-to-r from-danger/12 via-danger/7 to-danger/12 text-danger",
    warning: "border-warning/35 bg-gradient-to-r from-warning/12 via-warning/7 to-warning/12 text-warning",
  };

  const colorClass = variantStyles[variant].split(" ").pop() || "text-accent";

  return (
    <div className="flex justify-center items-center gap-2 py-3 select-none">
      {/* 左侧菱形装饰 */}
      <span className={cn("text-current/75", colorClass)}>{Decor.diamond}</span>
      
      {/* 主体公告 */}
      <div className={cn(
        "px-5 py-2.5 rounded-lg border font-medium text-sm flex items-center gap-2.5 max-w-[85%]",
        variantStyles[variant]
      )}>
        {icon && <span className="shrink-0">{icon}</span>}
        <span>{children}</span>
      </div>
      
      {/* 右侧菱形装饰 */}
      <span className={cn("text-current/75", colorClass)}>{Decor.diamond}</span>
    </div>
  );
}

// ── 组件4: 普通行动说明 ───────────────────────────────────────────────────
// 左对齐，细竖线，轻量展示
interface ActionNoteProps {
  children: React.ReactNode;
}
function ActionNote({ children }: ActionNoteProps) {
  return (
    <div className="pl-4 py-2 border-l-2 border-accent/30 select-none">
      <span className="text-sm text-text-sub/90">{children}</span>
    </div>
  );
}

// ── 主组件 ──────────────────────────────────────────────────────────
interface PhasePlaqueProps {
  children: React.ReactNode;
  eventType?: string;
  phase?: string;
}

export function PhasePlaque({ children, eventType, phase }: PhasePlaqueProps) {
  const content = String(children);

  // 1. 大阶段提示
  if (phase && MAJOR_PHASES.has(phase as Phase) || eventType === EventType.GAME_START || eventType === EventType.GAME_END) {
    return <PhaseDivider>{children}</PhaseDivider>;
  }

  // 2. 角色阶段提示
  const roleConfig = phase ? ROLE_PHASES[phase] : undefined;
  if (roleConfig) {
    return (
      <RolePhaseMarker icon={RoleIcon[roleConfig.icon]} color={roleConfig.color}>
        {children}
      </RolePhaseMarker>
    );
  }

  // 3. 结算结果提示
  const isResult = RESULT_KEYWORDS.some(keyword => content.includes(keyword));
  if (isResult) {
    let variant: ResultNoticeProps["variant"] = "default";
    let icon: React.ReactNode | undefined;

    if (content.includes("死亡") || content.includes("出局") || content.includes("died") || content.includes("eliminated")) {
      variant = "danger";
      icon = RoleIcon.death;
    } else if (content.includes("平安夜") || content.includes("no one died")) {
      variant = "success";
      icon = RoleIcon.success;
    } else if (content.includes("警长") || content.includes("sheriff")) {
      variant = "warning";
      icon = RoleIcon.sheriff;
    } else if (content.includes("PK") || content.includes("平局") || content.includes("tie")) {
      variant = "warning";
    }

    return <ResultNotice icon={icon} variant={variant}>{children}</ResultNotice>;
  }

  // 4. 普通行动说明
  return <ActionNote>{children}</ActionNote>;
}

// 导出子组件方便外部使用
export { PhaseDivider, RolePhaseMarker, ResultNotice, ActionNote };
