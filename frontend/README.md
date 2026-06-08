# AI Werewolf Frontend

Next.js + TypeScript + Tailwind CSS 前端，包含大厅、对局观战、真人操作、复盘仪表盘和人格管理页面。

## 技术栈

- Next.js 14.2.32
- React 18.2
- TypeScript 5
- Tailwind CSS 3.4
- `motion` / `gsap` 用于动效
- `recharts` 用于图表

## 快速开始

```bash
npm install
npm run dev
```

默认访问：

- Frontend: http://localhost:3001
- Backend: http://localhost:8000

如果 3001 被占用：

```bash
PORT=3002 npm run dev
```

生产构建：

```bash
npm run lint
npm run build
npm run start
```

## 项目结构

```
frontend/
├── app/
│   ├── page.tsx                 # /
│   ├── room/[id]/play/          # 对局观战
│   ├── room/[id]/human/         # 真人玩家操作页
│   ├── eval/dashboard/          # 复盘仪表盘
│   ├── personas/                # 人格管理
│   ├── games/[id]/report/       # 单局复盘报告
│   ├── layout.tsx
│   └── globals.css
├── components/
│   ├── ui/
│   └── game/
├── context/
│   └── AppContext.tsx
├── hooks/
├── lib/
├── types/
│   └── index.ts
├── next.config.js
├── tailwind.config.ts
└── package.json
```

## API 代理

`next.config.js` 默认把请求代理到 `BACKEND_ORIGIN`，未设置时为 `http://127.0.0.1:8000`：

- `/api/*` -> `${BACKEND_ORIGIN}/api/*`
- `/ws/*` -> `${BACKEND_ORIGIN}/ws/*`

运行前端开发服务器前请先启动后端：

```bash
uvicorn backend.app:app --reload --host 0.0.0.0 --port 8000
```
