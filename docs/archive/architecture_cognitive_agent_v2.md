# CognitiveAgent 架构优化 — MBTI 个人知识库 + 对局复盘 + Dream Job

## Context

当前 CognitiveAgent 已完成 LLMAgent 能力融合（Profile 三层、BeliefTracker、Humanization、wolfcha 风格 Prompt），新增了三个核心能力：

1. **对局后学习**：每局结束后，Agent 自动做 MBTI 差异化复盘
2. **人格级知识库**：`StrategyKnowledgeDoc` 使用 `persona_scope` 字段，同一角色不同 MBTI 有独立知识
3. **后台知识管理**：`DreamJob` + `manage_knowledge.py` CLI 做知识库维护

## 设计依据（每个决策的出处）

### 决策 1: 三层架构 MBTI + Role + Strategy

| 参考来源 | 借鉴内容 |
|----------|----------|
| **wolfcha** (`references/wolfcha/src/types/game.ts`) | 双层层叠式角色扮演：Persona（MBTI/性格/说话风格）+ 游戏内 Role |
| **CrewAI** Role/Goal/Backstory 三层 | Agent 身份由 "谁 + 想要什么 + 为什么这样想" 定义 |
| **DVM 论文** (ICASSP 2025) Predictor→Decider→Discussor | 三组件各司其职，对齐我们的 Observe→Think→Act |

### 决策 2: 对局后 MBTI 差异化复盘

| 参考来源 | 借鉴内容 |
|----------|----------|
| **wolfcha** `generateGameAnalysis()` | 游戏结束后 REVIEW_MODEL 生成 Timeline + PersonalStats |
| **Claude Code learnings.md** | what worked / what failed / patterns / errors 四段式结构 |
| **Anthropic Context Engineering** | Write → Select → Compress → Isolate 四操作 |

### 决策 3: 个人知识库 = StrategyKnowledgeDoc + persona_scope

| 参考来源 | 借鉴内容 |
|----------|----------|
| **MemOS** (2025) | 记忆生命周期：Generated → Activated → Archived → Purged |
| **LangMem** | 四种记忆类型：Semantic/Episodic/Procedural/Short-term |
| **Memp: Procedural Memory** | 成功任务 → 可复用程序性知识，跨模型迁移 |

### 决策 4: Dream Job 后台知识管理

| 参考来源 | 借鉴内容 |
|----------|----------|
| **Claude Code AutoDream** | Orient → Collect → Integrate → Prune 循环 |
| **现有 `run_dream_job()`** | 已实现的基础设施，扩展为 persona-aware |

## 实现架构

```
Game Engine
  ↓ PlayerView
Observer + BeliefTracker
  ↓ Observation
Pipeline (persona-aware, 3-stage)
  ① Observe → ② Think(+个人知识库检索) → ③ Act
  ↓ Decision
CognitiveAgent
  ↓ finish() → Reflector → PostgreSQL
```

## 数据流

### 对局中（实时检索）
```
Agent.talk/vote → Pipeline.think()
  → retrieve_strategies(role, phase, persona_mbti="INTJ")
    → 优先 mbti:INTJ → 其次 role 级别 → 最后全局
    → 注入 Think prompt
```

### 对局后（复盘持久化）
```
Agent.finish(winner)
  → _reflect_on_game()
    → _collect_game_events()     # View + BeliefTracker
    → _collect_decisions()       # Memory
    → Reflector.reflect_game()   # LLM: "你是 INTJ 型 Werewolf..."
    → save_reflections_to_db()   # INSERT → strategy_knowledge_docs
```
