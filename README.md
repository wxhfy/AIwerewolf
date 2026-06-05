<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)">
    <img alt="AI Werewolf" src="https://img.shields.io/badge/AI-Werewolf-8b5cf6?style=for-the-badge&logo=data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjQiIGhlaWdodD0iMjQiIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48Y2lyY2xlIGN4PSIxMiIgY3k9IjEyIiByPSIxMCIgZmlsbD0id2hpdGUiLz48L3N2Zz4=">
  </picture>
</p>

<h1 align="center">AI Werewolf</h1>
<p align="center"><strong>多智能体狼人杀 — 会玩 · 能复盘 · 会进化</strong></p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License"></a>
  <a href="#"><img src="https://img.shields.io/badge/python-3.8%20%7C%203.12-blue" alt="Python"></a>
  <a href="#"><img src="https://img.shields.io/badge/status-beta-orange" alt="Status"></a>
  <a href="#"><img src="https://img.shields.io/badge/build-strict%20mode%20passed-brightgreen" alt="Build"></a>
  <a href="#"><img src="https://img.shields.io/badge/database-PostgreSQL%2015-336791?logo=postgresql" alt="PostgreSQL"></a>
  <a href="#"><img src="https://img.shields.io/badge/frontend-Next.js%2015-black?logo=next.js" alt="Next.js"></a>
</p>

---

## 这是什么

**AI Werewolf** 是一个 AI 狼人杀多智能体对战系统。每个 AI 玩家拥有独立的 MBTI 人格、角色策略和认知架构，在严格信息隔离下进行推理、欺骗和协作。赛后通过三级评分级联定位关键失误，复盘结果沉淀为带可信度控制的策略知识，回流到下一代 Agent，形成闭环自进化。

### 三条轨道

```
┌─────────────────────────────────────────────────────────────────┐
│  Track A: 基础对局                                               │
│  CognitiveAgent × RoleStrategyCard × WolfTeamView × BeliefTracker│
│  6 种角色 · 32 个具名人格 · 92 项信息隔离验证                      │
└─────────────────────────────────────────────────────────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────────┐
│  Track B: 评测复盘                                               │
│  三级评分级联 → 反事实推演 → LLM Judge Panel → 结构化报告           │
│  发言质量 · 投票合理性 · 技能使用 · 阵营协作 — 逐步评分              │
└─────────────────────────────────────────────────────────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────────┐
│  Track C: 自进化                                                 │
│  复盘 → 知识提取 → L0-L4 可信度评估 → 4-Filter 安全管线 → 回流     │
│  A/B Leaderboard · 回合制进化 · 策略知识库 (187 条)                │
└─────────────────────────────────────────────────────────────────┘
```

---

## 快速开始

> 前置条件: Python 3.8+, Node.js 18+, Docker (PostgreSQL)

```bash
# 1. 克隆仓库
git clone <repo-url> && cd AIwerewolf

# 2. 安装依赖
python -m pip install -r requirements.txt

# 3. 配置 LLM API Key
cp .env.example .env
# 编辑 .env，填入 DOUBAO_API_KEY

# 4. 启动数据库
make db-up && make db-init

# 5. 运行预检 (7 项检查)
python -m backend.ops.preflight

# 6. 启动后端
make dev
# → API 服务运行在 http://localhost:8000

# 7. 启动前端 (另一个终端)
cd frontend && npm install --legacy-peer-deps && npm run dev
# → 观战界面运行在 http://localhost:3001
```

跑一局完整对局：
```bash
python scripts/run_full_llm_pipeline.py
```

---

## 系统架构

```
                           WerewolfGame Engine
                    (15+ phase transitions, parallel)
                                  │
        ┌─────────────────────────┼─────────────────────────┐
        ▼                         ▼                         ▼
   PlayerView 1             PlayerView 2             PlayerView N
  (3-view 信息隔离)         (3-view 信息隔离)         (3-view 信息隔离)
        │                         │                         │
        ▼                         ▼                         ▼
  CognitiveAgent           CognitiveAgent           CognitiveAgent
        │                         │                         │
        ├── Observe (BeliefTracker + 局势感知)                │
        ├── Think  (AgentLoop, 6 tools, max 3 iterations)     │
        └── Act   (Speech / Vote / Night Action)              │
        │                         │                         │
        └─────────────────────────┼─────────────────────────┘
                                  │
                                  ▼
                         PostgreSQL (21 张表)
                    agent_decisions + tool_trace
                                  │
                                  ▼
                        PerStepScorer (三级评分)
                     Tier 1 → Tier 2 → Tier 3 (LLM Judge)
                                  │
                    ┌─────────────┴─────────────┐
                    ▼                           ▼
            CounterfactualAnalyzer     KnowledgeAbstractor
              (反事实推演)               (知识提取 + 回流)
```

---

## 核心验证

| 验证项 | 命令 | 覆盖范围 |
|--------|------|----------|
| **全量严格验证** | `python scripts/run_backend_full_strict.py` | DB → LLM → 对局 → 评分 → 知识 → 报告 |
| **信息隔离验证** | `python scripts/verify_visibility_strict.py` | 92 项边界检查，杜绝信息泄露 |
| **多 Tier 实验** | `python scripts/multi_tier_experiment.py` | A/B 对比实验框架 |
| **单元测试** | `pytest tests/ -q` | 全量测试套件 |

---

## 技术栈

<table>
<tr>
  <td><strong>后端</strong></td>
  <td>Python 3.12 · FastAPI · WebSocket · LangChain</td>
</tr>
<tr>
  <td><strong>前端</strong></td>
  <td>Next.js 15 · React 19 · Tailwind CSS</td>
</tr>
<tr>
  <td><strong>数据库</strong></td>
  <td>PostgreSQL 15 (Docker, port 5433)</td>
</tr>
<tr>
  <td><strong>LLM</strong></td>
  <td>火山方舟 doubao-seed-2.0-pro · MiniMax</td>
</tr>
<tr>
  <td><strong>检索</strong></td>
  <td>BM25 + 倒排索引 (GPU-free) · Agent 工具调用</td>
</tr>
<tr>
  <td><strong>评测</strong></td>
  <td>LLM Judge Panel (三法官 + Critic) · scikit-learn</td>
</tr>
</table>

---

## 数据模型

21 张 PostgreSQL 表，覆盖完整生命周期：

| 类别 | 核心表 | 说明 |
|------|--------|------|
| **对局** | `games`, `players`, `game_events`, `game_snapshots` | 游戏状态与事件流 |
| **Agent** | `agent_decisions`, `agent_versions` | 决策日志含 tool_trace + strategy IDs |
| **评测** | `evaluations`, `review_reports`, `published_reviews`, `leaderboard_entries` | 三级评分 + 复盘报告 |
| **知识** | `strategy_knowledge_docs`, `strategy_graph_links`, `role_strategy_cards`, `strategy_patches` | 策略知识库 |
| **进化** | `evolution_tournaments`, `evolution_rounds`, `knowledge_usage_feedback`, `strategy_snapshots` | 知识生命周期 |
| **人设** | `personas`, `persona_role_adapters` | 32 个 MBTI 人格 |
| **实验** | `experiments` | 消融实验追踪 |

---

## Prompt 架构

三层物理分离，不可交叉：

| Layer | 职责 | 内容 | 策略污染防护 |
|-------|------|------|:---:|
| **Layer 1: Persona** | 控制"怎么说" | MBTI + 性格 + 说话风格 | ✅ |
| **Layer 2: Role Identity** | 定义"我是谁" | 身份 + 能力边界 + 胜利条件 | ✅ |
| **Layer 3: Strategy** | 教"怎么玩" | 检索策略 + 6 工具函数 | — |

策略知识只能从 Layer 3 进入 Prompt，经由 **4-Filter 安全管线** 过滤：
`confidence → visibility → no_leak → applicability → top_k`

---

## 项目结构

```
AIwerewolf/
├── backend/
│   ├── engine/              # 游戏引擎 (WerewolfGame, PlayerView)
│   ├── agents/cognitive/    # CognitiveAgent (Observe-Think-Act)
│   ├── eval/                # 评测 + 复盘 + 知识进化
│   ├── protocols/           # WebSocket / Room / Snapshot
│   ├── db/                  # ORM + 连接池 + 持久化
│   ├── llm/                 # LLM 客户端
│   └── ops/                 # 运维 (preflight 7 项检查)
├── frontend/                # Next.js 15 观战 UI
├── configs/                 # 规则配置 · 策略库 (187 条)
├── scripts/                 # 验证 · 实验 · 消融
├── tests/                   # 测试套件
└── docs/                    # 架构 · 数据流 · 验收标准
```

---

## 文档

| 文档 | 说明 |
|------|------|
| [`ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 系统架构总览 |
| [`DATA_FLOW.md`](docs/DATA_FLOW.md) | 端到端数据流 & 证据链 |
| [`backend_acceptance_criteria.md`](docs/backend_acceptance_criteria.md) | 后端验收标准 |
| [`DEVELOPMENT_ISSUES.md`](docs/DEVELOPMENT_ISSUES.md) | 开发问题追踪 |
| [`PROJECT_STATUS.md`](docs/PROJECT_STATUS.md) | 项目状态速览 |
| [`DOC_INDEX.md`](docs/DOC_INDEX.md) | 文档索引 |

---

## License

MIT © 2025 — see [LICENSE](LICENSE) for details.

---

<p align="center">
  <sub>Built with ❤️ by <a href="https://github.com/wxhfy">wxhfy</a></sub>
</p>
