---
name: frontend-conventions
description: Vanilla JS / i18n / WebSocket / 状态管理 / CSS 命名规范
audience: claude, codex, human
version: 1.0.0
updated: 2026-05-22
---

# 前端开发规范

> 适用范围：`frontend/` 目录。
> 当前技术栈：**原生 HTML + CSS + JavaScript**，无构建工具，无 React/Vue/Next.js。
> 由 FastAPI 通过 `StaticFiles` 直接托管 `frontend/`，访问 `http://localhost:8000` 即看到 `index.html`。

---

## 一、为什么不上框架

| 决策 | 理由 |
|------|------|
| 不上 React/Vue/Next | 项目体量小，零构建步骤更省事；不引入 node_modules |
| 不上 TypeScript | 同上；类型在后端 schemas.py 已收敛 |
| 不上 Tailwind | 已有手写 CSS 变量体系，引入 Tailwind 重写不划算 |

**例外**：如果有人要重写前端为 Next.js + TS，必须先在群里讨论 + PR 改本规范。

---

## 二、文件结构

```
frontend/
├── index.html       # 单页面，所有 DOM 都在这里
├── app.js           # 唯一的应用逻辑
└── style.css        # 唯一的样式表
```

**禁止**：
- 多份 `*.html` 文件（除非作为独立工具页）
- 大段 inline `<script>` / `<style>`
- `app.js` 拆成 `utils.js`/`api.js`/...（除非超过 1500 行再考虑）

---

## 三、JavaScript 风格

### 全局状态：单一 `state` 对象

```js
const state = {
  lang: ...,
  showPrivate: false,
  busy: false,
  roomId: null,
  gameId: null,
  // ...
};
```

- **所有可变全局状态都挂这里**，禁止散落的 `let` / `var`
- 改 state 之后调用对应的 `render*()` 函数刷新 UI
- 不要直接读 DOM 反推状态（DOM 是渲染产物，不是数据源）

### DOM 引用：集中 `els` 对象

```js
const $ = (selector) => document.querySelector(selector);
const els = {
  run: $("#run"),
  statusPhase: $("#status-phase"),
  // ...
};
```

- 启动时一次性把所有用到的元素 cache 进 `els`
- 后续读写都走 `els.xxx`，不要再 `document.querySelector` 重新查

### 命名

| 对象 | 风格 |
|------|------|
| 函数 / 变量 | `camelCase` |
| 常量字典（如 `I18N`） | `UPPER_SNAKE` |
| HTML id / class | `kebab-case` |
| `els` 键 | `camelCase` 对应 id `kebab-case` |

### 异步与错误处理

- 用 `async/await`，不要嵌套 `.then()` 链
- API 调用统一包 `try/catch`：失败时 toast 用户可见的错误，不要静默吞

```js
async function startGame() {
  try {
    const res = await fetch("/api/games", { method: "POST", ... });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    // ...
  } catch (e) {
    showError(e.message);
  }
}
```

### 禁止

- 用 `eval()` / `new Function()`
- 用 `innerHTML` 拼接用户输入（XSS）→ 用 `textContent` 或显式转义
- 在 prod 留 `console.log` 调试（开 PR 前清掉，或包 `if (DEBUG)`）

---

## 四、i18n 字典

```js
const I18N = {
  zh: { run: "开始游戏", ... },
  en: { run: "Start Game", ... },
};
```

### 规则

1. **所有用户可见文案**必须走字典，不允许 hardcode 在 HTML 或 JS
2. HTML 中 `data-i18n="key"` 标记，由 JS 渲染时填充
3. **必须同时**添加 `zh` 与 `en` 两个版本——只加一种过不了 review
4. key 用 `camelCase`，描述意图（`statusReady`），不要描述内容（`zhClickToStart`）
5. 模板字符串用 `{player}` 占位：`died: "{player} 因 {reason} 出局"`，渲染时用替换函数

### 反例

```html
<!-- 错：硬编码 -->
<button>开始游戏</button>

<!-- 对：标记 i18n key -->
<button data-i18n="run">开始游戏</button>
```

---

## 五、WebSocket

当前架构（看 `backend/app.py` 与 `frontend/app.js`）：

1. 前端 POST 创建房间 → 拿到 `room_id`
2. 前端开 `ws://host/ws/rooms/{room_id}` 连接
3. 后端每个 Phase 推 snapshot 给前端
4. 前端按事件类型分发到 `render*()`

### 客户端约定

- 一个房间**只开一个 WebSocket**（state.ws 单例）
- 切换语言 / 改 UI 状态 **不要**重连
- 断线后 **指数退避重连**（1s, 2s, 4s, 最多 30s）
- 每个收到的 message 都 `try { JSON.parse }`，失败不崩溃

### 消息格式

详见 `50-api-contract.md`，前端只接收，不构造（除了心跳）。

---

## 六、CSS 风格

### 颜色与变量

`:root` 定义颜色变量，**禁止**在选择器里写裸 hex：

```css
:root {
  --ink: #1a1a2e;
  --paper: #fef3e4;
  --wolf: #dc2626;
  --village: #2563eb;
}

.brand { color: var(--ink); }
```

新增颜色 → 加到 `:root`，给语义化命名（`--wolf` 不是 `--red`）。

### 选择器命名

- 类名 `kebab-case`，**语义化**：`.action-panel` / `.player-card`
- 状态修饰：`.hidden` / `.active` / `.dead`
- BEM 可以但不强求：`.players-grid__seat--dead`

### 避免

- `!important`（紧急 hotfix 可以，但 PR 描述里要解释）
- 内联 `style="..."`（特殊场景如动画 transform 可以）
- 通配选择器（`* { ... }`）只用于 reset

### 响应式

- 优先 flex / grid，移动端通过 `@media (max-width: 768px)` 收窄
- 答辩 demo 重点是桌面端 1080p，移动端不优化也可以但不能崩

---

## 七、HTML 结构

- 语义化标签：`<header> <main> <section> <article> <nav>`，不要全 `<div>`
- 表单控件加 `aria-label`：盲人/无障碍/截图可读
- 所有 `<button>` 显式写 `type="button"`，避免提交表单
- 禁止：`<table>` 用作布局（用 grid）

---

## 八、手测 checklist（PR 前必跑）

改了前端，**至少**手测：

- [ ] 启动 `uvicorn backend.app:app --reload --host 0.0.0.0 --port 8000`
- [ ] `http://localhost:8000` 打开，点 "开始游戏" 跑完一局
- [ ] 切换语言 zh ↔ en，所有文案正确
- [ ] 切换主持视角，私有信息正确显示/隐藏
- [ ] 历史对局点击进入，可看回放
- [ ] AI + Human 模式，自己当 seat 1 跑一局
- [ ] 浏览器 console 无 error / warning（DevTools 打开看）

UI smoke 自动化：`node tests/ui_smoke.mjs`（详见 `60-testing-ci.md`）。

---

## 九、性能

- DOM 大批量更新用 `DocumentFragment` 一次性 append
- 长列表（>100 项的事件流）考虑虚拟滚动或截断
- 图片资源压缩（如果引入）

当前对局规模（7-12 人 × 几十个事件）下不会有性能问题，不要过度优化。

---

## 十、AI 改前端的红线

让 AI 写前端代码时，至少检查：

- [ ] 没有引入 React/Vue/jQuery/Lodash 等库
- [ ] 文案都走 `I18N`，zh + en 都加了
- [ ] DOM 引用走 `els`，状态走 `state`
- [ ] CSS 颜色用 `var(--xxx)`，不裸 hex
- [ ] 没有 `innerHTML` 拼用户输入
- [ ] WebSocket 复用单例，不重连
- [ ] 没留 `console.log` debug 输出

详见 `70-ai-collaboration.md`。

---

*Version 1.0.0 — 2026-05-22 — 初始建立。*
