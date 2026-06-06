# Frontend Quality Foundation Design

## Goal
Improve the frontend quality foundation without changing core product behavior or redesigning the visual direction.

## Scope
This pass focuses on low-risk, high-leverage improvements:

1. Tighten frontend types around lobby preparation, pending human input, player persona data, and game page helpers.
2. Lightly split `frontend/app/room/[id]/play/page.tsx` by extracting pure helpers and focused UI/logic units where the boundary is obvious.
3. Move obvious user-visible strings from local inline translation helpers into `frontend/lib/i18n.ts`.
4. Replace suspicious Tailwind classes and repeated raw colors with supported classes or semantic tokens.
5. Fix clear accessibility issues: keyboard activation for clickable cards, dialog semantics, and missing labels on key controls.

## Non-goals
- Do not introduce new dependencies.
- Do not redesign the spectator UI.
- Do not rewrite the WebSocket architecture.
- Do not perform a full mobile layout redesign.
- Do not change backend contracts.

## Architecture
Keep the current Next.js App Router structure. The existing page remains the route owner, but responsibilities should move into small units when it reduces risk:

- Pure phase utilities can live near the play page or in a small frontend helper module.
- Pure UI fragments such as the game end panel can become `components/game/*` components.
- Shared labels should use `frontend/lib/i18n.ts`.
- Type additions should go into `frontend/types/index.ts` and mirror existing backend response shapes without changing API field names.

## Data Flow
Current fetch/WebSocket flows remain unchanged:

- Lobby creates/prepares rooms through existing REST endpoints.
- Play page starts/receives games through the existing room WebSocket.
- Human actions still post to `/api/rooms/{roomId}/action`.

Type changes document these flows; they must not transform snake_case API fields into camelCase.

## Error Handling
Keep current error surfaces, but remove debug-only `console.error` where user-facing status already exists or replace with a visible status update if needed. Do not add broad fallback behavior that hides real failures.

## Accessibility
- Clickable player cards must be keyboard-operable with Enter and Space.
- Modal panels should declare `role="dialog"` and `aria-modal="true"`.
- Icon-only controls and important floating controls should have descriptive labels.
- Existing reduced-motion support should be preserved.

## Styling
- Keep the current warm day / dark night theme.
- Replace unsupported or suspicious utilities such as `active:scale-98` and `bg-primary/8`.
- Prefer Tailwind tokens and CSS variables over raw hex/rgba in JSX.
- Do not move more component styles into `globals.css` unless they are genuinely global tokens or utilities.

## Validation
Run:

- `npm run build --prefix frontend`
- `npm run lint --prefix frontend` if available in the current dependency setup

Manual browser validation should cover:

- Lobby rendering and modal semantics
- Creating/starting a room
- Play page initial load
- Day/night phase visual state
- Keyboard activation on player cards
- Game-over panel rendering
