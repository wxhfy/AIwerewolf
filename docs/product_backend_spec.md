# AI Werewolf Agent Arena — 后端产品规格

## 产品定位
一个用于验证多智能体协作/对抗、信息隔离、过程评测和策略自进化的狼人杀 Agent Team 实验平台。

## 核心用户
1. **评委/观众**：看一局 AI 狼人杀是否完整、可信、可追溯。关注对局引擎的规则正确性、信息隔离的严格程度、以及决策推理链路的可审计性。
2. **研究者/开发者**：比较不同 Agent 配置的能力。关注 Prompt 调优效果、策略检索命中率、评分校准度、Leadboard 的可区分性。
3. **课程项目方**：验证基础要求和 Track B（评测+复盘）/ Track C（轻量自进化）进阶能力。关注系统完整度、文档完备性、实验可复现性。

## 核心能力

### 1. 完整狼人杀对局引擎
标准 12 人局和 7 人局。完整阶段流转：
- 夜晚：NIGHT_START → GUARD → WOLF → WITCH → SEER → NIGHT_RESOLVE
- 白天：DAY_START → BADGE_SIGNUP → BADGE_SPEECH → BADGE_ELECTION → DAY_SPEECH → VOTE → DAY_RESOLVE
- 特殊阶段：HUNTER_SHOOT / WHITE_WOLF_KING_BOOM / BADGE_TRANSFER / GAME_END
- 边界处理：狼刀空刀/自刀、女巫双药使用判重、猎人被毒不可开枪等
- 配置驱动：规则变体通过 `rule_variant_standard.yaml` 配置，角色通过 RoleRegistry 注册

### 2. 多角色 CognitiveAgent
Observe-Think-Act 架构，6 基础角色各有独立策略卡：
- Seer / Witch / Hunter / Guard / Villager / Werewolf
- 每个角色有专属 RoleStrategyCard（含 standard 和 anti_pattern 两层策略）
- 32 个具名 Character（张飞、诸葛亮、貂蝉等），绑定 MBTI 人格
- Memory 系统：短期记忆（近 N 轮事件）+ 长期记忆（知识沉淀）
- BeliefTracker：维护对其他玩家的身份信念
- WolfTeamView：狼队安全协调，共享狼同伴信息和战术约定
- Humanization：人格化发言（语气词、角色口头禅、情绪波动）

### 3. 严格信息隔离
PlayerView 按角色/阵营过滤，每个 Agent 只能看到：
- `self_player`：自己的完整信息
- `players`：其他玩家的公开信息（角色/身份/技能结果对狼以外阵营不可见）
- `public_events`：所有人可见的事件（白天发言、投票结果、死亡公告）
- `private_events`：仅该玩家可见的事件（查验结果、狼队讨论）
- `known_wolves`：仅狼队可见的狼同伴信息
- 信息泄露检查覆盖 12 项边界条件（预言家查验泄露、女巫用药泄露等）

### 4. Agent 决策追踪
Observation → Tool Call → Decision 完整链路，`agent_decisions` 表持久化：
- `observation`：Agent 在决策时看到的完整 PlayerView
- `parsed_action._auto_injected_strategies`：策略层自动注入的策略文档 ID
- `parsed_action._tool_trace`：Agent 调用了哪些检索工具、搜索关键词、命中结果
- `raw_output`：LLM 原始输出
- `decision`：解析后的结构化决策（发言文本、投票目标、技能目标）
- `model` / `tokens_used` / `latency_ms`：模型调用元数据

### 5. 策略知识库检索
BM25 + 关键词倒排索引，GPU-free 设计：
- 三层隔离：active（生产中）/ candidate（待验证）/ deprecated（已废弃）
- Agent 通过工具调用（tool call）主动检索策略，非强制注入
- 检索关键词由 Agent 根据当前情境生成（如"被查杀应对""多人对跳"）
- 策略文档含 `target_role`、`situation_pattern`、`trigger_conditions` 等元数据用于精准匹配
- 实验前可创建 strategy_snapshot 冻结 active 池，保证可复现性

### 6. 赛后过程评分
三级评分级联（Three-Tier Cascade），平衡成本与精度：
- **Tier 1 确定性评分**：基于硬规则的自动评分（如"空发言"→0 分、"投票投己方预言家"→满分），覆盖约 85% 决策，零成本、100% 可复现
- **Tier 2 轻量 LLM**：对 correctness ∈ [0.3, 0.7] 模糊决策进行单 Judge LLM 评分，覆盖约 12% 决策
- **Tier 3 三法官**：3-judge panel 评高影响力 + 高分歧决策，覆盖约 3% 决策
- 评分维度：correctness（正确性）、reasoning_quality（推理质量）、timeliness（时机把握）、impact（影响力）
- 每步产出 ScoredStep（含 is_mistake / is_highlight 判定）

### 7. 复盘报告和 Bad Case 定位
PerStepScorer + KnowledgeAbstractor 联动：
- PerStepScorer：逐步评分，标记 is_mistake（score ≤ 0.30）和 is_highlight（score ≥ 0.75）
- KnowledgeAbstractor：从低分步提取 lesson，含 situation_pattern / trigger_conditions / recommended_action
- 反事实推演：对关键失误生成"如果当时这样做会怎样"的替代方案
- 结构化报告：PlayerReviewReport（每人一份），含得分汇总、失误列表、改进建议
- 全局报告：阵营对比、阶段分布、策略使用率、知识增长趋势

### 8. Candidate Lesson 入库
赛后知识提取，默认不污染 active 池：
- 每局赛后自动运行 KnowledgeAbstractor
- Extracted lessons 写入 PostgreSQL（status=candidate），带 source_game_id 溯源
- 晋升 to active 需人工审核或规则阈值（如多个 source 在不同局中确认该 lesson）
- 晋升后记录 strategy_patches，支持回滚
- Track C 闭环：lesson 入库 → 后续对局检索 → 决策改进 → 新数据验证

### 9. 实验分组和 Leaderboard
四组对比实验：
- `baseline`：纯 MBTI + Role，不开启 Track C，不注入 anti_pattern
- `anti_only`：静态反模式注入（如"不要在没查过人时报查验"）
- `trackc_only`：仅动态策略检索（从知识库 BM25 检索）
- `both`：anti_pattern + trackc 全部开启
- 每组最少 30 局，固定 seed range，保证跨组可比性
- Leaderboard 按胜率 + 过程分 + 策略使用率三维排序
- 统计方法：Bootstrap 95% CI + Permutation test + Cohen's d

## 技术栈
- **后端**：Python 3.13 / FastAPI + asyncio / SQLAlchemy / PostgreSQL
- **AI**：DeepSeek V4 / 豆包 Seed 2.0 Pro（通过 LLM 客户端抽象层接入，支持多模型切换）
- **检索**：BM25 + 关键词倒排索引（GPU-free，生产级可用）
- **前端**：Next.js + TypeScript + Tailwind CSS（观战 UI + Replay Viewer）
- **配置**：YAML 格式（规则变体、策略库、角色策略卡）
- **通信**：WebSocket（实时对局状态推送）

## 数据流
```
对局开始
  → Agent 创建（分配角色 + MBTI + 策略卡）
  → 阶段循环：夜晚技能 → 白天发言/投票 → 胜负判定
  → 每步 Agent 决策：Observation → Tool Call → LLM 推理 → Decision
  → agent_decisions 持久化到 DB
  → 赛后 post_game 管道：
      1. reflect：Agent 自我反思
      2. score：PerStepScorer 三级评分
      3. speech_acts：发言语义分析
      4. scored_steps：Mistake/Highlight 标记
      5. review：PlayerReviewReport 生成
      6. abstract：KnowledgeAbstractor 提取候选
      7. candidate lessons → 写入 strategy_knowledge_docs (status=candidate)
      8. (可选) 人工晋升 → status=active → 下局可检索
```

## 系统边界
- **不在范围内**：实时多人联机、移动端 App、训练自有 LLM 模型、付费商用
- **在范围内**：离线对局评测、实验对比、知识回流、答辩展示
