# Track B 完整设计 + 验收文档

> **版本**: v2.0 | **日期**: 2026-05-31
> **可视化**: 见 `track_b_dashboard.html`

---

## 0. Track B 是什么

Track B = **评测 + 复盘**，不是单纯打分。

```
游戏结束 → 多维评分(4层) → 证据链构建 → 反事实推演 → 复盘报告 → ValidAgent校验 → 发布
```

**评测**: 四层评分（规则+LLM+反事实混合），每条指标有论文出处。
**复盘**: 对局回顾 + 高光/失误定位 + 反事实推演 + 证据链追溯 + 前端交互看板。

---

## 1. 设计原则

### 1.1 Hybrid Scoring

**依据**: Rulers (Hong et al., arXiv:2601.08654, 2026)

- **规则**: 精确验证客观事实（投票目标、事件存在性）
- **LLM**: 语义判断（发言质量、推理一致性）— 必须输出 extractive evidence
- **校准**: Ridge回归 + 分位数映射（Morandi, 2026）

### 1.2 核心原则

1. 分数不由LLM直接决定（Rulers验证了LLM judge三大失效模式）
2. 每个结论必须有证据链（evidence_event_ids）
3. 反事实必须分清精确重算和估计推演
4. ValidAgent是质量门，不是评分器

---

## 2. 四层评分体系

```
FinalScore   = 0.15*L1 + 0.30*L2 + 0.25*L3 + 0.30*L4
ProcessScore = (0.30*L2 + 0.25*L3 + 0.30*L4) / 0.85
```

### L1 基础层 (100%规则) — WOLF (NeurIPS 2025) + AdvGameBench (UCLA 2025)

```
L1 = clamp(0.50*camp + 0.25*survival + 0.25*(1-penalties), 0, 1)
penalties: invalid(-0.10), fallback(-0.03), info_leak(-0.20)
```

### L2 角色层 (80%规则+20%LLM) — DVM (ICASSP 2025) + Beyond Survival (2025)

每个角色独立评分标准：
- 狼人: KnifeValue + DeceptionSuccess + VoteManipulation + ExposureRisk + TeamCoord
- 预言家: CheckValue + InfoConversion + VoteGuidance + RevealTiming
- 女巫: SaveValue + PoisonAccuracy + MedicineTiming + FriendlyFirePenalty
- 猎人: ShotAccuracy + ShotBasis + EndgameImpact
- 守卫: ProtectValue + ThreatPrediction + PatternAvoidance
- 村民: VoteAccuracy + ReasoningGroundedness + BeliefUpdate + FollowRisk

### L3 人格层 (35%规则+65%LLM) — VCU (2025) + WOLF (2025) + Rulers (2026)

```
PersonaConsistency = 0.15*PC1 + 0.20*PC2 + 0.30*PC3 + 0.20*PC4 + 0.15*PC5
PC1 (规则): 发言长度符合习惯 · PC2 (规则): 社交行为符合习惯
PC3-5 (LLM+证据): 推理方式/不确定/压力反应一致性

DeceptionScore (狼,全部规则): 0.40*操控+0.30*怀疑管理+0.30*身份保护
DetectionScore (好,全部规则): 0.40*狼识别+0.30*投票命中+0.30*抗欺骗
```

### L4 策略层 (60%规则+40%反事实) — LSPO (ICML 2025) + MaKTO (2025)

```
StrategyImpact  = 0.25*SI1(检索)+0.35*SI2(遵循)+0.40*SI3(改善·反事实)
RetrievalQuality = 0.40*RQ1(命中)+0.35*RQ2(利用)+0.25*RQ3(时效)
```

Track C 反馈: applied+improved→success++; applied+degraded→failure++

---

## 3. 反事实分析

**参考**: LSPO (ICML 2025) CFR + Beyond Survival (2025) Counterfactual Perturbation

| 类型 | 置信度 | 方法 | 示例 |
|------|--------|------|------|
| vote_flip | 1.00 | 精确重算票型 | 改一票→重算出局结果 |
| skill_swap | 0.90 | 局部重算结果 | 女巫毒狼→局部死者变化 |
| info_release | 0.65 | 怀疑度估计 | 预言家公开查杀→目标怀疑度↑ |

**边界**: estimated 反事实不能写成确定性结论。

---

## 4. Elo Rating

**参考**: Foaster.ai (2025) + ART (2025)

```
K=32, initial=1200, K_adj=K/n
expected = 1/(1+10^((opponent-player)/400))
4轨: Role · PersonaRole · StrategyVersion · Model
```

---

## 5. 开源校准数据集

| 数据集 | 规模 | 校准用途 | 链接 |
|--------|------|---------|------|
| **Werewolf-bench** (Foaster) | 4场·LLM轨迹+推理 | L1/L2基准 | github.com/Foaster-ai/Werewolf-bench |
| **LLMafia** (EMNLP 2025) | 33场·3593消息·人类反馈 | L2角色评分锚点 | huggingface.co/datasets/niveck/LLMafia |
| **Werewolf Among Us** (ACL 2023) | 199对话·26647标注 | L3发言评分锚点 | github.com/SALT-NLP/PersuationGames |
| **AIWolfDial 2024** | 13 Agent·5维NLP评测 | L3发言自然度锚点 | aclanthology.org/volumes/2024.aiwolfdial-1/ |
| **WereBench** (Panda Kill) | 80+场·100h·32.4M tokens | L4策略对齐锚点 | arxiv.org/abs/2510.11389 |

**校准流程**: 下载数据集 → 提取三元组 → 人工审核≥50条/维度 → Ridge回归 → 分位数映射

---

## 6. ValidAgent 10 Gate

| Gate | 检查 | 失败后果 |
|------|------|---------|
| G1 SchemaValidity | JSON合规 | 修复schema |
| G2 ReportCompleteness | 8章节齐全 | 补充缺失 |
| G3 EvidenceCoverage | 有evidence_event_ids | 补证据 |
| G4 FactConsistency | 事实可查 | 修正/删除 |
| G5 ScoreConsistency | 分数一致 | 重算 |
| G6 CounterfactualSoundness | 反事实边界 | 修正措辞 |
| G7 VisibilitySafety | 无信息泄露 | 脱敏 |
| G8 RecommendationGrounding | 策略有来源 | 溯源/删除 |
| G9 PresentationQuality | 中文质量 | 润色 |
| G10 AgentRobustness | fallback=0 | REJECT |

RepairLoop: 不通过→调工具修复→再校验·最多3轮→仍失败REJECTED

---

## 7. 验收清单 (20项)

| # | 标准 | 状态 |
|---|------|------|
| 1 | 自动生成 ReviewReport | ✅ |
| 2 | FinalScore + 完整分项 | ✅ |
| 3 | SpeechAct 分析 | ✅ |
| 4 | SuspicionMatrix | ✅ |
| 5 | BadCase 检测 | ✅ |
| 6 | Highlight 识别 | ✅ |
| 7 | 证据链 | ✅ |
| 8 | 3类反事实 | ✅ |
| 9 | ValidAgent 10 Gate | ✅ |
| 10 | RepairLoop | ✅ |
| 11 | Elo 4轨 | ✅ |
| 12 | Hybrid打分 | ✅ |
| 13 | Ridge校准框架 | ✅ |
| 14 | 开源数据集引用 | ✅ |
| 15 | HTML看板 | ✅ |
| 16 | 论文出处 | ✅ |
| 17 | LLM证据验证 | ✅ |
| 18 | 批量Runner | 🚧 |
| 19 | 人工锚点≥50/维度 | 🚧 |
| 20 | Leaderboard聚合 | ✅ |

---

## 8. 参考论文 (11篇)

| # | 论文 | 会议 | 用途 |
|---|------|------|------|
| 1 | WOLF | NeurIPS 2025 | L1+L3 deception/detection |
| 2 | Beyond Survival | arXiv 2025 | L2 per-role scoring |
| 3 | LSPO | ICML 2025 | L4 strategy + CFR |
| 4 | DVM | ICASSP 2025 | L2 per-role proficiency |
| 5 | MaKTO | arXiv 2025 | L4 preference feedback |
| 6 | Rulers | arXiv 2026 | Hybrid scoring methodology |
| 7 | Morandi | arXiv 2026 | Ridge calibration |
| 8 | Foaster.ai | Industry 2025 | Elo benchmark |
| 9 | ART | arXiv 2025 | K-factor + continuous Elo |
| 10 | AdvGameBench | UCLA 2025 | Robustness metrics |
| 11 | VCU Thesis | 2025 | Persona diversity |
