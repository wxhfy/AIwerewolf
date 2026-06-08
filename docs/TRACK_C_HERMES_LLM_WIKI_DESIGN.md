# Track C Hermes + LLM Wiki Design

> 日期：2026-06-08
> 目的：明确 Track C 的增量式新设计：在现有 StrategyKnowledgeDoc / Retriever / Evolution 基础上，增加 LLM Wiki 知识编译层，并把 Hermes-style 自进化外循环作为策略版本迭代入口。

## 1. 设计结论

Track C 不需要推翻当前实现。新的设计是三层组合：

```text
LLM Wiki Layer        人类和 LLM 共读共写的策略知识编译层
Hermes Evolution     从复盘和 wiki 中提出 candidate patch，并用 A/B 验证
Runtime Retrieval    PostgreSQL 策略池，负责对局中安全、低延迟检索
```

当前已实现的是 Runtime Retrieval 和 Hermes Evolution 的核心骨架；新增的版本化知识层把 runtime strategy pool 从“经验条目集合”升级为“可迭代策略资产”：后续策略必须带有代际、成熟度、验证时间和替代关系，只有验证后的 refined / canonical 版本才会在检索中获得优先权。

## 2. 当前已有能力

| 能力 | 当前入口 | 状态 |
|---|---|---|
| 复盘到 lesson | `backend/eval/knowledge_abstractor.py` | 已实现 |
| 结构化知识表 | `strategy_knowledge_docs` / `backend/db/models.py` | 已实现 |
| 知识生命周期 | `candidate / active / deprecated` | 已实现 |
| 对局中检索 | `backend/agents/cognitive/retrieval_prod.py` | 已实现 |
| 工具调用归因 | `retrieved_knowledge_ids` / `knowledge_usage_feedback` | 已实现 |
| DreamJob | `backend/eval/evolution.py::DreamJob` | 已实现 |
| Hermes hook | `backend/eval/evolution.py::HermesEvolutionHook` | 骨架已实现 |
| Patch / tournament | `StrategyPatch` / `EvolutionTournament` | 基础设施已实现 |

因此本次设计调整应优先增加文档、wiki 文件结构和脚本，不应先改游戏引擎、Agent 协议或 DB schema。

## 3. 新的端到端闭环

```text
Play
  GameEvent / AgentDecision / PlayerView
    ↓
Evaluate
  Track B ScoredStep / PublishedReview / report
    ↓
Raw Sources
  对局日志、复盘报告、策略使用反馈、A/B 实验结果
    ↓
LLM Wiki Compile
  Markdown 策略百科：角色、阶段、概念、实验、版本日志
    ↓
Hermes DreamJob
  从 approved reviews + wiki 共识中提出 candidate lessons / patches
    ↓
Validation
  安全过滤、证据检查、paired-seed A/B、promote / rollback
    ↓
Runtime Strategy Pool
  strategy_knowledge_docs(active) / role_strategy_cards(active)
  version_group / knowledge_epoch / maturity / supersedes_doc_ids
    ↓
Agent Retrieval
  CognitiveAgent 在下一局按 role / phase / persona 检索策略
    ↓
Usage Feedback
  knowledge_usage_feedback 反哺 wiki、DreamJob 和知识生命周期
```

## 4. 三层职责边界

### 4.1 LLM Wiki Layer

职责：

- 把 Track B 复盘、实验结果和策略使用反馈编译成 Markdown 页面。
- 维护 `index.md`、`log.md`、角色页、阶段页、概念页和实验页。
- 为人类、LLM 和答辩展示提供可读的长期策略知识。
- 记录策略共识、证据来源、开放问题和版本变化。

不负责：

- 不直接给正在对局的 Agent 注入内容。
- 不绕过 `candidate / active / deprecated` 生命周期。
- 不承担当前局私有信息过滤。

### 4.2 Hermes Evolution Layer

职责：

- 从 approved reviews 和 wiki 共识中提炼 candidate lesson。
- 生成 `StrategyPatch` 或 `RoleStrategyCard` candidate version。
- 通过安全检查、A/B tournament、leaderboard 和 usage feedback 决定 promote / rollback / needs_more_trials。
- 把通过验证的策略同步到 runtime strategy pool。

不负责：

- 不直接修改游戏规则。
- 不把未验证 wiki 内容直接晋级为 active。
- 不用单局胜负替代 paired-seed 或多局证据。

### 4.3 Runtime Retrieval Layer

职责：

- 保存可执行的策略知识：`strategy_knowledge_docs`、`role_strategy_cards`、`knowledge_usage_feedback`。
- 用 confidence / visibility / privacy / applicability 过滤策略。
- 支持低延迟 BM25 / 倒排索引 / rerank 检索。
- 维护策略版本语义：`version_group` 表示同一策略主题，`knowledge_epoch` 表示演化代际，`doc_version` 表示策略版本，`maturity` 区分 `raw / refined / canonical`，`supersedes_doc_ids` 标记被新策略替代的旧策略。
- 检索排序不采用简单“越新越好”，而是优先考虑相关性、质量、使用反馈、验证新鲜度和成熟度；未验证的 raw candidate 不会压过稳定 active 策略。
- 记录每次检索和使用情况，用于验证 Track C 是否真的进入决策。

不负责：

- 不作为人类浏览的主要界面。
- 不承载长篇策略推导、概念解释和实验叙事。

## 4.4 版本化策略知识层

Track C 的策略知识分三种成熟度：

```text
raw        赛后复盘或 wiki 同步产生的原始候选经验，只能低优先级参与候选池
refined    通过质量门槛、证据复核或 promote 流程的可用策略
canonical  经过 A/B、使用反馈或人工审核后沉淀的长期策略卡/accepted patch
```

同一主题下的策略通过 `version_group` 聚合。新版本通过验证后，可以在 `supersedes_doc_ids` 中声明替代旧版本；runtime retriever 会过滤被替代的旧文档，避免早期高分经验长期污染 Agent prompt。

这和常见 RAG 记忆池的区别是：系统不是把所有历史经验按相似度塞回上下文，而是把经验先进入候选层，再通过证据、反馈和版本管理蒸馏成稳定策略。后代版本更精炼，但前提是它经过验证；单纯“更新时间更晚”的 raw lesson 不会自动成为最高优先级。

## 5. Wiki 文件结构

建议新增：

```text
docs/wiki/
├── index.md
├── log.md
├── schema/
│   └── track-c-wiki-schema.md
└── track-c/
    ├── overview.md
    ├── roles/
    │   ├── Werewolf.md
    │   ├── Seer.md
    │   ├── Witch.md
    │   ├── Hunter.md
    │   ├── Guard.md
    │   └── Villager.md
    ├── phases/
    │   ├── DAY_SPEECH.md
    │   ├── DAY_VOTE.md
    │   └── NIGHT_WOLF_ACTION.md
    ├── concepts/
    │   ├── bluff.md
    │   ├── badge-flow.md
    │   └── self-kill.md
    └── experiments/
        ├── retrieval-policy-ablation.md
        └── track-c-ab.md
```

Obsidian 可以直接打开 `docs/wiki/` 作为 vault。`.obsidian/` 本地配置不建议进入 GitHub，除非只提交轻量、无个人路径的团队配置。

## 6. Wiki 页面格式

每个策略页建议包含 frontmatter：

```yaml
---
type: strategy_wiki
scope: role
role: Werewolf
phase: DAY_SPEECH
status: draft
source_docs:
  - strategy_knowledge_docs:example
source_reports:
  - published_reviews:example
last_compiled: 2026-06-08
tags:
  - track-c
  - speech
---
```

正文建议固定为：

```text
# 标题

## Current Consensus
当前策略共识，只写可复用结论。

## Evidence
引用复盘、策略文档、A/B 结果或使用反馈。

## Runtime Candidates
可以同步进 StrategyKnowledgeDoc / RoleStrategyCard 的候选项。

## Conflicts
与其他策略的冲突、适用条件和反例。

## Open Questions
还缺什么实验或证据。
```

## 7. 增量落地步骤

### Step 1：建立 wiki 骨架

- 新增 `docs/wiki/index.md`、`docs/wiki/log.md`、`docs/wiki/schema/track-c-wiki-schema.md`。
- 新增角色、阶段和实验页的最小页面。
- 不改后端代码。

### Step 2：增加 ingest 脚本

新增 `scripts/wiki_ingest_track_c.py`：

- 读取 `published_reviews`、`strategy_knowledge_docs`、`evolution_tournaments`、`knowledge_usage_feedback`。
- 生成或更新 wiki 页面。
- 把原始证据写入页面的 `Evidence` 和 `Runtime Candidates`。
- 追加 `docs/wiki/log.md`。

### Step 3：增加 lint 脚本

新增 `scripts/wiki_lint_track_c.py`：

- 检查孤儿页面、缺少 source、frontmatter 缺字段。
- 检查 wiki 页面引用的 DB doc 是否存在。
- 检查 wiki 中标记 `active` 但 DB 中已 `deprecated` 的冲突。

### Step 4：增加 sync 脚本

新增 `scripts/wiki_sync_strategy_docs.py`：

- 只同步 `Runtime Candidates` 中明确标记为 `approved_for_candidate` 的内容。
- 新内容进入 `strategy_knowledge_docs(status="candidate")`。
- 仍需经过现有 promote / A/B / usage feedback 才能变成 `active`。

## 8. 验收口径

增量实现完成后，应能证明：

- `docs/wiki/index.md` 能作为 LLM 和人类进入 Track C 知识库的入口。
- 每条 wiki 策略结论都有 source report、source doc 或 experiment evidence。
- Wiki 能被 Obsidian 打开并通过 links / tags 浏览。
- Wiki 内容不会直接进入 Agent prompt；Agent runtime 仍从 DB 策略池检索。
- Wiki sync 只写 candidate，不直接写 active。
- `knowledge_usage_feedback` 和 A/B 结果能反向更新 wiki 的证据和状态。

## 9. 风险与护栏

| 风险 | 护栏 |
|---|---|
| Wiki 内容未经验证就污染 Agent | Wiki 只生成 candidate，不直接 runtime 注入 |
| 复盘里的上帝视角泄漏到当前局 | Runtime 仍走 visibility / privacy 过滤；wiki 页面标记 postgame evidence |
| LLM 编译时改丢证据 | 每页必须保留 source refs，lint 检查缺失来源 |
| Obsidian 配置污染仓库 | 不提交个人 `.obsidian/` 配置 |
| 自进化效果被夸大 | promote 必须基于 A/B、usage feedback 或明确质量门槛 |

## 10. 推荐表述

答辩或文档中建议统一描述：

> Track C 采用 Hermes-style 自进化外循环和 LLM Wiki 知识编译层。Track B 复盘先成为 raw evidence，LLM Wiki 将证据编译为可维护的角色/阶段/概念策略百科；DreamJob 基于这些知识提出 candidate strategy patches，经安全过滤、A/B tournament 和使用反馈验证后，晋级为 active 策略，并由 Retriever 回流到下一局 Agent。
