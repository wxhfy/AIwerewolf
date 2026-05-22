# AI Werewolf Frontend

基于 Next.js + TypeScript + Tailwind CSS 的 AI 狼人杀观战控制台前端。

## 技术栈

- Next.js 14.2.32
- React 19
- TypeScript 5
- Tailwind CSS 3.4.17
- clsx + tailwind-merge

## 快速开始

### 安装依赖

```bash
npm install
```

### 开发模式运行

```bash
npm run dev
```

访问 http://localhost:3000

### 构建生产版本

```bash
npm run build
npm start
```

## 项目结构

```
frontend/
├── app/                    # Next.js App Router
│   ├── globals.css        # 全局样式
│   ├── layout.tsx         # 根布局
│   └── page.tsx           # 主页/观战页
├── components/
│   ├── ui/                # UI 组件
│   │   ├── Button.tsx
│   │   ├── Badge.tsx
│   │   └── Card.tsx
│   └── game/              # 游戏组件
│       ├── PlayerCard.tsx
│       └── EventItem.tsx
├── context/
│   └── AppContext.tsx     # 全局状态
├── lib/
│   ├── utils.ts           # 工具函数
│   └── i18n.ts            # 国际化
├── types/
│   └── index.ts           # TypeScript 类型定义
├── next.config.js         # Next.js 配置
├── tailwind.config.ts     # Tailwind 配置
└── package.json
```

## 功能特性

- ✅ 观战控制台 UI
- ✅ 支持公开/主持视角切换
- ✅ 中英文双语支持
- ✅ WebSocket 实时更新
- ✅ 房间管理
- ✅ 游戏状态展示
- ✅ 事件时间线
- ✅ 玩家卡片展示

## API 代理

前端通过 `next.config.js` 中的 `rewrites` 配置代理 API 请求到后端：

- `/api/*` → `http://localhost:8000/api/*`
- `/ws/*` → `http://localhost:8000/ws/*`

确保后端服务在 http://localhost:8000 运行。
