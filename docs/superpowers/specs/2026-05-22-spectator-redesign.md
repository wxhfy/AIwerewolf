# Spectator Page Redesign — Design Spec

- **Date**: 2026-05-22
- **Scope**: P02 对局观战页 (Game Spectator Page) only
- **Backend**: No changes

## Decisions

| Dimension | Choice |
|-----------|--------|
| Theme | 极简素雅 (Minimal Elegant) — doc §4 方案四 |
| Layout | Three-column (doc §4.6) — 20% / 60% / 20% |
| Design language | Ultra-minimal Chinese elegance, magazine editorial style |
| Typography | Noto Serif SC (display) + Noto Sans SC (body) |
| Motion | CSS-only, subtle, 150ms micro / 800ms day-night transition |
| Responsive | Desktop 3-col / Tablet horizontal-scroll / Mobile single-col (doc §5.3) |

## Architecture

Single Next.js page (`page.tsx`) composed from shared components. No new dependencies.

```
page.tsx (SpectatorPage)
├── PhaseBanner           — day/night indicator, phase name, day counter
├── ControlPanel          — run button, seed, speed, agent type, view toggle
├── PlayerSeat × N        — player cards (left + right columns)
├── EventTimeline         — scrollable event feed grouped by day
│   └── DayBlock × N      — day header + EventItem list
│       └── EventItem × N — single event with type-specific rendering
└── StatusBar             — alive count, winner, event count
```

Files to modify:
- `frontend/app/page.tsx` — new layout structure
- `frontend/components/game/PlayerCard.tsx` — redesigned player card
- `frontend/components/game/EventItem.tsx` — type-specific event rendering
- `frontend/components/ui/Badge.tsx` — phase badges
- `frontend/app/globals.css` — theme variables, fonts, anim
- `frontend/lib/i18n.ts` — new translation keys
- `frontend/tailwind.config.*` — theme colors

## Color System

```css
--color-bg:        #F8F5F0;
--color-card:       #FAF7F2;
--color-primary:    #8B5A2B;
--color-gold:       #D4AF37;
--color-village:    #2E7D32;
--color-danger:     #B91C1C;
--color-text:       #2D2A24;
--color-text-sub:   #5B564D;
--color-border:     rgba(139, 90, 43, 0.10);

/* Night mode */
--color-bg-night:   #E8E2D8;
--color-card-night: #EDE8E0;
--color-overlay-night: rgba(0, 0, 0, 0.08);
```

## Component States

### PlayerCard
- **Alive**: warm brown thin border, color avatar
- **Dead**: grayscale filter + opacity 0.5 + death marker
- **Speaking**: golden border + 2s breathing animation + avatar subtle scale
- **Public view**: role hidden (icon)
- **Moderator view**: role name + alignment color indicator

### EventItem
- Left color strip by type: brown (phase), gold (vote), red (death), purple (night action)
- Chat messages: bubble style ("speaker: content")
- DayBlock header: "D{N}" badge + death summary line

### PhaseBanner
- Day: cream bg + sun icon + "第{N}天 · {phase}"
- Night: darkened bg + moon icon + "第{N}天 · {phase}"

## Day/Night Transition

800ms CSS transition on body-level CSS variables:
- Background, card, text colors fade between day/night values
- Semi-transparent overlay dims non-interactive areas at night
- PhaseBanner icon swaps from sun to moon

## Animation Spec

| Trigger | Duration | Effect |
|---------|----------|--------|
| Button click | 150ms | scale(0.97) + color deepen |
| Card hover | 150ms | translateY(-2px) + shadow deepen |
| Vote target select | 150ms | border gold transition |
| Speaking glow | 2s loop | opacity 0.4↔1.0, scale 0.98↔1.02 |
| Event enter | 300ms | slide-down 20px + fade in |
| Day-night switch | 800ms | global color gradient |
| Button loading | infinite | pulse opacity animation |

## Responsive (doc §5.3)

| Breakpoint | Layout |
|------------|--------|
| >1024px | 3-column: players-left (20%) + center (60%) + players-right (20%) |
| 768-1024px | Control top bar + player horizontal scroll + event feed below |
| <768px | Collapsible control + player scroll + full-width event feed |

## Scope Boundaries

- **In scope**: `page.tsx`, `PlayerCard.tsx`, `EventItem.tsx`, `globals.css`, `i18n.ts`, Tailwind config
- **Not in scope**: `app.js` (legacy page), new pages (lobby, settlement, etc.), backend changes, new npm dependencies
- **Backward-compatible**: WebSocket message types and API calls unchanged
