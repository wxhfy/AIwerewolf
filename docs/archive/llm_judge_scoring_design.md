# LLM-as-Judge 可靠评估方案

## 设计依据

### 参考论文

| 论文 | 核心贡献 | 借鉴内容 |
|------|----------|----------|
| **RULERS** (Hong et al., Jan 2026) | 锁定量规 + 证据锚定 + 事后校准 | 评分必须引用具体事件ID，量规hash版本锁定 |
| **Auto-Arena** (ICLR 2025) | 多轮辩论 + 委员会裁判 | 3法官panel + Critic轮互相质疑，92% Spearman correlation |
| **CourtEval** (ACL 2025) | Grader + Critic + Defender 对抗 | 对抗性验证防止评分bias |
| **Ensemble k=8** (Lail & Markham, Apr 2026) | 集成投票 +13.5pp提升 | 多次采样取一致性 |
| **Pairwise > Rating** (Stanford, Sep 2025) | 成对比较优于绝对评分 | Bradley-Terry排名补充绝对评分 |
| **LLM-REVal** (PKU/UCLA, Oct 2025) | LLM偏好"LLM风格" | 跨模型族裁判，防自偏好bias |
| **JRH** (Dev et al., Mar 2026) | Judge Reliability Harness | 系统性扰动测试（格式/语义/长度/标签翻转） |

## 评分架构

### 三层级联

```
对局结束
  │
  ├─ Layer 1: 确定性评分（免费，0 bias，90%决策走此通道）
  │   ├─ 投票正确率：f(true_role, voted_target)
  │   ├─ 技能效率：f(action_type, target_role, outcome)
  │   ├─ 存活贡献：survival_rounds / total_rounds
  │   └─ 输出：per_step_score + game_level_deterministic_score
  │
  ├─ Layer 2: LLM Judge Panel（3法官 + 锁定量规，10%模糊决策）
  │   ├─ Strategist Judge：策略选择质量
  │   ├─ Logician Judge：逻辑一致性
  │   ├─ Psychologist Judge：社交/欺骗/说服效果
  │   │
  │   ├─ Critic Round：每个法官强制质疑最高分和最低分
  │   ├─ Revision Round：根据质疑调整评分
  │   └─ Aggregation：trimmed mean（去掉最高最低）
  │
  └─ Layer 3: 事后校准
      ├─ 自一致性：同一输入重复3次，方差阈值检查
      ├─ 跨模型验证：至少2个不同模型族参与
      ├─ 人类标注校准（20局anchors）
      └─ 可靠性报告：kappa + CI + judge_disagreement
```

### 对局级评分（Game-Level）

| 维度 | 权重 | 评判者 | 量规关键问题 |
|------|------|--------|-------------|
| strategy_score | 0.40 | Strategist Judge | "技能使用是否最优时机？投票是否有效推动阵营目标？" |
| logic_score | 0.30 | Logician Judge | "发言-投票-行动之间逻辑自洽？有没有矛盾？" |
| social_score | 0.30 | Psychologist Judge | "发言是否影响了他人的投票？欺骗/说服是否成功？" |
| composite | 1.00 | Aggregation | trimmed_mean(strategy, logic, social) |

### 逐步打分（Per-Step）

| 决策类型 | 确定性通道 | LLM通道触发条件 |
|----------|-----------|----------------|
| vote | 目标真实身份 vs 投票目标 | correctness ∈ [0.3, 0.7] 时调用LLM |
| attack | 击杀关键神职 vs 普通人 | 非关键神职且非自伤时调用 |
| divine | 查狼成功 vs 查好人 | 查好人且存活>2轮 |
| guard | 保护关键神职 vs 普通人 | 同晚有死亡且保护非关键 |
| witch_save | 救关键神职 vs 普通人 | 救了非关键神职 |
| witch_poison | 毒狼 vs 毒好人 | 毒了好人 |
| talk | N/A（无ground truth） | 全部走LLM通道（轻量，单法官） |

## 锁定量规设计（RULERS风格）

```yaml
rubric_version: "werewolf-v1.0"
rubric_hash: "sha256:abc123..."

strategist_rubric:
  S1_skill_timing:
    question: "该玩家是否在正确的时机使用了角色技能？"
    scale: [0, 2, 4, 6, 8, 10]
    anchors:
      0: "技能使用完全适得其反或严重浪费"
      5: "技能使用中规中矩，无特别亮点或失误"
      10: "每次技能使用都是最优时机+最优目标"
    evidence_required: true
    evidence_type: "event_id"

  S2_vote_effectiveness:
    question: "该玩家的投票策略是否有效？"
    scale: [0, 2, 4, 6, 8, 10]
    anchors:
      0: "每次投票都投了己方阵营或关键神职"
      5: "投票正确率约50%"
      10: "每次投票都精确投中了敌方关键目标"
    evidence_required: true
    evidence_type: "vote_event_ids"

logician_rubric:
  L1_speech_vote_consistency:
    question: "发言表达的观点与投票行为是否一致？"
    scale: [0, 2, 4, 6, 8, 10]
    anchors:
      0: "发言说投A但实际投了B，存在明显矛盾"
      5: "基本一致，偶有调整但可解释"
      10: "每轮发言与投票完全自洽，逻辑链条清晰"
    evidence_required: true
    evidence_type: "chat_event_ids + vote_event_ids"

psychologist_rubric:
  P1_table_influence:
    question: "该玩家的发言对后续他人投票产生了多大影响？"
    scale: [0, 2, 4, 6, 8, 10]
    anchors:
      0: "发言完全被忽略，无人跟进其观点"
      5: "发言有一定影响力，少数人参考其意见"
      10: "发言改变了票型走向，成为桌面核心意见领袖"
    evidence_required: true
    evidence_type: "chat_event_id + subsequent_vote_event_ids"
```

## 可靠性保障

| 措施 | 参考来源 | 实现方式 |
|------|----------|----------|
| 量规版本锁定 | RULERS | hash(rubric_yaml) 存入评分记录，修改量规=新版本 |
| 证据强制引用 | RULERS | 每条评分附带 event_id 列表，不可为空 |
| 跨模型裁判 | LLM-REVal | 3个法官使用不同模型族（例如 Doubao + DeepSeek + Kimi） |
| 位置随机化 | JRH | 每个法官看到的玩家顺序不同，消除position bias |
| 自一致性检查 | JRH | 同一输入重复3次，方差>0.2标记不可靠 |
| 对抗验证 | CourtEval | Critic轮强制质疑最高分和最低分 |
| 事后校准 | RULERS | 20局人类标注→ridge regression校准 |
| 成对比较 | Stanford | Bradley-Terry排名补充绝对评分 |

## 实现计划

### Phase 1: 确定性评分层（已有基础，补齐）
- `per_step_scorer.py` — 已经是确定性的 ✅
- 补齐：输出 evidence_event_ids，标记模糊区间

### Phase 2: LLM Judge Panel（新建）
- `eval/llm_judge.py` — 3法官panel + 锁定量规
- `eval/judge_rubric.py` — 量规定义 + 版本锁定
- `eval/judge_aggregator.py` — trimmed mean + Bradley-Terry

### Phase 3: Critics + 校准（新建）
- `eval/judge_critic.py` — 对抗质疑轮
- `eval/judge_calibrator.py` — 自一致性 + 事后校准

### Phase 4: 集成到对局流程
- `persist.py:save_game_end()` → 调用 LLM Judge Panel
- 评分结果存入 `Evaluation` 表
- 前端展示：逐步轨迹 + 对局级分数

## 成本控制

| 决策类型 | 占比 | 通道 | 单次成本 |
|----------|------|------|----------|
| vote/attack/divine/guard | 60% | 确定性 | $0 |
| witch_save/poison | 10% | 确定性 | $0 |
| talk (清晰) | 20% | 确定性 | $0 |
| talk (模糊) | 7% | LLM单法官 | ~$0.003 |
| 对局级评分 | 3% | LLM 3-panel | ~$0.05/game |

单局总成本约 $0.05-$0.10（仅对局级+模糊决策走LLM）。
