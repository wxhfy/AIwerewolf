# Track B: 评测+复盘 完整设计

## 架构总览

```
对局结束
  │
  ├─ Layer 1: 数据持久化
  │   ├─ GameState → Game/Player/GameEvent/AgentDecision/Vote/Snapshot (PostgreSQL)
  │   └─ persist.py:save_game_end()
  │
  ├─ Layer 2: 评分系统 (Scoring)
  │   ├─ 确定性评分 (per_step_scorer.py) — 每步决策 correctness/reasoning/timeliness/impact
  │   ├─ LLM Judge Panel (llm_judge.py) — 3法官面板 (Strategist/Logician/Psychologist)
  │   │   ├─ 锁定量规 (judge_rubric.py) — RULERS风格，hash版本锁定
  │   │   ├─ Critic Round — 对抗性质疑最高/最低分
  │   │   └─ Aggregation — trimmed mean
  │   └─ 对局级评分: strategy_score + logic_score + social_score → composite
  │
  ├─ Layer 3: 复盘分析 (Review)
  │   ├─ 全局复盘 (Game-Level)
  │   │   ├─ MetricsCalculator — 12维对局级指标
  │   │   ├─ BadCaseDetector — 10种失误检测
  │   │   ├─ ReviewBonusDetector — 11种加分项
  │   │   ├─ TurningPointDetector — 关键转折点
  │   │   ├─ CounterfactualAnalyzer — 13种反事实推演 (精确重算)
  │   │   ├─ SpeechActAnalyzer — 逐条发言行为分析
  │   │   └─ SuspicionMatrixBuilder — 怀疑网络矩阵
  │   │
  │   ├─ 个人复盘 (Player-Level)
  │   │   ├─ DecisionTrajectory — 决策质量轨迹 (per_step_scorer数据)
  │   │   ├─ SpeechStanceEvolution — 发言立场演变 (SpeechAct数据)
  │   │   ├─ VoteFlowDiagram — 投票流向图
  │   │   ├─ MBTI Reflection — 人格视角个人复盘 (reflect.py)
  │   │   └─ PersonalLearnings — 个人经验提取 → C Track
  │   │
  │   └─ 可视化 (Visualization)
  │       ├─ SVG Charts (VisualReportAgent)
  │       │   ├─ Story Banner — 对局概览横幅
  │       │   ├─ Timeline Ribbon — 关键转折点时间线
  │       │   ├─ Suspicion Heatmap — 怀疑矩阵热力图
  │       │   ├─ Decision Trajectory — 决策轨迹折线图
  │       │   ├─ Vote Flow — 投票流向桑基图
  │       │   └─ Score Radar — 多维雷达图
  │       └─ HTML Report (HTMLReviewRenderer)
  │
  ├─ Layer 4: 验证+发布 (Validation)
  │   ├─ TrackBValidator — 9道验证门
  │   ├─ ReviewRepairLoop — 自动修复 (最多3轮)
  │   └─ PublishedReview → PostgreSQL
  │
  └─ Layer 5: Leaderboard
      ├─ LeaderboardAggregator — 按角色/模型/版本聚合
      └─ get_role_model_leaderboard — 交叉矩阵排行
```

## B→C Track 连接

```
B Track (复盘)
  │
  ├─ 全局复盘 → PublishedReview
  │     └─ extract_strategy_knowledge_from_game() → StrategyKnowledgeDoc (全局)
  │
  └─ 个人复盘 → reflect.py:Reflector
        ├─ MBTI视角反思 (16种MBTI各有独立反思角度)
        ├─ reflections_to_knowledge_docs() → persona_scope知识
        └─ save_reflections_to_db() → StrategyKnowledgeDoc (个人)
              │
              └─ C Track: DreamJob
                    ├─ 读取 persona_scope 知识
                    ├─ 冲突解决 + Prune
                    ├─ 生成 StrategyPatch
                    └─ 下次对局: retrieve_strategies(persona_mbti=...)
```

## 评分系统

### 对局级评分 (Game-Level)

| 维度 | 权重 | 评判者 | 方法 |
|------|------|--------|------|
| strategy_score | 0.40 | Strategist Judge | LLM + 锁定量规 S1/S2 |
| logic_score | 0.30 | Logician Judge | LLM + 锁定量规 L1/L2 |
| social_score | 0.30 | Psychologist Judge | LLM + 锁定量规 P1/P2 |
| composite | 1.00 | trimmed_mean | 去掉最高最低取中位 |

### 逐步评分 (Per-Step)

| 决策类型 | 确定性通道 | LLM通道 |
|----------|-----------|---------|
| vote | 目标真实身份 vs 投票目标 | correctness ∈ [0.3, 0.7] 时 |
| attack | 击杀关键神职 vs 普通人 | 非关键且非自伤时 |
| divine | 查狼 vs 查好人 | 查好人且存活>2轮 |
| guard | 保护关键神职 vs 普通人 | 同晚死亡且保护非关键 |
| witch_save/poison | 目标身份比对 | 毒/救了好人时 |
| talk | N/A (speech act analysis) | 全部走LLM (轻量单法官) |

## 可视化组件

| 组件 | 类型 | 数据源 | 参考来源 |
|------|------|--------|----------|
| Story Banner | SVG | GameState.winner + players | — |
| Timeline Ribbon | SVG | TurningPoint[] | — |
| Suspicion Heatmap | SVG | SuspicionSnapshot[] | WOLF (NeurIPS 2025) |
| Decision Trajectory | SVG line | DecisionScore[] | RiftRewind |
| Vote Flow | SVG sankey | VoteSnapshot[] | — |
| Score Radar | SVG radar | GameLevelScore | — |
| Speech Stance Evolution | SVG area | SpeechAct[] × rounds | WOLF suspicion timeline |
| Personal Reflection Card | HTML | ReflectionResult | reflect.py |

## 参考来源

- **RULERS** (Hong et al., Jan 2026): 锁定量规 + 证据锚定 + 事后校准
- **Auto-Arena** (ICLR 2025): 多法官委员会辩论，92% Spearman
- **CourtEval** (ACL 2025): Grader + Critic + Defender 对抗验证
- **WOLF** (NeurIPS 2025): 狼人杀 suspicion 追踪 + 跨感知矩阵
- **TRACE** (2026): 策略偏离热力图 + 自动叙事生成
- **Mentiss**: 3D Replayer + BYOM 评测
- **G-Eval** (2026): LLM-as-Judge 生产最佳实践
