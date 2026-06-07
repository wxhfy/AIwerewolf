# Game Page Redesign — 对齐 wolfcha 视觉风格

> **Date**: 2026-05-27
> **Scope**: 仅 `/room/[id]/play` 对局页面
> **Constraint**: 后端接口不变，只改视觉层

## 1. 目标

将游戏对局页面的视觉风格全面对齐 wolfcha 项目（`/home/wsl0163/code/AIWolf/wolfcha/`），包括：
- 设计系统（CSS 变量、glass morphism、色板）
- 组件视觉（PlayerCard、DialogArea、BottomActionPanel 等）
- 布局结构（三栏 + 角色立绘区）
- 动画和微交互

**不改动**：后端 API 接口、WebSocket 协议、组件逻辑、状态管理

## 2. 设计系统同步

### 2.1 核心色板

从 wolfcha `globals.css` 同步以下 CSS 变量到我们的 `globals.css`：

```css
:root {
  /* 品牌色 */
  --color-blood: #8a1c1c;
  --color-blood-light: #b93636;
  --color-gold: #c5a059;
  --color-gold-dim: #8c7335;
  --color-gold-dark: #6e5626;
  --paper: #f0e6d2;

  /* Day 背景 */
  --bg-main: #f5f0e6;
  --bg-day-main: #f5f0e6;
  --bg-secondary: #ede6d6;
  --bg-card: #ffffff;
  --bg-dark: #1a1614;
  --bg-hover: #e8dfcc;
  --bg-selected: #fcfbf9;
  --bg-day-from: #fdfbf7;
  --bg-day-via: #f2ebe0;
  --bg-day-to: #e6ded1;

  /* Night 背景 */
  --bg-dark: #1a1614;
  --bg-dark-secondary: #2c241b;
  --bg-night-from: #1a1614;
  --bg-night-via: #14100e;
  --bg-night-to: #0d0a08;

  /* Day 文字 */
  --text-primary: #3d2e24;
  --text-secondary: #6e5948;
  --text-muted: #9c8570;
  --text-inverse: #f0e6d2;

  /* 角色色 */
  --color-wolf: #8a1c1c;
  --color-wolf-bg: #f5e6e6;
  --color-seer: #2c5282;
  --color-seer-bg: #e6f0f8;
  --color-witch: #6b46c1;
  --color-witch-bg: #f3e6f8;
  --color-hunter: #c05621;
  --color-hunter-bg: #fdf2e6;
  --color-guard: #276749;
  --color-guard-bg: #e6f5ed;
  --color-idiot: #5c4a3d;
  --color-idiot-bg: #ebe4d4;
  --color-villager: #5c4a3d;
  --color-villager-bg: #ebe4d4;

  /* 功能色 */
  --color-accent: #c5a059;
  --color-accent-light: #d4b06a;
  --color-accent-dark: #8c7335;
  --color-accent-bg: rgba(197, 160, 89, 0.12);
  --color-success: #2f855a;
  --color-success-bg: rgba(47, 133, 90, 0.12);
  --color-warning: #c05621;
  --color-warning-bg: rgba(192, 86, 33, 0.12);
  --color-danger: #9b2c2c;
  --color-danger-bg: rgba(155, 44, 44, 0.12);

  /* Glass Morphism */
  --glass-bg: rgba(255, 255, 255, 0.75);
  --glass-bg-weak: rgba(255, 255, 255, 0.60);
  --glass-bg-strong: rgba(255, 255, 255, 0.90);
  --glass-border: rgba(255, 255, 255, 0.6);
  --glass-shadow: 0 8px 32px rgba(61, 46, 36, 0.08);
  --glass-shadow-strong: 0 12px 48px rgba(61, 46, 36, 0.12);
  --glass-blur: 16px;
  --glass-blur-weak: 10px;
  --glass-blur-strong: 24px;

  /* Border */
  --border-color: rgba(140, 115, 53, 0.25);
  --border-focus: #c5a059;
  --surface-border: rgba(140, 115, 53, 0.18);

  /* 阴影 */
  --shadow-card: 0 4px 16px rgba(61, 46, 36, 0.06);
  --shadow-card-hover: 0 8px 28px rgba(61, 46, 36, 0.10);
  --shadow-modal: 0 16px 48px rgba(61, 46, 36, 0.14);

  /* 字体 */
  --font-title: "Cinzel";
  --font-chinese: "Noto Serif SC";

  /* Topbar */
  --topbar-border: rgba(197, 160, 89, 0.3);

  /* Easing */
  --ease-out: cubic-bezier(0.22, 0.61, 0.36, 1);
  --ease-in-out: cubic-bezier(0.45, 0, 0.55, 1);
}

/* Night theme overrides */
[data-theme="dark"] {
  --text-primary: #f0e6d2;
  --text-secondary: rgba(240, 230, 210, 0.75);
  --text-muted: rgba(240, 230, 210, 0.55);
  --text-inverse: #1a1614;
  --bg-card: rgba(40, 35, 33, 0.8);
  --bg-secondary: rgba(30, 25, 23, 0.9);
  --bg-hover: rgba(50, 43, 38, 0.9);
  --bg-selected: rgba(60, 52, 45, 0.9);
  --border-color: rgba(197, 160, 89, 0.20);
  --surface-border: rgba(197, 160, 89, 0.15);
  --glass-bg: rgba(20, 16, 14, 0.70);
  --glass-bg-weak: rgba(20, 16, 14, 0.55);
  --glass-bg-strong: rgba(20, 16, 14, 0.82);
  --glass-border: rgba(197, 160, 89, 0.20);
  --glass-shadow: 0 14px 40px rgba(0, 0, 0, 0.50);
  --shadow-card: 0 4px 16px rgba(0, 0, 0, 0.30);
  --shadow-card-hover: 0 8px 28px rgba(0, 0, 0, 0.40);
  --color-wolf-bg: rgba(138, 28, 28, 0.15);
  --color-seer-bg: rgba(74, 144, 226, 0.12);
  --color-witch-bg: rgba(155, 89, 182, 0.12);
  --color-hunter-bg: rgba(211, 84, 0, 0.12);
  --color-guard-bg: rgba(39, 174, 96, 0.12);
  --color-villager-bg: rgba(92, 74, 61, 0.15);
  --color-idiot-bg: rgba(92, 74, 61, 0.15);
}
```

### 2.2 Tailwind Config

更新 `tailwind.config.ts` 的 `theme.extend`：

```ts
theme: {
  extend: {
    colors: {
      primary: "var(--color-blood)",
      "primary-light": "var(--color-blood-light)",
      accent: "var(--color-gold)",
      "accent-dim": "var(--color-gold-dim)",
      // ... 其余与 wolfcha 对齐
    },
    boxShadow: {
      card: "var(--shadow-card)",
      modal: "var(--shadow-modal)",
      float: "var(--shadow-card-hover)",
    },
    fontFamily: {
      display: ['"Cinzel"', '"Noto Serif SC"', "serif"],
      body: ['"Noto Serif SC"', "serif"],
    },
  },
},
```

## 3. 组件改造

### 3.1 PlayerCardCompact

**视觉改动**：
- Avatar: 64px 圆形，`border: 2px solid rgba(197,160,89,0.3)`
- 背景: glass morphism（day: `rgba(255,255,255,0.95)` gradient，night: `rgba(40,35,33,0.8)` gradient）
- Border-radius: 6px
- Padding: 12px, min-height: 64px
- Speaking 状态: 金色边框 + `box-shadow: 0 0 12px rgba(197,160,89,0.15)` + 脉冲动画
- Hover: `translateX(4px)` + 金色边框
- Dead 状态: `filter: grayscale(1) brightness(0.9); opacity: 0.6`
- 可选状态: `wc-selectable-pulse` 动画
- 自己: 左侧 3px 金色边框 + 金色渐变背景

**逻辑不变**：所有 props、事件回调、状态判断保持原样

### 3.2 DialogArea

**新增：角色立绘区域**
- 左侧 220-300px（响应式）显示当前说话角色的半身像
- 使用 wolfcha 的 `TalkingAvatar` 组件或类似实现
- 夜间阶段显示角色专属立绘

**聊天记录改动**：
- 气泡样式改为 `.wc-speaker-bubble` 风格
- 背景: glass gradient（day: 白色渐变，night: 深色渐变）
- Border: `1px solid rgba(197,160,89,0.3)`
- Border-radius: `0 12px 12px 12px`（左上角直角）
- 消息边距: `margin-bottom: 12px`
- 人类消息: 右对齐，`background: rgba(197,160,89,0.1)`
- 系统消息: 居中，glass-bg-weak 背景
- 聊天区域: `mask-image` 渐变遮罩（上下淡出）
- 头像: 32px 圆形，`border: 1px solid var(--border-color)`

**输入框改动**：
- 高度 50px
- 背景: `rgba(255,255,255,0.6)` + `backdrop-filter: blur(5px)`
- Border: `1px solid rgba(197,160,89,0.3)`
- Focus: `border-color: var(--color-gold); box-shadow: 0 0 15px rgba(197,160,89,0.2)`
- 字体: Noto Serif SC

**逻辑不变**：消息列表、发送、选择确认逻辑保持

### 3.3 BottomActionPanel

**按钮样式改为 `.wc-action-btn` 风格**：
- 高度 50px, padding 0 24px
- Border: `1px solid var(--color-gold)`
- Background: `linear-gradient(180deg, rgba(197,160,89,0.1), rgba(197,160,89,0.05))`
- Color: `var(--color-gold)`
- Font: Cinzel, bold, 14px, letter-spacing 0.05em
- Hover: `background: rgba(197,160,89,0.2); box-shadow: 0 0 15px rgba(197,160,89,0.2); transform: translateY(-1px)`
- Primary: `background: var(--color-gold); color: #1a1614`
- Danger: `border-color: var(--color-blood); color: var(--color-blood-light); background: rgba(138,28,28,0.1)`

**逻辑不变**：所有 phase 判断和 action 回调保持

### 3.4 GameBackground

**增加视觉层次**：
- Day: 纸质噪声纹理（SVG feTurbulence）+ 中心暖色光晕 + 柔和白/琥珀模糊圆形
- Night: 暗色噪声纹理 + 血红光晕 + 金色光晕 + 雾气动画
- 角落装饰: 固定 SVG 角标（四角 L 形线 + 金色圆点）

**逻辑不变**：isNight/isBlinking props 保持

### 3.5 Notebook FAB

- 背景: `var(--bg-dark)`
- 边框: `2px solid var(--color-gold)`
- 颜色: `var(--color-gold)`
- 阴影: `0 4px 20px rgba(0,0,0,0.50)`
- 尺寸: 56px 圆形

### 3.6 Topbar

- 高度: 60px（mobile: auto, min 48px）
- 背景: glass gradient（day: 白色渐变，night: 深色渐变）+ `backdrop-filter: blur(10px)`
- 底部边框: `1px solid var(--topbar-border)`
- 标题: Cinzel, 900 weight, 20px, letter-spacing 0.1em, gold color + text-shadow
- 信息项: Day/Alive/Phase badge

## 4. 布局结构

### 4.1 桌面端三栏

```
┌─────────────────────────────────────────────┐
│                   Topbar                     │
├──────────┬──────────────────┬───────────────┤
│ Left     │   DialogArea     │  Right        │
│ Players  │  (Portrait +     │  Players      │
│ (220-    │   Chat + Input)  │  (220-        │
│  260px)  │  (flex-1)        │   260px)      │
│          │                  │               │
├──────────┴──────────────────┴───────────────┤
│              BottomActionPanel               │
└─────────────────────────────────────────────┘
```

### 4.2 移动端

- 左右栏隐藏
- 底部水平滚动玩家条
- 对话区全宽
- Topbar 响应式折叠

## 5. 动画

| 动画 | 时长 | 描述 |
|------|------|------|
| `wc-pulse-border` | 2.5s 循环 | 金色边框透明度振荡（speaking） |
| `wc-selectable-pulse` | 2s 循环 | box-shadow 呼吸（可选卡牌） |
| Day/Night 转场 | close 360ms + hold 120ms + open 620ms | 眼睑闭合动画 |
| Background crossfade | 1.5s | 背景渐变交叉淡入淡出 |
| Entry animation | 0.3s | `opacity: 0, y: 10, scale: 0.95` + spring |
| Card hover | 0.2s | `translateX(4px)` + 金色边框 |
| Card flip (role reveal) | 0.7s | `rotateY` 180→0, perspective 1200 |
| Night action overlays | 各异 | wolf claw, witch heal/poison, hunter shot, seer eye |

所有动画尊重 `prefers-reduced-motion: reduce`。

## 6. 不改动的部分

- 后端 API 接口
- WebSocket 协议和消息格式
- `useWebSocketGame` hook 逻辑
- `game-store.ts` atom 逻辑
- `types/game.ts` 类型定义
- WelcomeScreen（大厅页面，不在本次范围）
- RoleRevealOverlay（已有，只需微调 CSS 变量引用）
- NightActionOverlay（已有，只需微调 CSS 变量引用）

## 7. 文件清单

| 文件 | 改动类型 |
|------|----------|
| `app/globals.css` | 重写 CSS 变量 + 新增 wc-* 组件样式 |
| `tailwind.config.ts` | 更新 theme.extend |
| `components/game/PlayerCardCompact.tsx` | 视觉重写（保持 props） |
| `components/game/DialogArea.tsx` | 加立绘区 + 视觉重写 |
| `components/game/BottomActionPanel.tsx` | 按钮样式重写 |
| `components/game/GameBackground.tsx` | 加纹理/光晕/角标 |
| `components/game/Notebook.tsx` | FAB 样式更新 |
| `app/room/[id]/play/page.tsx` | 布局结构调整（三栏 + topbar） |
| 新增: `components/game/PortraitArea.tsx` | 角色立绘展示组件 |
