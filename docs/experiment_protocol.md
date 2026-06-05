# 实验协议

## 实验问题

1. **Track C 策略检索是否提高过程决策质量？**
   - 假设：开启 trackc 后 Agent 能检索到历史 lessons，避免重复犯错
   - 对比维度：win_rate / duration_s / fallback_count

2. **Anti-pattern 注入是否减少明显错误？**
   - 假设：静态反模式规则（如"不要在没查过人时报查验"）能阻止基础性失误
   - 对比维度：win_rate / fallback_count

3. **Both（anti_pattern + trackc）是否优于单独开启？**
   - 假设：静态规则 + 动态检索产生互补效应，既防止基础错误又提供情境策略
   - 对比维度：win_rate / fallback_count / duration_s

## 实验分组

| Tier | anti_pattern | track_c | 说明 |
|------|-------------|---------|------|
| **baseline** | false | false | 纯 MBTI + RoleStrategyCard（standard 层），无外部策略注入，无动态检索 |
| **anti_only** | true | false | MBTI + Role + anti_pattern 静态反模式注入（如"空发言不得分""投票给同伴扣分"） |
| **trackc_only** | false | true | MBTI + Role + BM25 动态策略检索（从 active 池搜索情境策略） |
| **both** | true | true | 全部开启：anti_pattern 静态规则 + trackc 动态策略检索 |

## 固定变量

| 变量 | 值 | 理由 |
|------|-----|------|
| **模型** | doubao-seed-2.0-pro | 主模型固定，排除模型版本噪音 |
| **角色配置** | Werewolf x2, Seer, Witch, Hunter, Guard, Villager | 7 人标准局，均衡阵营 |
| **Seed 范围** | baseline: [1000, 1000+N-1], anti_only: [2000, 2000+N-1], trackc_only: [3000, 3000+N-1], both: [4000, 4000+N-1] | 每组独立 seed 区间，跨组同 offset（如 baseline seed=1000 vs anti_only seed=2000 vs trackc_only seed=3000 vs both seed=4000）保证 MBTI 分配公平 |
| **Strategy Snapshot** | 实验前记录 active_count（活跃策略条数），记录时间戳 | 提供实验环境可追溯性。当前实现仅记录 active docs 数量；TODO: 添加 content_hash 支持以验证内容不变性 |
| **规则版本** | standard_competition_v1 | 标准竞技规则（无特殊扩展角色） |
| **Player Count** | 7 | 固定 7 人局 |
| **Character Pool** | 32 个具名 Character（张飞/诸葛亮/貂蝉等） | 人格分配由 seed 决定，固定 character pool |
| **Max Tokens** | 8000 | LLM 输出上限 |
| **Temperature** | 0.7 | 推理创造性控制 |
| **Speech Order** | 蛇形（snake） | 保证公平发言机会 |
| **Witch 配置** | 不可自救（standard_competition_v1 规则） | 防止女巫过于强势 |
| **Guard 配置** | 不可连续守同一人 | 防止守卫无风险操作 |

## 指标

### 当前实现指标

| 指标 | 定义 | 方向 | 优先级 |
|------|------|------|--------|
| **win_rate** | 阵营胜率（per role, team, MBTI） | 高游戏质量下均衡为佳 | P0 |
| **duration_s** | 单局时长（秒） | 性能参考 | P2 |
| **fallback_count** | 降级到 heuristic 的总次数 | 越低越好 | P2 |

### 计划指标（Planned）

以下指标在 `multi_tier_experiment.py` 中尚未实现，计划在答辩轮次中添加：

| 指标 | 定义 | 方向 | 优先级 |
|------|------|------|--------|
| **process_score** | 所有 decisions 的 overall_score 均值 | 越高越好 | P0 |
| **vote_accuracy** | 投票正确率（上帝视角：投敌对阵营 = 正确） | 越高越好 | P0 |
| **skill_efficiency** | 技能使用效率（如预言家查中狼人 / 总查验次数） | 越高越好 | P0 |
| **speech_quality** | 发言质量分（语义丰富度 + 逻辑一致性 + 信息密度） | 越高越好 | P1 |
| **invalid_action_count** | 无效操作次数（如投票给死人/技能目标非法） | 越低越好 | P0 |
| **strategy_retrieval_count** | Agent 调用 search_strategies 工具的总次数 | 仅 trackc/both 组有效 | P1 |
| **strategy_usage_count** | 策略实际被引用的次数（从 tool_trace + decision 中验证） | 越高越好（仅 trackc/both） | P1 |
| **anti_pattern_violation_count** | Agent 违反反模式规则的次数（如空发言、投同伴） | 越低越好（仅 anti/both） | P1 |
| **candidate_lessons_count** | 每局赛后从 ScoredStep 中提取的候选经验数 | 越多越好（上限限流） | P1 |
| **cost_per_game** | 每局 LLM token 消耗 x 当前模型单价 | 越低越好 | P2 |
| **llm_latency_p50** | LLM 调用延迟中位数（ms） | 越低越好 | P2 |
| **retrieval_latency_p50** | BM25 检索延迟中位数（ms） | 越低越好 | P2 |

## 统计方法

当前实现使用描述性统计（各角色/阵营/MBTI 的胜率）。统计显著性检验计划在答辩轮次中添加。

| 方法 | 用途 | 状态 |
|------|------|------|
| **Descriptive Statistics** | 按角色/阵营/MBTI 分组计算 win_rate | 已实现 |
| **Bootstrap 95% CI** | 评估各指标的不确定性区间 | Planned |
| **Permutation Test** | 检验组间胜率差异是否显著 | Planned |
| **Cohen's d** | 量化组间差异的效应量 | Planned |
| **Bonferroni Correction** | 多重比较校正 | Planned |

## 最小样本量

- 每组（Tier）：**12 局**（默认），推荐 **30+ 局**以获得统计显著性
- 总样本量：**48 局**（4 tiers x 12 games，默认）/ **120 局**（4 tiers x 30 games，推荐）

## 实验执行流程

```
1. for each tier in [baseline, anti_only, trackc_only, both]:
     for seed in tier.seed_range:
       game = run_game(seed, tier.config)
2. 每行结果写入 {tier}.jsonl
3. compile_stats() — 按角色/阵营/MBTI 汇总胜率
4. _print_comparison() — 输出格式化对比表到 stdout
5. 保存 summary.json（含 experiment_id, timestamps, tier 汇总）
```

## 报告生成

- `multi_tier_experiment.py` 输出：
  - `data/experiment/multi_tier/{tier}.jsonl` — 每局的原始结果（一行 JSON per game）
  - `data/experiment/multi_tier/results.jsonl` — 合并后的所有对局结果
  - `data/experiment/multi_tier/summary.json` — 汇总统计（experiment_id, 各 tier 的 game_count/error_count/avg_duration_s/total_fallbacks + 角色/阵营/MBTI 胜率）
- `_print_comparison()` 输出：
  - 团队胜率对比表（stdout）
  - 角色胜率对比表（stdout）
  - MBTI 胜率对比表（stdout）
  - Meta 对比表（game_count, error_count, avg_duration_s, total_fallbacks）（stdout）

## 策略快照（Strategy Snapshot）

当前实现为最小化版本：

- **记录内容**：active_count（活跃策略条数）+ timestamp
- **记录方式**：子进程启动时从 `strategy_knowledge_docs WHERE status='active'` 查询 COUNT
- **存储位置**：每条 JSONL 记录的 `strategy_snapshot` 字段
- **TODO**: 添加 content_hash 支持，以便验证实验期间策略内容未被修改

```json
{
  "strategy_snapshot": {
    "active_count": 42,
    "timestamp": 1717459200.0
  }
}
```

## 预期结果（假设）

1. **both > trackc_only > anti_only > baseline** 在 win_rate 上
2. **trackc_only** 在 strategy_usage_count 上最高（无 anti_pattern 干扰，Agent 更依赖检索）
3. **anti_only** 在 anti_pattern_violation_count 上最低（反模式直接阻止错误）
4. **baseline** 在 cost_per_game 上最低（无额外检索 token 消耗）

## 复现说明

1. 安装依赖：`pip install -r requirements.txt`
2. 配置 PostgreSQL 连接：`.env` 中设置 `DATABASE_URL`
3. 配置 LLM 密钥：`.env` 中设置对应模型的 API Key
4. 运行实验：`python scripts/multi_tier_experiment.py --games 12`
5. 查看结果：`cat data/experiment/multi_tier/summary.json | python -m json.tool`
