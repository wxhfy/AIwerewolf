# Spectator Page Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign game spectator page with 极简素雅 theme, three-column editorial layout, day-night CSS transitions, and responsive breakpoints.

**Architecture:** Single-page Next.js app (`page.tsx`) composed from focused components. Theme via CSS custom properties on `:root`, toggled by `data-phase` attribute. Zero new npm dependencies. No backend changes.

**Tech Stack:** Next.js 14, TypeScript, Tailwind CSS, CSS custom properties + transitions

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `frontend/app/globals.css` | Rewrite | CSS variables, fonts, animations, day/night theme, phase attribute rules |
| `frontend/tailwind.config.ts` | Modify | Update night palette to 极简素雅 night values |
| `frontend/lib/i18n.ts` | Modify | Add 5 new keys for redesigned UI text |
| `frontend/components/ui/Badge.tsx` | Modify | Add `phase` and `speech` variants |
| `frontend/components/game/PhaseBanner.tsx` | Create | Day/night banner with icon, day counter, phase name |
| `frontend/components/game/PlayerCard.tsx` | Rewrite | Magazine-style: large seat number, name, status indicators |
| `frontend/components/game/EventItem.tsx` | Rewrite | Left color strips, bubble chat, cleaner event rendering |
| `frontend/app/page.tsx` | Rewrite | Three-column layout, PhaseBanner, responsive, day-night detection |

---

### Task 1: Theme Foundation — globals.css + Tailwind config

**Files:**
- Modify: `frontend/app/globals.css`
- Modify: `frontend/tailwind.config.ts`

- [ ] **Step 1: Rewrite globals.css with CSS variables and fonts**

Replace entire file:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@import url('https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@400;600;700&family=Noto+Sans+SC:wght@300;400;500&display=swap');

:root {
  /* Day theme (极简素雅) */
  --color-bg: #F8F5F0;
  --color-card: #FAF7F2;
  --color-primary: #8B5A2B;
  --color-primary-hover: #A67C52;
  --color-gold: #D4AF37;
  --color-village: #2E7D32;
  --color-danger: #B91C1C;
  --color-text: #2D2A24;
  --color-text-sub: #5B564D;
  --color-border: rgba(139, 90, 43, 0.10);
  --color-overlay: transparent;

  /* Typography */
  --font-display: 'Noto Serif SC', serif;
  --font-body: 'Noto Sans SC', -apple-system, BlinkMacSystemFont, sans-serif;

  /* Animation */
  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
  --ease-in-out: cubic-bezier(0.65, 0, 0.35, 1);
  --transition-daynight: 800ms;
  --transition-micro: 150ms;
  --transition-enter: 300ms;

  /* Spacing */
  --sidebar-width: 20%;
  --center-width: 60%;
}

/* Night phase overrides */
[data-phase="night"] {
  --color-bg: #E8E2D8;
  --color-card: #EDE8E0;
  --color-primary: #7A4E20;
  --color-text: #1A1816;
  --color-text-sub: #4A4540;
  --color-border: rgba(139, 90, 43, 0.15);
  --color-overlay: rgba(0, 0, 0, 0.06);
}

body {
  color: var(--color-text);
  background: var(--color-bg);
  font-family: var(--font-body);
  transition: background var(--transition-daynight) var(--ease-in-out),
              color var(--transition-daynight) var(--ease-in-out);
}

/* ---- Animations ---- */
@keyframes breathe {
  0%, 100% { opacity: 0.4; }
  50% { opacity: 1; }
}

@keyframes pulse-loading {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

@keyframes slide-in {
  from {
    opacity: 0;
    transform: translateY(-20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes scale-in {
  from { transform: scale(0.97); }
  to { transform: scale(1); }
}

.animate-breathe {
  animation: breathe 2s var(--ease-in-out) infinite;
}

.animate-slide-in {
  animation: slide-in var(--transition-enter) var(--ease-out) both;
}

.animate-scale-in {
  animation: scale-in var(--transition-micro) var(--ease-out) both;
}

.animate-pulse-loading {
  animation: pulse-loading 1.5s var(--ease-in-out) infinite;
}
```

- [ ] **Step 2: Update tailwind.config.ts night colors**

Replace the night colors block (remove old Gothic dark night vars, replace with 极简素雅 night):

```typescript
import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: "#8B5A2B",
        primaryHover: "#A67C52",
        secondary: "#2E7D32",
        accent: "#D4AF37",
        background: "#F8F5F0",
        cardBackground: "#FAF7F2",
        border: "rgba(139,90,43,0.10)",
        textPrimary: "#2D2A24",
        textSecondary: "#5B564D",
        danger: "#B91C1C",
        success: "#2E7D32",
        warning: "#D4AF37",
        info: "#3B82F6",
        nightBackground: "#E8E2D8",
        nightCardBackground: "#EDE8E0",
        nightBorder: "rgba(139,90,43,0.15)",
        nightTextPrimary: "#1A1816",
        nightTextSecondary: "#4A4540",
      },
      borderRadius: {
        card: "12px",
        button: "8px",
        badge: "14px",
      },
      fontFamily: {
        display: ['"Noto Serif SC"', "serif"],
        body: ['"Noto Sans SC"', "-apple-system", "BlinkMacSystemFont", "sans-serif"],
      },
    },
  },
  plugins: [],
  darkMode: "class",
};

export default config;
```

- [ ] **Step 3: Verify CSS compiles**

Run: `cd /home/wsl0163/code/AIWolf/AIwerewolf/frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add frontend/app/globals.css frontend/tailwind.config.ts
git commit -m "feat: add 极简素雅 theme foundation — CSS vars, fonts, day-night, animations"
```

---

### Task 2: i18n — New Translation Keys

**Files:**
- Modify: `frontend/lib/i18n.ts`

- [ ] **Step 1: Add new keys to both ZH and EN translations**

Add inside `[Language.ZH]` block (before the closing `},`):

```typescript
    night: "夜晚",
    dayLabel: "白天",
    speakerBubble: "{name}: {text}",
    loading: "加载中",
    readyHint: "点击「运行一局」开始观战",
```

Add inside `[Language.EN]` block:

```typescript
    night: "Night",
    dayLabel: "Day",
    speakerBubble: "{name}: {text}",
    loading: "Loading",
    readyHint: "Click \"Run Game\" to start spectating",
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd /home/wsl0163/code/AIWolf/AIwerewolf/frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/i18n.ts
git commit -m "feat: add i18n keys for redesigned spectator UI"
```

---

### Task 3: Badge — New Variants

**Files:**
- Modify: `frontend/components/ui/Badge.tsx`

- [ ] **Step 1: Add `phase` and `speech` variants to Badge**

Replace the `variants` object and interface:

```tsx
"use client";

import React from "react";
import { cn } from "@/lib/utils";

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: "default" | "success" | "danger" | "warning" | "info" | "phase" | "speech" | "seat" | "dead";
}

export function Badge({ className, variant = "default", ...props }: BadgeProps) {
  const variants: Record<string, string> = {
    default: "bg-primary/10 text-primary",
    success: "bg-success/10 text-success",
    danger: "bg-danger/10 text-danger",
    warning: "bg-warning/10 text-warning",
    info: "bg-info/10 text-info",
    phase: "bg-primary/8 text-primary font-display text-sm px-4 py-1.5 rounded-badge",
    speech: "bg-accent/15 text-accent animate-breathe",
    seat: "bg-primary text-white font-display text-lg rounded-full w-8 h-8 flex items-center justify-center",
    dead: "bg-text-sub/15 text-text-sub line-through",
  };

  return (
    <span
      className={cn(
        "inline-flex items-center px-3 py-1 rounded-badge text-xs font-medium",
        variants[variant],
        className
      )}
      {...props}
    />
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd /home/wsl0163/code/AIWolf/AIwerewolf/frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/components/ui/Badge.tsx
git commit -m "feat: add phase, speech, seat, dead Badge variants"
```

---

### Task 4: PhaseBanner Component

**Files:**
- Create: `frontend/components/game/PhaseBanner.tsx`

- [ ] **Step 1: Create PhaseBanner component**

```tsx
"use client";

import React from "react";
import { useAppContext } from "@/context/AppContext";
import { t, tPhase } from "@/lib/i18n";
import { Badge } from "@/components/ui/Badge";

interface PhaseBannerProps {
  day: number;
  phase: string;
  isNight: boolean;
}

export function PhaseBanner({ day, phase, isNight }: PhaseBannerProps) {
  const { language } = useAppContext();

  return (
    <div className="flex items-center justify-center gap-3 py-4">
      <div className="flex items-center gap-2">
        <span className="text-2xl" aria-hidden="true">
          {isNight ? "☽" : "☀"}
        </span>
        <span className="font-display text-xl text-textPrimary">
          {formatDayLabel(day, phase, isNight, language)}
        </span>
      </div>
      <Badge variant={isNight ? "default" : "phase"}>
        {tPhase(phase, language)}
      </Badge>
    </div>
  );
}

function formatDayLabel(
  day: number,
  phase: string,
  isNight: boolean,
  lang: string
): string {
  const phaseLabel = tPhase(phase, lang);
  const prefix = lang === "zh" ? `第${day}天` : `Day ${day}`;
  return `${prefix} · ${phaseLabel}`;
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd /home/wsl0163/code/AIWolf/AIwerewolf/frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/components/game/PhaseBanner.tsx
git commit -m "feat: add PhaseBanner component with day-night icon"
```

---

### Task 5: PlayerCard Redesign

**Files:**
- Modify: `frontend/components/game/PlayerCard.tsx`

- [ ] **Step 1: Rewrite PlayerCard with magazine editorial style**

Replace entire file:

```tsx
"use client";

import React from "react";
import { Player, Alignment } from "@/types";
import { useAppContext } from "@/context/AppContext";
import { t, tRole } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/Badge";

interface PlayerCardProps {
  player: Player;
  isSpeaking?: boolean;
  isSelected?: boolean;
  onClick?: () => void;
}

export function PlayerCard({
  player,
  isSpeaking = false,
  isSelected = false,
  onClick,
}: PlayerCardProps) {
  const { viewMode, language } = useAppContext();

  const isDead = !player.alive;
  const isWolf = player.alignment === Alignment.WOLF;
  const isVillage = player.alignment === Alignment.VILLAGE;

  const containerClass = cn(
    "relative flex flex-col items-center p-4 rounded-card border transition-all cursor-pointer select-none",
    isDead && "opacity-50 grayscale",
    isSpeaking && "border-accent shadow-[0_0_12px_rgba(212,175,55,0.25)]",
    !isSpeaking && !isDead && "border-border hover:-translate-y-0.5 hover:shadow-md",
    isSelected && "border-primary ring-1 ring-primary",
    isDead && "border-border/50"
  );

  return (
    <div className={containerClass} onClick={onClick} role="button" tabIndex={0}>
      {/* Speaking indicator */}
      {isSpeaking && (
        <div className="absolute -top-2 -right-2">
          <Badge variant="speech" className="text-xs px-2 py-0.5">
            &#x1F399;
          </Badge>
        </div>
      )}

      {/* Seat number — large editorial number */}
      <Badge variant={isDead ? "dead" : "seat"} className="mb-2">
        {isDead ? "✝" : player.seat}
      </Badge>

      {/* Name */}
      <p
        className={cn(
          "font-display text-sm font-semibold text-textPrimary text-center leading-tight",
          isDead && "text-text-sub"
        )}
      >
        {player.name}
      </p>

      {/* Role / hidden */}
      <div className="mt-1.5 text-center min-h-[20px]">
        {viewMode === "moderator" && player.role ? (
          <p
            className={cn(
              "text-xs font-medium",
              isWolf ? "text-danger" : isVillage ? "text-success" : "text-text-sub"
            )}
          >
            {tRole(player.role, language)}
          </p>
        ) : (
          <p className="text-xs text-text-sub">{t("hiddenRole", language)}</p>
        )}
      </div>

      {/* Persona label (if available) */}
      {player.persona?.style_label && (
        <p className="mt-1 text-[10px] text-text-sub italic truncate max-w-full">
          {player.persona.style_label}
        </p>
      )}

      {/* Status tag */}
      <div className="mt-2">
        {isDead ? (
          <Badge variant="dead" className="text-[10px] px-2 py-0">
            {t("dead", language)}
          </Badge>
        ) : (
          <Badge variant="success" className="text-[10px] px-2 py-0">
            {t("alive", language)}
          </Badge>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd /home/wsl0163/code/AIWolf/AIwerewolf/frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/components/game/PlayerCard.tsx
git commit -m "feat: redesign PlayerCard — magazine editorial, speaking glow, seat badge"
```

---

### Task 6: EventItem Redesign

**Files:**
- Modify: `frontend/components/game/EventItem.tsx`

- [ ] **Step 1: Rewrite EventItem with color strips and bubble chat**

Replace entire file:

```tsx
"use client";

import React from "react";
import { GameEvent, EventType } from "@/types";
import { useAppContext } from "@/context/AppContext";
import { t, tPhase, format } from "@/lib/i18n";
import { cn } from "@/lib/utils";

interface EventItemProps {
  event: GameEvent;
  index?: number;
}

const stripColor: Record<string, string> = {
  [EventType.PHASE_CHANGED]: "bg-primary/60",
  [EventType.CHAT_MESSAGE]: "bg-accent/60",
  [EventType.VOTE_CAST]: "bg-accent",
  [EventType.PLAYER_DIED]: "bg-danger/70",
  [EventType.HUNTER_SHOT]: "bg-danger/70",
  [EventType.WHITE_WOLF_KING_BOOM]: "bg-danger/70",
  [EventType.NIGHT_ACTION]: "bg-info/60",
  [EventType.PRIVATE_INFO]: "bg-info/40",
  [EventType.GAME_END]: "bg-accent",
  [EventType.GAME_START]: "bg-primary/40",
  [EventType.SYSTEM_MESSAGE]: "bg-text-sub/40",
};

export function EventItem({ event, index = 0 }: EventItemProps) {
  const { language, viewMode } = useAppContext();

  const isPrivate = event.visibility === "private" && viewMode !== "moderator";
  if (isPrivate) return null;

  const strip = stripColor[event.type] || "bg-text-sub/30";

  function content() {
    const p = event.payload;

    if (event.type === EventType.CHAT_MESSAGE) {
      return (
        <span className="text-sm text-textPrimary">
          <span className="font-medium">{p.actor_name}</span>
          <span className="text-text-sub mx-1.5">:</span>
          {p.speech}
        </span>
      );
    }

    if (event.type === EventType.PHASE_CHANGED) {
      return (
        <span className="text-xs text-text-sub italic">
          {format(t("phaseChanged", language), { phase: tPhase(p.phase, language) })}
        </span>
      );
    }

    if (event.type === EventType.VOTE_CAST) {
      return (
        <span className="text-sm text-textPrimary">
          <span className="font-medium">{p.voter_name}</span>
          <span className="text-text-sub"> &#8594; </span>
          <span className="font-medium">{p.target_name}</span>
          {p.reasoning && (
            <span className="text-text-sub ml-1">({p.reasoning})</span>
          )}
        </span>
      );
    }

    if (
      event.type === EventType.PLAYER_DIED ||
      event.type === EventType.HUNTER_SHOT ||
      event.type === EventType.WHITE_WOLF_KING_BOOM
    ) {
      return (
        <span className="text-sm text-danger font-medium">
          {format(t("died"), {
            player: p.player_name || p.target_name || "",
            reason: p.reason || event.type.toLowerCase(),
          })}
        </span>
      );
    }

    if (event.type === EventType.GAME_END) {
      return (
        <span className="text-sm font-display font-semibold text-accent">
          {format(t("wins"), {
            winner: p.winner === "village" ? t("village") : t("wolf"),
            reason: p.reason || "",
          })}
        </span>
      );
    }

    if (event.type === EventType.NIGHT_ACTION) {
      return (
        <span className="text-xs text-text-sub">
          {format(t("action"), {
            actor: p.actor_name || "?",
            action: p.action_type || "",
            target: (p.target && p.target.name) || p.target_id || t("none"),
            reasoning: p.reasoning || "",
          })}
        </span>
      );
    }

    return (
      <span className="text-xs text-text-sub">
        {p.message || JSON.stringify(p)}
      </span>
    );
  }

  return (
    <div
      className={cn(
        "flex gap-3 py-2.5 animate-slide-in",
        event.visibility === "private" && "opacity-70"
      )}
      style={{ animationDelay: `${index * 50}ms` }}
    >
      {/* Color strip */}
      <div className={cn("w-1 rounded-full flex-shrink-0", strip)} />

      {/* Content */}
      <div className="flex-1 min-w-0">{content()}</div>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd /home/wsl0163/code/AIWolf/AIwerewolf/frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/components/game/EventItem.tsx
git commit -m "feat: redesign EventItem — color strips, bubble chat, staggered animation"
```

---

### Task 7: DayBlock — Group Events by Day

**Files:**
- Create: `frontend/components/game/DayBlock.tsx`

- [ ] **Step 1: Create DayBlock component**

```tsx
"use client";

import React from "react";
import { GameEvent, EventType } from "@/types";
import { useAppContext } from "@/context/AppContext";
import { t, format } from "@/lib/i18n";
import { EventItem } from "@/components/game/EventItem";

interface DayBlockProps {
  day: number;
  events: GameEvent[];
}

export function DayBlock({ day, events }: DayBlockProps) {
  const { language } = useAppContext();

  // Find death events for the day header
  const deaths = events.filter(
    (e) =>
      e.type === EventType.PLAYER_DIED ||
      e.type === EventType.HUNTER_SHOT ||
      e.type === EventType.WHITE_WOLF_KING_BOOM
  );

  const deathLine =
    deaths.length > 0
      ? deaths
          .map((d) =>
            format(t("died"), {
              player: d.payload.player_name || d.payload.target_name || "?",
              reason: d.payload.reason || d.type.toLowerCase(),
            })
          )
          .join(" · ")
      : null;

  return (
    <div className="mb-6">
      {/* Day header */}
      <div className="flex items-center gap-3 mb-3 pb-2 border-b border-border">
        <span className="font-display text-lg font-bold text-primary">
          D{day}
        </span>
        {deathLine && (
          <span className="text-xs text-danger truncate">{deathLine}</span>
        )}
      </div>

      {/* Event list */}
      <div className="space-y-1">
        {events.map((event, index) => (
          <EventItem key={event.id || index} event={event} index={index} />
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd /home/wsl0163/code/AIWolf/AIwerewolf/frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/components/game/DayBlock.tsx
git commit -m "feat: add DayBlock component — groups events by day with death summary"
```

---

### Task 8: Page Redesign — Three-Column Layout

**Files:**
- Modify: `frontend/app/page.tsx`

- [ ] **Step 1: Rewrite page.tsx with three-column layout**

Replace entire file:

```tsx
"use client";

import React, { useState, useEffect, useRef, useMemo } from "react";
import { useAppContext } from "@/context/AppContext";
import { t, tPhase, format } from "@/lib/i18n";
import { truncate } from "@/lib/utils";
import {
  WebSocketMessage,
  WebSocketRequest,
  Language,
  AgentType,
  ViewMode,
  EventType,
  Phase,
} from "@/types";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { PhaseBanner } from "@/components/game/PhaseBanner";
import { PlayerCard } from "@/components/game/PlayerCard";
import { DayBlock } from "@/components/game/DayBlock";

export default function SpectatorPage() {
  const {
    language,
    setLanguage,
    viewMode,
    setViewMode,
    agentType,
    setAgentType,
    room,
    setRoom,
    gameState,
    setGameState,
    isPlaying,
    setIsPlaying,
    speed,
    setSpeed,
    seed,
    setSeed,
  } = useAppContext();

  const [statusTitle, setStatusTitle] = useState(t("statusReady", language));
  const wsRef = useRef<WebSocket | null>(null);

  // Detect night phase for CSS attribute
  const isNight = useMemo(() => {
    const phase = gameState?.phase || "";
    return phase.startsWith("NIGHT") || phase === Phase.NIGHT_START || phase === Phase.NIGHT_RESOLVE;
  }, [gameState?.phase]);

  // Apply data-phase to document for CSS variables
  useEffect(() => {
    document.documentElement.setAttribute("data-phase", isNight ? "night" : "day");
  }, [isNight]);

  // Create room
  async function createRoom() {
    try {
      setStatusTitle(t("statusLoading", language));
      const response = await fetch(
        `/api/rooms?name=Demo+Room&seed=${seed}&player_count=7&agent_type=${agentType}`,
        { method: "POST", headers: { Accept: "application/json" } }
      );
      if (!response.ok) throw new Error(`Failed to create room: ${response.status}`);
      const roomData = await response.json();
      setRoom(roomData);
      setStatusTitle(t("roomReady", language));
    } catch (error) {
      console.error("Failed to create room:", error);
      setStatusTitle(t("statusError", language));
    }
  }

  // Run game via WebSocket
  function runGame() {
    if (!room) {
      createRoom().then(() => setTimeout(runGame, 100));
      return;
    }
    if (wsRef.current) wsRef.current.close();
    setIsPlaying(true);
    setStatusTitle(t("statusStreaming", language));
    setGameState(null);

    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${window.location.host}/ws/rooms/${room.id}`);
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(
        JSON.stringify({
          action: "start",
          seed,
          agent_type: agentType,
          show_private: viewMode === ViewMode.MODERATOR,
          delay_ms: speed,
        } as WebSocketRequest)
      );
    };

    ws.onmessage = (event) => {
      const msg: WebSocketMessage = JSON.parse(event.data);
      if (msg.type === "room" && msg.room) setRoom(msg.room);
      if (msg.type === "snapshot" && msg.state) setGameState(msg.state);
      if (msg.type === "complete") {
        if (msg.state) setGameState(msg.state);
        if (msg.room) setRoom(msg.room);
        setIsPlaying(false);
        setStatusTitle(t("statusLoaded", language));
      }
      if (msg.type === "error") {
        console.error("WS error:", msg.message);
        setIsPlaying(false);
        setStatusTitle(t("statusError", language));
      }
    };

    ws.onerror = () => { setIsPlaying(false); setStatusTitle(t("statusError", language)); };
    ws.onclose = () => setIsPlaying(false);
  }

  // Restore room from URL
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const roomId = params.get("room");
    if (roomId && !room) {
      fetch(`/api/rooms/${roomId}`, { headers: { Accept: "application/json" } })
        .then((res) => (res.ok ? res.json() : null))
        .then((data) => { if (data) setRoom(data); })
        .catch(() => {});
    }
  }, []);

  // Group events by day
  const dayBlocks = useMemo(() => {
    if (!gameState?.events) return {};
    const blocks: Record<number, typeof gameState.events> = {};
    for (const event of gameState.events) {
      const d = event.day || 0;
      if (!blocks[d]) blocks[d] = [];
      blocks[d].push(event);
    }
    return blocks;
  }, [gameState?.events]);

  // Split players: seats 1-3 left, 4-6 right
  const leftPlayers = useMemo(
    () => (gameState?.players || []).filter((p) => p.seat <= 3),
    [gameState?.players]
  );
  const rightPlayers = useMemo(
    () => (gameState?.players || []).filter((p) => p.seat > 3),
    [gameState?.players]
  );

  const aliveCount =
    gameState?.alive_count ||
    gameState?.players.filter((p) => p.alive).length ||
    0;

  return (
    <div className="min-h-screen" style={{ background: "var(--color-bg)", transition: "background var(--transition-daynight) var(--ease-in-out)" }}>
      {/* Night overlay */}
      <div
        className="fixed inset-0 pointer-events-none z-0"
        style={{
          background: "var(--color-overlay)",
          transition: "background var(--transition-daynight) var(--ease-in-out)",
        }}
      />

      <div className="relative z-10 max-w-screen-2xl mx-auto px-4 md:px-6 lg:px-8 py-6">
        {/* === Phase Banner === */}
        <PhaseBanner
          day={gameState?.day || 0}
          phase={gameState?.phase || "SETUP"}
          isNight={isNight}
        />

        {/* === Info badges row === */}
        <div className="flex flex-wrap items-center justify-center gap-2 mb-6 -mt-2">
          <Badge variant="default">
            {t("roomLabel", language)}: {room ? truncate(room.id) : "-"}
          </Badge>
          <Badge variant="default">
            {t("gameLabel", language)}: {gameState ? truncate(gameState.id) : "-"}
          </Badge>
          <Badge variant={viewMode === "moderator" ? "warning" : "default"}>
            {viewMode === "moderator" ? t("private", language) : t("publicMode", language)}
          </Badge>
          <Badge variant="default">
            {t("aliveCount", language)}: {aliveCount} / {gameState?.players.length || 0}
          </Badge>
          {gameState?.winner && (
            <Badge variant="warning">
              {t("winner", language)}:{" "}
              {gameState.winner === "village" ? t("village", language) : t("wolf", language)}
            </Badge>
          )}
        </div>

        {/* === Main Three-Column Layout === */}
        <div className="flex flex-col lg:flex-row gap-6">
          {/* Left column — Players 1-3 */}
          <aside className="hidden lg:flex flex-col gap-3 w-full lg:w-[20%] min-w-[140px]">
            {leftPlayers.map((player) => (
              <PlayerCard key={player.id} player={player} />
            ))}
          </aside>

          {/* Center column — Controls + Timeline */}
          <main className="flex-1 lg:w-[60%] space-y-6">
            {/* Control Panel */}
            <div
              className="rounded-card p-4 md:p-6 space-y-4"
              style={{
                background: "var(--color-card)",
                border: "1px solid var(--color-border)",
                transition: "background var(--transition-daynight) var(--ease-in-out), border var(--transition-daynight) var(--ease-in-out)",
              }}
            >
              <div className="flex flex-wrap items-center gap-3">
                {/* Run button */}
                <Button
                  onClick={runGame}
                  disabled={isPlaying}
                  className={isPlaying ? "animate-pulse-loading" : ""}
                >
                  {isPlaying ? t("statusStreaming", language) : t("run", language)}
                </Button>

                {/* Language */}
                <div className="flex rounded-button border border-border overflow-hidden">
                  <button
                    onClick={() => setLanguage(Language.ZH)}
                    className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                      language === "zh" ? "bg-primary text-white" : "bg-transparent text-text-sub hover:text-textPrimary"
                    }`}
                  >
                    中文
                  </button>
                  <button
                    onClick={() => setLanguage(Language.EN)}
                    className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                      language === "en" ? "bg-primary text-white" : "bg-transparent text-text-sub hover:text-textPrimary"
                    }`}
                  >
                    EN
                  </button>
                </div>

                {/* Agent type */}
                <select
                  value={agentType}
                  onChange={(e) => setAgentType(e.target.value === "llm" ? AgentType.LLM : AgentType.HEURISTIC)}
                  disabled={isPlaying}
                  className="h-9 px-3 rounded-button border border-border text-sm text-textPrimary disabled:opacity-50"
                  style={{ background: "var(--color-bg)" }}
                >
                  <option value="heuristic">{t("agentHeuristic", language)}</option>
                  <option value="llm">{t("agentLlm", language)}</option>
                </select>

                {/* Seed */}
                <input
                  type="number"
                  value={seed}
                  onChange={(e) => setSeed(parseInt(e.target.value) || 7)}
                  disabled={isPlaying}
                  className="h-9 w-20 px-2 rounded-button border border-border text-sm text-textPrimary disabled:opacity-50"
                  style={{ background: "var(--color-bg)" }}
                  title={t("seed", language)}
                />

                {/* Speed */}
                <input
                  type="number"
                  value={speed}
                  onChange={(e) => setSpeed(parseInt(e.target.value) || 80)}
                  disabled={isPlaying}
                  className="h-9 w-20 px-2 rounded-button border border-border text-sm text-textPrimary disabled:opacity-50"
                  style={{ background: "var(--color-bg)" }}
                  title={t("speed", language)}
                />

                {/* View toggle */}
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() =>
                    setViewMode(viewMode === ViewMode.MODERATOR ? ViewMode.PUBLIC : ViewMode.MODERATOR)
                  }
                  disabled={isPlaying}
                >
                  {viewMode === ViewMode.MODERATOR ? t("public", language) : t("private", language)}
                </Button>
              </div>

              {/* Status */}
              {statusTitle && (
                <p className="text-xs text-text-sub">
                  <span className="font-medium">{statusTitle}</span>
                </p>
              )}
            </div>

            {/* Mobile players */}
            <div className="lg:hidden">
              <div className="flex gap-2 overflow-x-auto pb-2">
                {(gameState?.players || []).map((player) => (
                  <div key={player.id} className="flex-shrink-0 w-[120px]">
                    <PlayerCard player={player} />
                  </div>
                ))}
              </div>
            </div>

            {/* Event Timeline */}
            <div
              className="rounded-card p-4 md:p-6"
              style={{
                background: "var(--color-card)",
                border: "1px solid var(--color-border)",
                transition: "background var(--transition-daynight) var(--ease-in-out), border var(--transition-daynight) var(--ease-in-out)",
              }}
            >
              <h2 className="font-display text-lg font-semibold text-textPrimary mb-4">
                {t("timeline", language)}
              </h2>
              <div className="max-h-[55vh] overflow-y-auto">
                {gameState?.events.length ? (
                  Object.keys(dayBlocks)
                    .sort((a, b) => Number(b) - Number(a))
                    .map((dayKey) => (
                      <DayBlock
                        key={dayKey}
                        day={Number(dayKey)}
                        events={dayBlocks[Number(dayKey)]}
                      />
                    ))
                ) : (
                  <div className="text-center py-12 text-text-sub">
                    <p className="font-display text-lg mb-2">{t("readyHint", language)}</p>
                    <p className="text-sm">{t("statusHint", language)}</p>
                  </div>
                )}
              </div>
            </div>
          </main>

          {/* Right column — Players 4-6 */}
          <aside className="hidden lg:flex flex-col gap-3 w-full lg:w-[20%] min-w-[140px]">
            {rightPlayers.map((player) => (
              <PlayerCard key={player.id} player={player} />
            ))}
          </aside>
        </div>

        {/* Footer */}
        <footer className="mt-8 text-center text-xs text-text-sub">
          <span className="font-display">AI Werewolf</span>
          <span className="mx-2">·</span>
          <span>{t("streamingLabel", language)}</span>
        </footer>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd /home/wsl0163/code/AIWolf/AIwerewolf/frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Verify the dev server compiles without errors**

Run: `curl -s -o /dev/null -w "%{http_code}" http://localhost:3001`
Expected: 200

- [ ] **Step 4: Commit**

```bash
git add frontend/app/page.tsx
git commit -m "feat: redesign spectator page — three-column layout, PhaseBanner, day-night, responsive"
```

---

### Task 9: Smoke Test

**Files:**
- None (verification only)

- [ ] **Step 1: Verify TypeScript across entire frontend**

```bash
cd /home/wsl0163/code/AIWolf/AIwerewolf/frontend && npx tsc --noEmit
```
Expected: No errors

- [ ] **Step 2: Verify frontend serves 200**

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:3001
```
Expected: 200

- [ ] **Step 3: Verify API proxy works**

```bash
curl -s http://localhost:3001/api/health
```
Expected: `{"status":"ok"}`

- [ ] **Step 4: Check for any leftover import errors or dead code**

Run: `cd /home/wsl0163/code/AIWolf/AIwerewolf/frontend && npx tsc --noEmit 2>&1 | grep -i error | head -20`
Expected: No output

- [ ] **Step 5: Navigate to the page in browser and verify layout**

Open `http://localhost:3001` and confirm:
- Three columns visible on desktop (>1024px)
- PhaseBanner shows with sun/moon icon
- PlayerCards display with seat numbers
- Control panel is compact single-row
- Event timeline groups by day
- Resizing to tablet width switches to horizontal scroll
- Resizing to mobile width switches to single column

- [ ] **Step 6: Commit (if any cleanup needed)**

```bash
git status
```
