---
name: frontend-conventions
description: Next.js 14 App Router + React 18 + TypeScript 5 + Tailwind 3 前端开发规范
audience: claude, codex, human
version: 2.1.0
updated: 2026-05-22
---

# 前端开发规范

> v2.1 — 老的 vanilla 三件套 (`index.html` / `app.js` / `style.css`) **已删除**。前端唯一形态是 Next.js。
> v1.0 规范（"vanilla, no framework"）已彻底作废,仅在 git 历史中保留。
> 适用范围：`frontend/` 目录。

---

## 一、为什么从 vanilla 切到 Next.js

队友在 `5332bc7..aad96ec` 这 16 个 commit 里把 spectator 页重写成了三栏布局 + 7 个 React 组件 + 极简素雅 Tailwind 主题。讨论得到的结论：

| 旧（v1）痛点 | 新（v2）方案 |
|--------------|-------------|
| 单 `state` 对象 + 全 DOM 重渲染 | React 组件树 + Context，按需 re-render |
| `data-i18n` 属性扫一遍 DOM 翻译 | `useI18n()` hook + 编译期 key 检查 |
| CSS 变量手动加，类命名靠自觉 | Tailwind utility + 主题 token 集中在 `tailwind.config.ts` |
| 后端字段对错前端只能运行时炸 | `types/index.ts` 镜像后端 Enum，编译期捕获 |
| 加新 Phase 要改 HTML 模板 + JS 渲染 + CSS | 加一个 React 组件就完事 |

**v1 规范作废了**——不要再去翻 v1.0 给老的 `frontend/app.js` 加东西，新代码全走 Next.js。

---

## 二、技术栈（不要乱换版本）

| 工具 | 版本 | 用途 |
|------|------|------|
| Next.js | 14.2.x | App Router（不要切回 Pages Router） |
| React | 18.2.x | function component 风格 |
| TypeScript | 5.x | strict mode |
| Tailwind CSS | 3.4.x | utility-first 样式 |
| `clsx` + `tailwind-merge` | latest | 条件类名拼接（用 `cn()` helper） |
| Node | ≥ 18（开发用 v24） | 运行环境 |

`frontend/package.json` 是单一事实来源。**新增依赖必须**：
- PR 描述写出"为什么不能用现有依赖完成"
- 群里 +1 才合
- 优先用 zero-runtime 工具（如 `clsx` 这种），避免引入大库

**禁止**：
- 加 jQuery / Lodash / Moment / RxJS / Redux / MobX
- 切换到其他 React meta-framework（Remix / Astro / Vite）
- 引入 CSS-in-JS 库（styled-components / emotion）—— Tailwind 已经够用

---

## 三、目录结构

```
frontend/
├── app/                    # Next.js App Router
│   ├── layout.tsx          # 根布局（字体 / 全局 Provider）
│   ├── page.tsx            # /（观战台主页）
│   └── globals.css         # Tailwind base + 极少全局规则
├── components/
│   ├── ui/                 # 通用元件（Badge / Button / Card 等）
│   └── game/               # 业务组件（PhaseBanner / PlayerCard / EventItem / DayBlock）
├── lib/
│   ├── i18n.ts             # 翻译字典 + useI18n hook
│   └── utils.ts            # cn() 等工具
├── context/
│   └── AppContext.tsx      # 全局状态（语言 / 视角 / 当前对局快照 / WS 连接）
├── types/
│   └── index.ts            # 后端契约的 TS 镜像（Phase / Role / GameEvent / ...）
├── tailwind.config.ts      # 主题 token（颜色 / 字体 / borderRadius）
├── next.config.js          # Next 配置
├── tsconfig.json           # paths: "@/*" → "./*"
├── package.json
└── package-lock.json
```

### 文件命名

| 类型 | 风格 | 例 |
|------|------|----|
| 组件文件 | `PascalCase.tsx` | `PlayerCard.tsx` |
| 工具/lib 文件 | `kebab-case.ts` 或 `lowercase.ts` | `i18n.ts` / `utils.ts` |
| Hook 文件 | `useXxx.ts` | `useI18n.ts` |
| 类型文件 | `index.ts` 集中导出 | `types/index.ts` |
| Tailwind 配置 | `tailwind.config.ts`（TS 不是 JS） | — |

---

## 四、TypeScript 风格

### 严格模式必须开

`tsconfig.json` 不要降级 `strict` / `noImplicitAny` / `strictNullChecks`。
碰到类型尴尬就用 `as` / `unknown`，不要靠关 strict 来回避。

### 命名

| 对象 | 风格 |
|------|------|
| 类型 / 接口 / Enum | `PascalCase`：`PlayerCard` / `GameEvent` / `Phase` |
| 函数 / 变量 / hook | `camelCase`：`fetchSnapshot` / `useGameState` |
| 常量字典 | `camelCase`（不再用 `UPPER_SNAKE`，遵循 React 习惯） |
| Props 类型 | `XxxProps`：`PlayerCardProps` |
| 组件文件导出 | `export default`（页面/根组件）+ 命名导出（子组件） |

### `interface` vs `type`

- 对外暴露的 **对象形状** → `interface`（可被扩展）
- 联合类型 / 字面量 / 元组 / 映射 → `type`

```tsx
// 对
interface PlayerCardProps {
  player: Player;
  speaking?: boolean;
}

type Variant = "phase" | "speech" | "seat" | "dead";
```

### `any` 是红线

- `any` 仅出现在两处：第三方库无 types、`JSON.parse` 后的临时变量
- 否则用 `unknown` + 类型守卫，或显式 `as XxxType`

### 与后端契约同步

**关键铁律**：`frontend/types/index.ts` 是后端 schema 的 TS 镜像，**两边任一改了必须同步**。

```ts
// 后端 backend/engine/models.py
class Phase(str, Enum):
    NIGHT_GUARD_ACTION = "NIGHT_GUARD_ACTION"
    ...

// 前端 frontend/types/index.ts
export enum Phase {
  NIGHT_GUARD_ACTION = "NIGHT_GUARD_ACTION",
  ...
}
```

后端加 Enum 成员，前端 `types/index.ts` 同 PR 内更新——见 `skills/50-api-contract.md`。
后端 + 前端 enum 不同步 = 编译期类型 OK 但运行时 switch case 漏分支 → bug。

---

## 五、React 组件规范

### 一律 function component

```tsx
export interface PhaseBannerProps {
  phase: Phase;
  day: number;
  isNight: boolean;
}

export default function PhaseBanner({ phase, day, isNight }: PhaseBannerProps) {
  // ...
}
```

- **禁止**用 `class` 组件
- **禁止**`React.FC<Props>`（社区已弃用，多余的 children inference）
- 单个组件 < 200 行；过长就拆 sub-component 或抽 hook

### Props 解构 + 默认值

```tsx
function Badge({ variant = "phase", children }: BadgeProps) { ... }
```

避免 `props.variant` 风格——破坏可读性。

### Server vs Client component

- App Router 默认是 **Server Component**
- 用了 `useState` / `useEffect` / `useContext` / 浏览器 API → 必须在文件顶加 `"use client"`
- **观战页和实时事件流是 client side**（用 WebSocket + state），其他静态内容尽量 server

### 何时把样式抽成组件 vs 直接 Tailwind

- 重复 3+ 次的样式组合 → 抽组件（如 `Badge`）
- 一次性的容器布局 → 直接写 Tailwind class
- 不要为了"组件化"把 `<div className="text-sm text-gray-500">` 这种东西也抽组件

---

## 六、状态管理：Context API

### 全局状态在 `context/AppContext.tsx`

当前架构：单一 `AppContext` 提供：
- `lang` / `setLang`（语言）
- `showPrivate` / `setShowPrivate`（视角）
- `snapshot` / `setSnapshot`（当前对局快照）
- `ws`（WebSocket 实例）

### 不要引入 Redux / Zustand / Jotai

21 天项目体量，Context + `useState` + `useReducer` 完全够用。引入第三方状态库要 PR 描述里证明 Context 不够。

### Hook 抽取

跨多个组件复用的状态/副作用逻辑 → 抽 hook：

```ts
// lib/useGameStream.ts
export function useGameStream(roomId: string) {
  const [snapshot, setSnapshot] = useState<GameState | null>(null);
  useEffect(() => {
    const ws = new WebSocket(`/ws/rooms/${roomId}`);
    // ...
    return () => ws.close();
  }, [roomId]);
  return snapshot;
}
```

Hook 命名永远 `useXxx`，文件名 `useXxx.ts`。

---

## 七、i18n

### 字典在 `lib/i18n.ts`

```ts
import { Language } from "@/types";

const translations = {
  [Language.ZH]: { pageTitle: "AI 狼人杀", ... },
  [Language.EN]: { pageTitle: "AI Werewolf", ... },
};

export function useI18n() {
  const { lang } = useContext(AppContext);
  return (key: TranslationKey) => translations[lang][key];
}
```

### 规则

1. **所有用户可见文案**走字典，**禁止**在 JSX 里 hardcode 中/英
2. 新增 key 必须 **zh + en 同时加**，缺一编译报错（用 `keyof` 做类型）
3. key 用 `camelCase`，按语义命名（`statusReady`），不按内容（`zhClickHere`）
4. 模板字符串用 `{name}` 占位 + `format(template, { name: '小明' })` 工具

### 反例

```tsx
// 错：硬编码
<button>开始游戏</button>

// 错：字典里只加了 zh 没加 en
{ [Language.ZH]: { run: "开始游戏" } }

// 对
const t = useI18n();
<button>{t("run")}</button>
```

---

## 八、Tailwind CSS 风格

### 主题 token 集中在 `tailwind.config.ts`

```ts
theme: {
  extend: {
    colors: {
      primary: "#8B5A2B",         // 深棕
      secondary: "#2E7D32",       // 深绿
      accent: "#D4AF37",          // 金
      background: "#F8F5F0",      // 米白
      textPrimary: "#2D2A24",
      ...
    },
    fontFamily: {
      display: ['"Noto Serif SC"', "serif"],
      body: ['"Noto Sans SC"', ...],
    },
  },
}
```

### 规则

1. **禁止裸 hex/rgb 写进 JSX**：用 `bg-primary` / `text-accent` 不是 `bg-[#8B5A2B]`
2. 新增颜色 → 加到 `tailwind.config.ts`，给**语义化命名**（`wolf` / `village` / `dead`），不是 `red500`
3. 用 `cn()` 拼接条件类（来自 `lib/utils.ts`，封装 `clsx + tailwind-merge`）：

```tsx
import { cn } from "@/lib/utils";

<div className={cn(
  "rounded-card border bg-cardBackground p-4",
  speaking && "ring-2 ring-accent",
  player.is_alive ? "opacity-100" : "opacity-50 grayscale",
)} />
```

4. 行内任意值（`bg-[var(--xxx)]`、`mt-[13px]`）**仅**用于一次性微调；重复出现要进 config
5. `globals.css` 只放 `@tailwind base/components/utilities` + 3-5 行真正必须的 reset；**禁止**在里头写组件样式

### 响应式

Tailwind 断点（默认）：`sm md lg xl 2xl`。
答辩 Demo 桌面 1080p 优先，移动端最低保证不崩——用 `md:grid-cols-3 grid-cols-1` 这种渐进增强。

---

## 九、WebSocket 接入

### 当前后端端点

- `ws://host/ws/games`
- `ws://host/ws/rooms/{room_id}` (推荐)

详见 `skills/50-api-contract.md`。

### 客户端模式

```ts
"use client";
function GameStream({ roomId }: { roomId: string }) {
  const [snapshot, setSnapshot] = useState<GameState | null>(null);
  useEffect(() => {
    const ws = new WebSocket(`${wsBase()}/ws/rooms/${roomId}`);
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data) as ServerMessage;
        if (msg.type === "snapshot") setSnapshot(msg.state);
      } catch { /* ignore parse errors */ }
    };
    return () => ws.close();
  }, [roomId]);
  return <Spectator snapshot={snapshot} />;
}
```

### 必守

- 一个 roomId **只开一个 WebSocket**（在 `useEffect` 的 cleanup 里 `close()`）
- **指数退避重连**（1s → 2s → 4s → max 30s）
- 切换语言 / 视角 **不**重连
- 每个 message `try/catch JSON.parse`
- 断线后用 `GET /api/rooms/{room_id}/snapshot` 拉一次最新状态，**不要**重放历史 ws 消息

---

## 十、构建、运行、部署

### 本地开发

```bash
cd frontend
npm install --legacy-peer-deps     # eslint 版本与 next 有 peer 冲突,加这个 flag
npm run dev                        # 起在 :3001（同机有人占就改 -p 3002）
```

后端：`uvicorn :8000` 提供 API + WS。前端 dev server `:3001` 通过 `next.config.js` 的 rewrites/proxy 转发 `/api/*` 和 `/ws/*` 到后端（如未配，需要 fetch 写绝对 URL 或在 client 用 `NEXT_PUBLIC_API_BASE`）。

### 生产构建

```bash
npm run build      # → .next/
npm run start      # 起 next start，:3001
```

或者通过 `docker compose up`（参见 `docker-compose.yml`）。

---

## 十一、与后端的契约（铁律）

任何前端改动碰到下列文件，**同 PR 内必须**同步动 `skills/50-api-contract.md`：

- `frontend/types/index.ts`（Enum / interface）
- 调 `fetch('/api/...')` 或 `new WebSocket('/ws/...')` 的逻辑

后端改 schema 没同步前端 → 前端编译时类型 OK 但运行时 NaN / undefined → 真实 bug。
**强制**：API 字段名两边都用 `snake_case`（不要前端转 camelCase）。

---

## 十二、AI 改前端的红线

让 AI 写 Next.js 代码时，**至少检查**：

- [ ] 有 `"use client"` 标记（如果用了 hook / browser API）
- [ ] Props 有显式 `interface`，没出现 `any`
- [ ] 用 `cn()` 拼条件类，没用 string template + `&&`
- [ ] 文案走 `useI18n()`，zh + en 都加了
- [ ] Tailwind 颜色用 token（`bg-primary`），没裸 hex
- [ ] 新加 Enum / interface 同步改了 `types/index.ts`
- [ ] 新加 API 字段同步改了 `skills/50-api-contract.md`
- [ ] WebSocket 在 `useEffect` cleanup 里 `close()`
- [ ] 没引入 Redux / styled-components / 大库
- [ ] 单组件 < 200 行
- [ ] 文件名 `PascalCase.tsx`（组件）/ `camelCase.ts`（lib）
- [ ] 没改 v1 vanilla 三件套（已被删除,不会再出现）
- [ ] 没留 `console.log` debug 输出

详见 `skills/70-ai-collaboration.md`。

---

*Version 2.1.0 — 2026-05-22 — vanilla 三件套已删除,Next.js 是唯一前端。v2.0 (并行过渡期版) 和 v1 (vanilla) 规范保留在 git 历史。*
