# 后端用户旅程

## Journey 1：运行一局完整 AI 对局

**输入**：`seed` / `player_count` / `strict_mode`

**步骤**：

1. **前置检查**
   - 检查 PostgreSQL 连接（20 张表 existence 验证）
   - 检查 LLM 客户端可用性（health check ping）
   - 检查策略库 active 文档数量 >= 最小阈值
   - 检查规则配置文件 `rule_variant_standard.yaml` 存在且可解析

2. **初始化对局**
   - 解析规则配置，确定本局阶段顺序和角色集合
   - 按玩家数量分配角色（如 7 人局：狼人x2, 预言家, 女巫, 猎人, 守卫, 村民）
   - 从 32 个 Character 池中分配 MBTI 人格（保证各阵营人格均衡）
   - 为每个角色加载对应 RoleStrategyCard（含 standard + anti_pattern 层）
   - 创建 CognitiveAgent 实例，注入 Memory + BeliefTracker + WolfTeamView
   - 生成 game_id，写入 `games` 表

3. **夜晚阶段**（按 `NIGHT_START → GUARD → WOLF → WITCH → SEER → NIGHT_RESOLVE` 顺序）
   - 对每个子阶段：遍历相应角色 Agent，执行 Observe → Think → Act
   - Agent 通过 PlayerView 获取当前可见信息
   - Agent 可选调用策略检索工具（search_strategies）查找相关策略
   - Agent 做出技能决策（守卫守人/狼人刀人/女巫用药/预言家查验）
   - 决策写入 `agent_decisions` 表
   - NIGHT_RESOLVE：结算夜晚结果（死亡玩家、女巫药品消耗标记）
   - 信息隔离：不同阵营的 PlayerView 按 Visibility 规则过滤
   - 异常处理：若 LLM 调用失败，自动降级到 heuristic 策略（如狼人随机刀、预言家随机查）

4. **白天阶段**（按 `DAY_START → BADGE_SIGNUP → BADGE_SPEECH → BADGE_ELECTION → DAY_SPEECH → VOTE → DAY_RESOLVE` 顺序）
   - BADGE_SIGNUP：Agent 决定是否竞选警长
   - BADGE_SPEECH：竞选者发表竞选发言
   - BADGE_ELECTION：所有存活玩家投票选警长
   - DAY_SPEECH：按发言顺序（蛇形/顺序），每个 Agent 发表白天发言
     - 发言内容基于 PlayerView + Memory + 检索到的策略知识
     - 支持 Humanization 人格化（语气词、角色口头禅）
   - VOTE：所有存活玩家投票放逐
   - DAY_RESOLVE：公布投票结果、被放逐者身份、触发遗言
   - 特殊处理：猎人死亡触发 HUNTER_SHOOT 阶段；猎人在毒杀情况下不可开枪

5. **终局判定**
   - 胜负条件检查（狼人全部死亡 → 好人胜；存活狼人数 >= 存活好人数 → 狼人胜）
   - 记录 `winner`、`end_day`、`end_phase` 到 `games` 表

6. **赛后管道**（post_game）
   - Reflect：每个 Agent 运行 reflect() 自我反思，产出 self_reflection 文本
   - Decision Save：确认所有 agent_decisions 已持久化到 DB
   - Score：PerStepScorer 三级评分级联
     - Tier 1：确定性评分覆盖所有决策，产出初始 correctness 分
     - Tier 2：对模糊决策（0.3 < correctness < 0.7）调用轻量 LLM 评分
     - Tier 3：对高影响+高分歧决策调用三法官 panel 评分
   - Speech Acts：分析每次发言的语义（声明、质疑、归票、表水等）
   - Knowledge Abstract：KnowledgeAbstractor 从低分步提取候选 lessons
     - 标记 is_mistake=True 的步骤 → 提取"不要做什么"
     - 标记 is_highlight=True 的步骤 → 提取"应该怎么做"
   - Candidate Lessons：写入 `strategy_knowledge_docs`（status=candidate）
   - 生成 PlayerReviewReport（每人一份）+ 全局 ReviewReport

**输出**：`game_id` / `logs` / `decisions` / `winner` / `review`

---

## Journey 2：查看一条决策证据链

**输入**：`game_id` / `player_id` / `phase`

**步骤**：

1. **从 DB 查询 agent_decisions**
   - SQL：`SELECT * FROM agent_decisions WHERE game_id=? AND player_id=? AND phase=?`
   - 返回该玩家在该阶段的完整决策记录

2. **解析 Observation（Agent 看到什么）**
   - 读取 `agent_decisions.observation` JSON 字段
   - 展开 PlayerView 结构：
     - `self_player`：自己的角色、身份、存活状态
     - `players`：每个其他玩家的公开信息（name、alive、role——角色对非狼阵营隐藏）
     - `public_events`：该阶段前所有公开事件（死亡公告、投票结果）
     - `private_events`：该玩家专属事件（查验结果、狼队讨论）
     - `known_wolves`：狼同伴列表（仅狼阵营可见）

3. **解析 Tool Trace（Agent 调用了哪些工具、命中了哪些策略）**
   - 读取 `parsed_action._auto_injected_strategies`：策略层自动注入的文档 ID
   - 读取 `parsed_action._tool_trace` 数组，每个元素包含：
     - `tool_name`：search_strategies / search_rules / recall_memory
     - `keywords`：Agent 生成的搜索关键词
     - `result_count`：命中结果数量
     - `result_summary`：Top-3 命中策略的摘要
     - `latency_ms`：检索耗时

4. **解析 Decision（Agent 做出了什么决策）**
   - 读取 `agent_decisions.raw_output`：LLM 原始输出文本
   - 读取 `agent_decisions.decision`：解析后的结构化决策
     - 发言决策：`speech_text` + `speech_type`（声明/质疑/归票/表水）
     - 投票决策：`vote_target` + `vote_reason`
     - 技能决策：`skill_used` + `skill_target` + `skill_reason`

5. **查询 Scoring（这个决策得了多少分）**
   - SQL：`SELECT * FROM evaluations WHERE decision_id=?`
   - 返回 DecisionScore 结构：
     - `correctness`、`reasoning_quality`、`timeliness`、`impact`
     - `overall_score`
     - `scoring_tier`（deterministic / light_llm / heavy_llm）
     - `evidence`：评分依据列表

6. **查询 Lesson（从这次决策中提取了什么知识）**
   - SQL：`SELECT * FROM strategy_knowledge_docs WHERE source_step_id=?`
   - 返回 AbstractedLesson 结构：
     - `target_role`：适用于哪个角色
     - `situation_pattern`：触发情境
     - `recommended_action`：推荐做法
     - `status`：candidate / active / deprecated
     - `confidence_score`：可信度分数

**输出**：Observation → Strategy Hit → Decision → Score → Lesson 完整链路

---

## Journey 3：运行一组实验

**输入**：experiment config（tier 定义、seed range、rule variant、固定变量）

**步骤**：

1. **生成 experiment_id**
   - 格式：`exp_{YYYYMMDD}_{HHMMSS}_{hash8}`
   - 写入 `evolution_tournaments` 表

2. **创建 Strategy Snapshot**
   - 冻结当前 active 策略池：将所有 active docs 的 id + content_hash + timestamp 记录下来
   - 存入 `evolution_rounds` 表，含 snapshot 元数据
   - 保证实验期间策略库不变，实验结果可复现

3. **对每个 Tier 启动独立子进程**
   - 4 个 Tier：baseline、anti_only、trackc_only、both
   - 每个 Tier 至少 30 局（保证统计显著性）
   - 使用多进程（`multiprocessing`），每个进程独立 PostgreSQL 连接
   - 固定 seed range：每个 Tier 使用独立不重叠的 seed 区间，但同 index 跨 Tier 保证 MBTI 分配公平
   - 每局记录：`game_id`、`experiment_id`、`tier`、`seed`
   - 每局赛后自动运行 post_game 管道

4. **进度监控**
   - 实时写入进度到 `evolution_rounds.status` JSON
   - 每完成一局记录：tier 进度、累计胜率、平均过程分
   - 异常处理：LLM 超时重试（最多 3 次）、DB 连接断开自动重连、单局失败不影响同 tier 其他局

5. **汇总统计**
   - 胜率：按阵营（werewolf_win_rate / villager_win_rate）
   - 过程分：所有 decisions 的 overall_score 均值 + 分布
   - 策略使用率：`strategy_usage_count / total_decisions`
   - 检索命中率：`strategy_hit_count / strategy_search_count`
   - bad_case 数量：`is_mistake=True` 的决策数
   - candidate_lessons_count：每局提取的知识条目数
   - cost_per_game：每局 LLM token 消耗 × 单价

6. **统计检验**
   - Bootstrap 95% CI（10000 次重采样）
   - Permutation test（组间胜率差异，10000 次置换）
   - Cohen's d（效应量，评估改进幅度）
   - 生成 Tier 对比表格 + 可视化图表

**输出**：`tier_summary` / `process_metrics` / `bootstrap_ci` / `leaderboard`
