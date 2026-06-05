# CLAUDE.md — AI Werewolf 项目

> **项目根目录**: `/home/fyh0106/AIwerewolf/`
> **参考仓库**: `/home/fyh0106/AIwerewolf/references/`
> **主攻方向**: Track B 评测 + 复盘 + 轻量自进化

## 项目运行模式

**当前阶段：单人开发**（owner: wxhfy / 付一涵）。

- AI 可在用户授权后**直接 `git push` 到 main**：无需 PR、无需 review、无需 2 人 approve。
- 保留的护栏：
  1. 修改"重灾区"文件（`backend/engine/*`、`backend/protocols/schemas.py`、`backend/db/models.py`、`CLAUDE.md`）前告知用户；
  2. 不得 `git push --force` 到 main；
  3. 不得跳过 hook（`--no-verify` / `--no-gpg-sign`）；
  4. 不得把 API Key、`.env`、Prompt 全文写进 commit / PR / 代码注释；
  5. commit message 走 Conventional Commits（`feat / fix / docs / chore / refactor / test / perf`）。

---

## 项目目标（最终版）

> 做一个 AI 狼人杀多智能体系统：会玩（Play），能复盘（Evaluate），会进化（Evolve）。

### 三个关键词

```
玩 Play       = CognitiveAgent + RoleStrategyCard + WolfTeamView + BeliefTracker
评 Evaluate   = 三级评分 + 反事实推演 + Judge校准 + DecisionTrace + 结构化报告
进化 Evolve   = L0-L4 知识分层 + 权限过滤 + 回验 + A/B Leaderboard
```

### 主申报方向：Track B — 评测 + 复盘

通过确定性 replay、反事实推演、级联评分和结构化报告，定位 Agent 在发言、投票、技能使用、阵营协作中的关键失误。复盘结果沉淀为带可信度和权限控制的策略知识，作为轻量自进化能力。

---

## 评判标准（评分细则与权重）

总分 100 分。核心选拔目标：**Agent 调优和多智能体系统设计能力**。
Agent 相关维度合计 70%，工程相关维度合计 30%。

### 评分维度

| 维度 | 权重 | 考察要点 | 满分档 | 及格档 | 不及格 |
|---|---|---|---|---|---|
| **单 Agent 能力**（Prompt 工程与决策质量） | 20% | Prompt 设计质量（角色人设、思维链、few-shot 等）；迭代调优过程；各角色策略差异度；决策推理链路可追溯性 | Prompt 精细且有迭代调优痕迹，不同角色行为差异显著；决策有可追溯推理链路，有量化评估手段，能识别并分析 bad case | 各角色有独立 Prompt 和基本合理行为，但 Prompt 粗糙、策略雷同；有日志但缺推理过程记录 | 所有角色共用 Prompt 或行为随机不合理；无法了解决策原因 |
| **多 Agent 协作与系统设计** | 20% | 上下文管理：每个 Agent 的对话历史、公共/私有信息如何维护与传递；技能管理：角色技能的抽象与调度逻辑设计；Agent 间博弈行为（伪装、欺骗检测、归票、站队等）；多 Agent 通信与协调机制 | 上下文管理清晰（公共/私有信息分离、历史管理合理），技能调度抽象良好（加新角色/技能改动小），Agent 间有明确博弈行为（归票、交叉验证、选择性暴露等） | 上下文有基本管理但不够精细，技能逻辑硬编码耦合度高；Agent 能按规则交互但缺主动博弈 | 无上下文管理（Agent 每轮无记忆或信息混乱），技能逻辑散落无设计；Agent 各自独立决策不参考他人 |
| **工程实现与系统完整度** | 30% | 对局引擎正确性与边界处理；信息隔离实现（无泄露）；前端可视化与交互体验；可观测性（日志/监控）；代码质量与规范；文档与演示材料完整度 | 对局全流程正确，边界处理完善；信息隔离严格经测试无泄露；前端直观好用，非技术人员能看懂；代码清晰、文档/视频齐全 | 核心流程跑通但部分边界出错；信息隔离基本有效；有前端但粗糙；有基本文档能跑起来 | 对局无法跑完或严重规则错误；信息隔离形同虚设；无前端或无文档，评委无法运行 |
| **进阶课题 — 评测+复盘** | 30% | 多维评测（发言/投票/技能）→关键决策复盘→反事实推演→结构化报告→Leaderboard | 构造含明显失误的对局，系统能精准定位失误并给改进建议；Leaderboard 能区分不同模型/Agent 版本能力 | 有基本多维评分和报告输出，但复盘深度不足或 Leaderboard 不完整 | 仅有胜负统计，无多维评测能力 |

### 加分项（不限于此）

| 加分项 | 说明 | 本项目现状 |
|---|---|---|
| 策略深度 | Agent 有明确的博弈策略设计，不同角色行为差异显著 | ✅ RoleStrategyCard + 6 角色独立策略卡 |
| 工程完整度超预期 | 错误处理、并发支持、监控告警等生产级能力 | ✅ 三级降级链 + AgentDecisionLog + GameHealthReport |
| 前端体验出色 | 有动画、状态可视化，非技术人员也能看懂对战 | ⚠️ Replay Viewer 单独规划 |
| 可扩展架构 | 加新角色或规则变体改动量小 | ✅ Skill Protocol + RoleRegistry + 规则配置分离 |
| 人机交互 | 真人玩家可加入对局与 Agent 混合博弈 | ✅ HumanAgent 已支持 |
| 进阶课题有独创性 | 方案有新意且效果可验证 | ✅ 可信知识回流驱动的轻量自进化 |

---

## 技术栈

- **后端**: Python 3.12 + FastAPI + WebSocket
- **前端**: Next.js 15 + React 19 + Tailwind CSS
- **数据库**: PostgreSQL 15 (Docker @ 127.0.0.1:5433, database: werewolf)
- **LLM**: 火山方舟 doubao-seed-2.0-pro (ep-20260514115354-k4jz4) / MiniMax
- **检索**: BM25 + 关键词倒排索引 (GPU-free)
- **配置**: YAML

## 项目结构

```
AIwerewolf/
├── CLAUDE.md                      # 项目速查（本文档）
├── README.md                      # 项目说明
├── docs/
│   ├── ARCHITECTURE.md            # ★ 系统架构总览（给评委）
│   ├── DATA_FLOW.md               # ★ 端到端数据流 & 证据链
│   ├── backend_acceptance_criteria.md  # 后端验收标准
│   ├── DEVELOPMENT_ISSUES.md      # 开发问题追踪 (50+ 条)
│   ├── PROJECT_STATUS.md          # 项目状态速览
│   ├── DOC_INDEX.md               # 文档索引
│   └── archive/                   # 历史设计文档 (34 篇)
├── configs/
│   ├── rule_variant_standard.yaml # 标准规则配置
│   ├── demo.yaml                  # 演示对局配置
│   └── strategy_library.yaml      # 策略知识库 (187 条)
├── backend/
│   ├── engine/            # 游戏引擎
│   │   ├── game.py              # WerewolfGame 主循环 (1721 行)
│   │   ├── visibility.py        # PlayerView 信息隔离
│   │   ├── models.py            # GameState, Player, Phase, Decision
│   │   └── roles/               # RoleRegistry (60+ 角色)
│   ├── agents/
│   │   ├── cognitive/     # ★ 主 Agent — Observe-Think-Act 架构
│   │   │   ├── agent.py          # CognitiveAgent (871 行)
│   │   │   ├── agent_loop.py     # AgentLoop (max 3 tool-call iterations)
│   │   │   ├── observe.py        # Observation + BeliefTracker
│   │   │   ├── memory.py         # 短期/长期记忆
│   │   │   ├── profiles.py       # MBTI + Role Profile
│   │   │   ├── prompts.py        # Prompt 构造 (3-layer)
│   │   │   ├── humanization.py   # 人格化发言
│   │   │   ├── retrieval_prod.py # BM25 + 倒排索引 + 4-filter 安全管线
│   │   │   ├── tools.py          # 6 个工具函数
│   │   │   ├── reflect.py        # 赛后反思
│   │   │   ├── wolf_team.py      # 狼队安全协调 (WolfTeamView)
│   │   │   └── repository.py     # 知识仓储存取
│   │   ├── heuristic.py    # 启发式 Agent（降级兜底）
│   │   ├── human_agent.py  # 真人玩家 Agent
│   │   └── characters.py   # Character 系统（32 个具名角色）
│   ├── eval/               # ★ 评测系统（Track B + Track C）
│   │   ├── per_step_scorer.py    # 三级评分级联 (Tier1→Tier2→Tier3)
│   │   ├── llm_judge.py          # LLM Judge Panel（三法官 + Critic）
│   │   ├── review.py             # 复盘系统 (CounterfactualAnalyzer)
│   │   ├── track_b.py            # Track B 发布管道
│   │   ├── post_game.py          # 赛后评分入口
│   │   ├── knowledge_abstractor.py    # 知识提取 (Track C)
│   │   ├── knowledge_confidence.py    # L0-L4 知识可信度 + 4-filter
│   │   ├── evolution.py          # 知识生命周期管理
│   │   └── types.py              # 共享数据类型
│   ├── protocols/          # 通信协议（Room/Snapshot/WebSocket）
│   ├── db/                 # 数据库
│   │   ├── models.py             # ORM (21 张表, SQLAlchemy)
│   │   ├── database.py           # 连接池 (10+10, pool_pre_ping)
│   │   └── persist.py            # 持久化层
│   ├── llm/                # LLM 客户端
│   └── ops/                # 运维
│       └── preflight.py          # 7 项启动预检
├── frontend/               # Next.js 观战 UI
├── tests/                  # 测试
├── scripts/                # 实验/验证脚本
│   ├── run_backend_full_strict.py # 全量严格验证
│   ├── multi_tier_experiment.py   # 多 Tier 对比实验
│   └── verify_visibility_strict.py # 信息隔离验证
└── references/             # 克隆的参考仓库（gitignored）
```

---

## AI 助手开工指引

接到任务后：
1. 读本文件（CLAUDE.md）了解项目目标与评判标准
2. 读 `docs/ARCHITECTURE.md` 了解系统架构
3. 读 `docs/DATA_FLOW.md` 了解端到端数据流
4. 动代码前检查对应模块的现有实现，避免重复
5. 跨模块改动先列计划

**铁律**：
- 每个非平凡改动必须有可量化的验证手段（测试/指标/对比实验）
- 不引入与现有架构冲突的重复实现
- 改动效果要能量化：对局完成率、信息泄露测试通过数、降级率、评测分数等

---

## 日常开发命令

```bash
# 启动预检（7 项：imports/db/llm/strategies/pool）
python -m backend.ops.preflight

# 全量严格验证（DB → LLM → 对局 → 评分 → 知识 → 报告）
python scripts/run_backend_full_strict.py

# 完整 LLM 流程（含 Track B/C）
python scripts/run_full_llm_pipeline.py

# 多 Tier 对比实验
python scripts/multi_tier_experiment.py

# 信息隔离验证（92 项边界检查）
python scripts/verify_visibility_strict.py

# 全量测试
pytest tests/ -q

# 启动后端
make dev

# 启动前端
cd frontend && npm run dev

# 数据库连接
psql -h 127.0.0.1 -p 5433 -U werewolf -d werewolf
# password: wolf_secret_2026
```

---

## 关键设计参考

### 阶段流转
夜晚：NIGHT_START → GUARD → WOLF → WITCH → SEER → NIGHT_RESOLVE
白天：DAY_START → BADGE_SIGNUP → BADGE_SPEECH → BADGE_ELECTION → DAY_SPEECH → VOTE → DAY_RESOLVE
特殊：HUNTER_SHOOT / WHITE_WOLF_KING_BOOM / BADGE_TRANSFER / GAME_END

### 角色列表
基础：Villager / Werewolf / Seer / Witch / Hunter / Guard
扩展：Idiot / WhiteWolfKing / Cupid / BigBadWolf / WolfCub 等 60+

### Prompt 三层架构（铁律！）
```
Layer 1: Persona (MBTI + 性格 + 说话风格) → 只控制"怎么说"
Layer 2: Role Identity (身份 + 能力边界 + 胜利条件) → 只定义"我是谁"
Layer 3: Strategy + Tools (检索到的策略 + 6 工具) → 只教"怎么玩"
```
**三层物理分离，Persona/Role 层不得包含任何玩法指导。**
策略知识只能从 Layer 3 进入 Prompt。

### 4-Filter 安全管线
```
检索 → confidence_allowed (L0-L3 only)
     → visibility_allowed (public/self/wolf/postgame)
     → leaks_current_game_private_info (no current-game leak)
     → applicability_matches (role/phase/rule/player_count)
     → top_k result
```

### 知识生命周期
```
candidate → active → deprecated
     ↑                    │
     └── promote.py ──────┘
     └── usage feedback ──┘ (3+ uses 全无效 → deprecated)
```

### 开发约定
- Python 代码使用 type hints
- 配置使用 YAML 格式
- 事件日志使用结构化 JSON
- 每个 Agent 只能看到其角色允许的信息（信息隔离）
- 参考仓库代码不直接复制，理解后重写
- 数据库变更写入 `backend/db/migrations/` 目录
- 新策略追加到 `configs/strategy_library.yaml`（单条 ≤ 60 字符）
