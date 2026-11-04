"use client";

import React from "react";
import { cn } from "@/lib/utils";
import { Phase, EventType } from "@/types";

// Restrained line icons for major phase dividers.
const PhaseIcon = {
  moon: (
    <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  ),
  sun: (
    <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="5" />
      <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" />
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
  [Phase.NIGHT_WITCH_ACTION]: { icon: "witch", color: "text-info" },
  [Phase.NIGHT_SEER_ACTION]: { icon: "seer", color: "text-info/90" },
  [Phase.HUNTER_SHOOT]: { icon: "hunter", color: "text-success" },
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

interface PhaseDividerProps {
  children: React.ReactNode;
}

function PhaseDivider({ children }: PhaseDividerProps) {
  const content = String(children);
  const icon = content.includes("天黑") || content.includes("Night")
    ? PhaseIcon.moon
    : content.includes("天亮") || content.includes("Day")
      ? PhaseIcon.sun
      : null;

  return (
    <div className="flex items-center gap-3 py-4">
      <span aria-hidden="true" className="h-px min-w-3 flex-1 bg-border" />
      <div className="flex max-w-[85%] items-center justify-center gap-2 rounded-badge border border-border bg-primary/5 px-3 py-1.5 text-center font-display text-xs font-semibold leading-relaxed text-primary sm:px-4 sm:text-sm">
        {icon && <span aria-hidden="true" className="shrink-0">{icon}</span>}
        <span className="break-words">{children}</span>
      </div>
      <span aria-hidden="true" className="h-px min-w-3 flex-1 bg-border" />
    </div>
  );
}

interface RolePhaseMarkerProps {
  icon: React.ReactNode;
  children: React.ReactNode;
  color?: string;
}

function RolePhaseMarker({ icon, children, color = "text-text-sub" }: RolePhaseMarkerProps) {
  return (
    <div className={cn("flex items-center justify-center gap-2 py-2.5", color)}>
      <span aria-hidden="true" className="shrink-0">{icon}</span>
      <span className="text-center text-xs font-medium leading-relaxed">{children}</span>
    </div>
  );
}

interface ResultNoticeProps {
  icon?: React.ReactNode;
  children: React.ReactNode;
  variant?: "default" | "success" | "danger" | "warning";
}

function ResultNotice({ icon, children, variant = "default" }: ResultNoticeProps) {
  const variantStyles = {
    default: "border-border bg-primary/5 text-textPrimary",
    success: "border-success/20 bg-success/5 text-success",
    danger: "border-danger/20 bg-danger/5 text-danger",
    warning: "border-warning/20 bg-warning/5 text-warning",
  };

  return (
    <div className="flex justify-center py-2.5">
      <div className={cn("flex w-full max-w-lg items-start gap-2.5 rounded-button border px-3 py-2.5 text-sm font-medium leading-relaxed sm:px-4", variantStyles[variant])}>
        {icon && <span aria-hidden="true" className="mt-0.5 shrink-0">{icon}</span>}
        <span className="min-w-0 break-words">{children}</span>
      </div>
    </div>
  );
}

interface ActionNoteProps {
  children: React.ReactNode;
}

function ActionNote({ children }: ActionNoteProps) {
  return (
    <div className="my-1 border-l-2 border-border py-1.5 pl-3">
      <span className="text-xs leading-relaxed text-text-sub">{children}</span>
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
