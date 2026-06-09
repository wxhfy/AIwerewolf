# CLAUDE.md — AI Werewolf 项目

> **项目根目录**: `/home/fyh0106/AIwerewolf/`
> **参考仓库**: `/home/fyh0106/AIwerewolf/references/`（local-only，不进入 GitHub）

## 项目运行模式（最高优先级，覆盖 skills/ 中的多人协作规则）

**当前阶段：单人开发**（owner: wxhfy / 付一涵）。

- AI 可在用户授权后直接 `git push` 到 `main`：无需 PR、无需 review、无需 2 人 approve；merge / rebase / squash / cherry-pick 可自主决定。
- 仍保留的护栏（任何阶段都不放松）：
  1. 修改重灾区文件（`backend/engine/*`、`backend/protocols/schemas.py`、`backend/db/models.py`、`CLAUDE.md`、`AGENTS.md`、`SKILLS.md`、`skills/*`）前用一句话告知用户范围；
  2. 不得 `git push --force` 到 `main`；
  3. 不得跳过 hook（`--no-verify` / `--no-gpg-sign`）；
  4. 不得把 API Key、`.env`、Prompt 全文写进 commit / PR / 代码注释；
  5. commit message 仍走 Conventional Commits（`feat / fix / docs / chore / refactor / test / perf`）。
- 当团队规模 >= 2 时本段失效，恢复 `skills/10-git-workflow.md` 和 `skills/70-ai-collaboration.md` 的多人 PR 规则。

> 本段显式覆盖：
> - `skills/10-git-workflow.md` §一 “main 受保护、禁止直推”
> - `skills/10-git-workflow.md` §三 “至少 1 人 approve” + 重灾区 “2 人 approve”
> - `skills/10-git-workflow.md` §七 “禁止 AI 直接 git push 到 main”
> - `skills/70-ai-collaboration.md` §四 “AI 必须先问人 -> git push origin main”

---

## AI 助手开工指引（必读）

接到任务后，按下面顺序读：

1. **本文件（CLAUDE.md）** — 项目速查
2. **`SKILLS.md`** — 狼人杀业务知识 + 参考仓库
3. **`skills/README.md`** — 团队协作规范索引
4. 按任务类型继续读：
   - 改后端：`skills/20-backend-conventions.md`
   - 改前端：`skills/30-frontend-conventions.md`
   - 改 Agent：`skills/40-agent-development.md`
   - 改 API / Schema：`skills/50-api-contract.md`
   - 写测试：`skills/60-testing-ci.md`
   - 任何 AI 直接改代码：`skills/70-ai-collaboration.md`

**铁律**：动代码前必须查对应 `skills/` 文件；跨模块改动必须先列计划让人类确认。

> 本文件与 `AGENTS.md` 内容等价，仅入口名不同（Claude Code 读 `CLAUDE.md`，Codex 通常读 `AGENTS.md`）。改一份要同步改另一份。

---

## 当前项目概述

AI Werewolf 是一个多智能体狼人杀研究平台：AI 玩家在严格信息隔离下完成狼人杀对局，并通过赛后复盘分析、复盘报告、策略知识抽取和检索回流形成 Play -> Evaluate -> Evolve 闭环。

当前实现已经不只是 MVP：

- **Play**：`WerewolfGame` 引擎支持 7-12 人配置、警徽、PK、遗言、猎人开枪、白狼王自爆、真人混战。
- **Agent**：AI 席位默认且强制使用 LLM-compatible `CognitiveAgent`；`agent_type=heuristic` 会被拒绝。离线测试用 `_TEST_ALLOW_FAKE_LLM=true LLM_PROVIDER=fake`。
- **Evaluate**：Track B 生成逐步复盘分析、复盘报告、runtime metrics、leaderboard。
- **Evolve**：Track C 抽取策略知识、维护 strategy cards / patches / knowledge usage feedback。
- **Frontend**：Next.js 14 + React 18 的大厅、对局页、真人操作页、复盘仪表盘、人格页、单局报告页；Track C 通过后端 API、脚本和报告材料呈现。

## 技术栈（当前实现）

| 层 | 当前实现 |
|---|---|
| 后端 | Python 3.8+ / FastAPI / WebSocket |
| 游戏引擎 | dataclass + Enum 纯逻辑，入口 `backend/engine/game.py` |
| Agent | `backend/agents/cognitive/` 的 `CognitiveAgent` + `HumanAgent` |
| LLM | `backend.llm.create_client()`，支持 `doubao` / `dsv4flash` / `ark` / `deepseek` / `anthropic` / `weapi` / `mimo` / test-only `fake` |
| DB | SQLAlchemy；`DATABASE_URL` 存在时 PostgreSQL，否则 SQLite fallback |
| 前端 | Next.js 14.2.32 / React 18.2 / TypeScript 5 / Tailwind 3.4 |
| 配置 | YAML (`configs/`) + `.env`（不入库） |
| 验证 | `backend.run_demo`、ruff、前端构建；`scripts/`、`tests/`、`.github/` 为 local-only，不进入当前 GitHub 精简仓库 |

## 当前项目结构

```
AIwerewolf/
├── AGENTS.md / CLAUDE.md       # AI 入口说明（内容等价）
├── SKILLS.md                   # 狼人杀业务知识和参考仓库说明
├── README.md                   # GitHub 首页说明
├── REQUIREMENTS.md             # 项目需求与设计目标
├── backend/
│   ├── app.py                  # FastAPI / REST / WebSocket 入口
│   ├── engine/                 # 游戏引擎、规则、状态、Visibility
│   ├── engine/roles/           # RoleRegistry，角色元数据单一事实来源
│   ├── agents/                 # Agent 协议、HumanAgent、legacy agent、认知 agent
│   ├── agents/cognitive/       # CognitiveAgent、AgentLoop、Memory、Retrieval
│   ├── protocols/              # Room schema / RoomManager
│   ├── db/                     # SQLAlchemy models + persist/persona DB
│   ├── eval/                   # Track B/C 复盘分析、知识进化、open-data 适配
│   ├── llm/                    # LLM 客户端封装
│   └── ops/                    # preflight 等运维检查
├── frontend/
│   ├── app/                    # App Router: /, /room/[id]/play, /human, /eval/dashboard, /personas, /games/[id]/report
│   ├── components/             # UI 和 game 组件
│   ├── hooks/                  # 对局流、真人操作、展示派生状态
│   ├── lib/                    # API、i18n、展示派生工具
│   └── types/index.ts          # 后端契约 TS 镜像
├── configs/                    # 规则、策略和实验配置
├── docs/                       # 正式文档、报告、轻量图表资产
├── skills/                     # 协作和代码规范
├── nginx/                      # Docker 反向代理
└── references/                 # 本地参考仓库，.gitignore 排除
```

## GitHub 干净度约定

应进入 GitHub：

- 源码：`backend/`、`frontend/`、`configs/`
- 正式文档：根目录 README/需求/变更日志、`docs/*.md`、小型 SVG/HTML 展示资产
- 部署配置：`Dockerfile`、`docker-compose.yml`、`nginx/`

不应进入 GitHub：

- `.env`、真实 API Key、本地数据库、日志、备份、`.venv`
- `data/`、`models/`、`references/`、`scripts/`、`tests/`、`.github/`
- `frontend/.next*`、`node_modules/`、大体积图片/音频/截图、实验输出 JSONL

提交前至少跑：

```bash
git status --short --ignored
git ls-files | rg '(^|/)(\\.env$|__pycache__/|node_modules/|\\.next/|data/|models/|outputs/|references/|scripts/|tests/|\\.github/|docs/evidence/|docs/experiments/)|\\.(db|sqlite|log|jsonl|pptx|pdf|png|jpe?g)$'
```

---

## 游戏规则与当前实现

### 可玩角色与模板角色

`backend/engine/models.py` 的 `Role` enum 当前包含：

- 可玩并可进入 7-12P 配置：`Villager`、`Werewolf`、`WhiteWolfKing`、`Seer`、`Witch`、`Hunter`、`Guard`、`Idiot`
- 模板角色（registry / prompt / i18n 已有，默认 `playable=False`，不会进入 7-12P 配置）：`Cupid`、`BigBadWolf`、`WolfCub`、`WolfKing`、`Knight`、`Elder`

角色元数据单一事实来源：`backend/engine/roles/`。新增角色必须同步 `Role` enum、RoleRegistry、Agent playbook/profile/prompt、前端 `types/index.ts` 和 i18n；若设为可玩，还要补引擎阶段和测试。

### 当前 Phase 清单

```
SETUP
NIGHT_START
NIGHT_GUARD_ACTION
NIGHT_WOLF_ACTION
NIGHT_WITCH_ACTION
NIGHT_SEER_ACTION
NIGHT_RESOLVE
DAY_START
DAY_BADGE_SIGNUP
DAY_BADGE_SPEECH
DAY_BADGE_ELECTION
DAY_PK_SPEECH
DAY_LAST_WORDS
DAY_SPEECH
DAY_SHERIFF_CLOSING
DAY_VOTE
DAY_RESOLVE
BADGE_TRANSFER
HUNTER_SHOOT
WHITE_WOLF_KING_BOOM
GAME_END
```

### 胜负条件（以代码为准）

- 好人胜：所有狼人死亡。
- 狼人胜：狼人数 >= 存活好人数；或所有神职死亡；或所有村民死亡。
- `max_days` 达到上限时，当前代码将 `winner` 设为 `wolf`，reason 为 `max_days_reached`。

### 关键展示规则

- `show_private=false` 时，夜间子阶段会在 public snapshot 中折叠为 `NIGHT_START`，夜间具体行动 payload 会脱敏。
- `night_actions.wolf_votes` 是狼队个体初始目标，不一定等于最终刀口；前端展示最终刀口应以 `night_actions.wolf_target_id` 为准。
- 公开视角不应请求或缓存 private snapshot；前端只是渲染，信息隔离必须在后端完成。

---

## Agent 协议（当前代码）

源文件：`backend/agents/base.py`、`backend/engine/models.py`。

```python
class Agent(Protocol):
    player_id: str

    def initialize(self, view: PlayerView, game_setting: dict) -> None: ...
    def update(self, view: PlayerView, request: str) -> None: ...
    def day_start(self) -> None: ...
    def talk(self) -> Decision: ...
    def vote(self) -> Decision: ...
    def attack(self) -> Decision: ...
    def divine(self) -> Decision: ...
    def guard(self) -> Decision: ...
    def witch_act(self, victim_id: str | None) -> list[Decision]: ...
    def shoot(self) -> Decision: ...
    def boom(self) -> Decision: ...
    def transfer_badge(self, candidates: list[str]) -> Decision: ...
    def finish(self, winner: str | None) -> None: ...
```

`Decision` 当前字段：

```python
@dataclass
class Decision:
    actor_id: str
    action_type: ActionType
    target_id: str | None = None
    speech: str | None = None
    reasoning: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
```

`ActionType` 当前值：

```
talk, vote, attack, divine, guard, witch_save, witch_poison, shoot, boom, skip
```

---

## API / 前端速查

后端默认：

```bash
make dev
# http://localhost:8000/docs
```

前端默认：

```bash
cd frontend
npm install --legacy-peer-deps
npm run dev
# http://localhost:3001
```

核心路由：

- REST：`/api/health`、`/api/rooms`、`/api/games`、`/api/replay/{game_id}`、`/api/games/{game_id}/reviews*`、`/api/leaderboard*`、`/api/evolution*`、`/api/strategy/*`、`/api/personas`
- WebSocket：`/ws/games`、`/ws/rooms/{room_id}`
- 前端：`/`、`/room/[id]/play`、`/room/[id]/human`、`/eval/dashboard`、`/games/[id]/report`、`/personas`

---

## 参考仓库速查

| 优先级 | 仓库 | 目录名 | 核心价值 |
|---|---|---|---|
| #1 | oil-oil/wolfcha | `wolfcha/` | 产品形态、Phase、Persona |
| #2 | xiong35/werewolf | `xiong35-werewolf/` | 房间、WebSocket、断线重连 |
| #3 | Char-lotte-Xia/WereWolfPlus | `WereWolfPlus/` | Prompt 模板、多模型对比 |
| #4 | aiwolf/AIWolfPy | `AIWolfPy/` | Agent 生命周期 |
| #5 | AIWolfSharp/AIWolfSharp | `AIWolfSharp/` | Server/Client 分离接口 |
| #6 | lycan-city/werewolf-brain | `werewolf-brain/` | 角色库、夜晚序列 |
| #7 | open-mafia/open_mafia_engine | `open_mafia_engine/` | 事件驱动引擎 |
| #8 | JamesCraster/OpenWerewolf | `OpenWerewolf/` | 在线房间/大厅 |
| #9 | AlecM33/Werewolf | `AlecM33-Werewolf/` | 主持工具参考，GPL-3.0 不可复制 |
| #10 | lykoss/lykos | `lykos/` | 复杂角色 Bot |

最常用参考文件：

1. `references/WereWolfPlus/agent_manager/prompts/werewolf_prompt.py`
2. `references/wolfcha/src/types/game.ts`
3. `references/AIWolfPy/aiwolfpy/agentproxy.py`

---

## 常用验证命令

```bash
make lint
make test
python -m backend.run_demo --seed 7
cd frontend && npm run build
```

local-only 的 `scripts/` / `tests/` 若存在，可继续用于更重的 strict、visibility、Track B/C 验证；这些材料不进入当前 GitHub 精简仓库。
