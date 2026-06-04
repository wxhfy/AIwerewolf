# 实验协议

## 实验问题

1. **Track C 策略检索是否提高过程决策质量？**
   - 假设：开启 trackc 后 Agent 能检索到历史 lessons，避免重复犯错
   - 对比维度：vote_accuracy / speech_quality / skill_efficiency / invalid_action_count

2. **Anti-pattern 注入是否减少明显错误？**
   - 假设：静态反模式规则（如"不要在没查过人时报查验"）能阻止基础性失误
   - 对比维度：anti_pattern_violation_count / invalid_action_count / speech_quality

3. **Both（anti_pattern + trackc）是否优于单独开启？**
   - 假设：静态规则 + 动态检索产生互补效应，既防止基础错误又提供情境策略
   - 对比维度：win_rate / 过程分 / strategy_retrieval_count

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
| **Seed 范围** | baseline: [1, 30], anti_only: [101, 130], trackc_only: [201, 230], both: [301, 330] | 每组独立 seed 区间，跨组同 index（如 baseline seed=1 vs anti_only seed=101）保证 MBTI 分配公平 |
| **Strategy Snapshot** | 实验前冻结 active docs | 阻止实验期间新增 lesson 污染检索结果 |
| **规则版本** | standard_competition_v1 | 标准竞技规则（无特殊扩展角色） |
| **Player Count** | 7 | 固定 7 人局 |
| **Character Pool** | 32 个具名 Character（张飞/诸葛亮/貂蝉等） | 人格分配由 seed 决定，固定 character pool |
| **Max Tokens** | 8000 | LLM 输出上限 |
| **Temperature** | 0.7 | 推理创造性控制 |
| **Speech Order** | 蛇形（snake） | 保证公平发言机会 |
| **Witch 配置** | 不可自救（standard_competition_v1 规则） | 防止女巫过于强势 |
| **Guard 配置** | 不可连续守同一人 | 防止守卫无风险操作 |

## 指标

### 主要指标

| 指标 | 定义 | 方向 | 优先级 |
|------|------|------|--------|
| **win_rate** | 阵营胜率：werewolf_win_rate / villager_win_rate | 高游戏质量下均衡为佳 | P0 |
| **process_score** | 所有 decisions 的 overall_score 均值 | 越高越好 | P0 |
| **vote_accuracy** | 投票正确率（上帝视角：投敌对阵营 = 正确） | 越高越好 | P0 |
| **skill_efficiency** | 技能使用效率（如预言家查中狼人 / 总查验次数） | 越高越好 | P0 |
| **speech_quality** | 发言质量分（语义丰富度 + 逻辑一致性 + 信息密度） | 越高越好 | P1 |
| **invalid_action_count** | 无效操作次数（如投票给死人/技能目标非法） | 越低越好 | P0 |

### 辅助指标

| 指标 | 定义 | 方向 | 优先级 |
|------|------|------|--------|
| **strategy_retrieval_count** | Agent 调用 search_strategies 工具的总次数 | 仅 trackc/both 组有效 | P1 |
| **strategy_usage_count** | 策略实际被引用的次数（从 tool_trace + decision 中验证） | 越高越好（仅 trackc/both） | P1 |
| **anti_pattern_violation_count** | Agent 违反反模式规则的次数（如空发言、投同伴） | 越低越好（仅 anti/both） | P1 |
| **candidate_lessons_count** | 每局赛后从 ScoredStep 中提取的候选经验数 | 越多越好（上限限流） | P1 |
| **cost_per_game** | 每局 LLM token 消耗 × 当前模型单价 | 越低越好 | P2 |
| **llm_latency_p50** | LLM 调用延迟中位数（ms） | 越低越好 | P2 |
| **retrieval_latency_p50** | BM25 检索延迟中位数（ms） | 越低越好 | P2 |
| **downgrade_count** | 降级到 heuristic 的次数 | 越低越好 | P2 |

## 统计方法

| 方法 | 用途 | 参数 | 输出 |
|------|------|------|------|
| **Bootstrap 95% CI** | 评估各指标的不确定性区间 | 10000 次重采样 | `metric ± CI` |
| **Permutation Test** | 检验组间胜率差异是否显著 | 10000 次置换，双侧 | p-value |
| **Cohen's d** | 量化组间差异的效应量 | pooled SD | d 值（小: 0.2, 中: 0.5, 大: 0.8） |
| **Bonferroni Correction** | 多重比较校正 | α = 0.05 / k（k=6 pairwise comparisons） | 校正后显著性阈值 |

## 最小样本量

- 每组（Tier）：**30 局**（基于 Cohen's d=0.5, power=0.8, α=0.05 的 power analysis）
- 总样本量：**120 局**（4 tiers × 30 games）

## 实验执行流程

```
1. preflight.check_all() — 验证环境就绪
2. strategy_snapshot.create() — 冻结 active pool
3. for each tier in [baseline, anti_only, trackc_only, both]:
     for seed in tier.seed_range:
       game = run_game(seed, tier.config)
       post_game(game)  — score + review + abstract
4. aggregate() — 汇总所有指标
5. analyze() — Bootstrap CI + Permutation test + Cohen's d
6. export() — JSON results + HTML dashboard
```

## 预期结果（假设）

1. **both > trackc_only > anti_only > baseline** 在 process_score 和 invalid_action_count 上
2. **trackc_only** 在 strategy_usage_count 上最高（无 anti_pattern 干扰，Agent 更依赖检索）
3. **anti_only** 在 anti_pattern_violation_count 上最低（反模式直接阻止错误）
4. **baseline** 在 cost_per_game 上最低（无额外检索 token 消耗）

## 复现说明

1. 安装依赖：`pip install -r requirements.txt`
2. 配置 PostgreSQL 连接：`.env` 中设置 `DATABASE_URL`
3. 配置 LLM 密钥：`.env` 中设置对应模型的 API Key
4. 运行实验：`python scripts/multi_tier_experiment.py --config configs/demo.yaml`
5. 生成报告：`python scripts/render_dashboard_html.py --experiment_id <exp_id>`
