# V3 总目标：HTML 可视化复盘 + 多局测评有效性看板

> **状态更新**: 2026-05-28
> **整体进度**: 脚本已就绪，待生成 HTML 产物

## 进度总览

| 模块 | 脚本 | 状态 |
|------|------|------|
| 单局报告数据构建 | `scripts/build_single_game_report_data.py` | ✅ 脚本就绪 |
| 多局看板数据构建 | `scripts/build_dashboard_data.py` | ✅ 脚本就绪 |
| V3 features 构建 | `scripts/build_v3_features.py` | ✅ 脚本就绪 |
| 单局 HTML 渲染 | `scripts/render_single_game_html.py` | ✅ 脚本就绪 |
| 多局 dashboard HTML 渲染 | `scripts/render_dashboard_html.py` | ✅ 脚本就绪 |
| 单局 HTML 报告 | `data/health/review_game_<id>_v7.html` | ⬜ 待生成 |
| 多局测评看板 | `data/health/scoring_validity_dashboard.html` | ⬜ 待生成 |
| V3 后端 API (`/api/games/<id>/reviews/html`) | `backend/app.py` | ✅ 已接入 |

**阻塞项**: 待跑 `scripts/v3_full_pipeline.py` 生成中间数据后渲染 HTML。

> 注意：README 中引用的 `data/health/scoring_validity_appendix_v7.html` 和 `data/health/mbti_performance_dashboard_v7.html` 也待生成。

---

V3 分成两个报告，不要混在一起。

```
1. 单局 HTML 复盘报告
   目标：讲清楚一局狼人杀发生了什么，哪里精彩，谁做了关键操作。

2. 多局 HTML 测评看板
   目标：证明评分系统有效，能区分角色、操作、策略版本和 Agent 能力。
```

也就是说：

```
单局报告 = 给观众看“这局好不好看，为什么这样赢/输”
多局报告 = 给评委看“你的评分器到底靠不靠谱”
```

------

# 一、V3 具体要做什么

## V3.1 单局 HTML 复盘报告

输入：

```
review_with_learned_scores_v3.json
replay.json
opportunities.jsonl
counterfactuals
speech_acts
suspicion_matrix
validation_result
```

输出：

```
review_game_<game_id>.html
```

要求：

```
1. 打开即用；
2. 不依赖 Markdown 渲染器；
3. 图表、样式、数据全部内嵌；
4. 可以离线打开；
5. 支持点击证据、展开回合、查看反事实；
6. 以图、表、时间线为主，少放大段文字。
```

## V3.2 多局 HTML 测评看板

输入：

```
scoring_validity_report_v3.json
role_action_evaluation_matrix.csv
ablation_summary.csv
leaderboard
validation_summary
```

输出：

```
scoring_validity_dashboard.html
```

要求展示：

```
1. 评分系统是否有效；
2. 不同角色是否能区分好坏操作；
3. 新评分相比旧规则是否提升；
4. Guard / Hunter 的低置信边界；
5. Leaderboard；
6. Valid Agent 通过情况。
```

------

# 二、单局 HTML 报告展示什么

单局报告不是论文，不要全是文字。它应该像“比赛复盘页面”。

## 页面结构

```
1. 顶部总览区
2. 阵营走势区
3. 对局时间线
4. 玩家评分榜
5. 怀疑度热力图
6. 投票流向图
7. 关键操作高光
8. 关键失误
9. 反事实推演
10. 玩家个人卡片
11. Valid Agent 校验结果
12. 原始证据抽屉
```

------

# 三、顶部总览区

## 展示内容

```
游戏 ID
规则板子
胜利阵营
总天数 / 总轮次
MVP
最佳操作
最大失误
最关键转折点
Valid Agent 状态
```

## 视觉设计

顶部用卡片：

```
┌─────────────────────────────────────────────┐
│ AI 狼人杀复盘报告                            │
│ Winner: Villagers     MVP: P3 / Seer         │
│ Game Length: 3 Days   Valid: Grade A         │
└─────────────────────────────────────────────┘
```

## 指标卡

```
阵营胜负
MVP 分数
最高 impact 操作
最大反事实 swing
Valid Agent grade
```

------

# 四、阵营走势区：Camp Advantage Curve

这是最重要的图之一。

## 目的

让观众一眼看出：

```
哪一刻好人占优；
哪一刻狼人翻盘；
哪个操作改变了局势。
```

## 指标设计

定义一个局部阵营优势分：

```
CampAdvantage(t) =
  good_alive_value(t)
- wolf_alive_value(t)
+ public_info_value(t)
+ confirmed_wolf_pressure(t)
- mislead_pressure(t)
```

可以简化为：

```
CampAdvantage =
  0.35 * alive_balance
+ 0.25 * key_role_alive
+ 0.20 * confirmed_info
+ 0.10 * vote_pressure_on_wolf
- 0.10 * vote_pressure_on_good
```

## HTML 展示

用折线图：

```
Y轴：好人优势 / 狼人优势
X轴：事件时间
```

标记关键节点：

```
N1 狼刀
D1 发言
D1 投票
N2 女巫毒药
D2 预言家公开查杀
D2 放逐
```

每个关键点可 hover：

```
Day2 Vote:
P5 被放逐，身份为 Werewolf
CampAdvantage +0.32
```

------

# 五、对局时间线：Interactive Timeline

## 目的

让人像看比赛一样复盘整局。

## 时间线结构

```
Night 1
  狼人刀人
  预言家查验
  女巫救/毒
Day 1
  发言
  投票
  放逐
Night 2
  ...
Day 2
  ...
```

## 每个事件卡片显示

```
时间
阶段
行动者
目标
操作类型
影响分 impact
证据 event_id
```

示例：

```
Day 2 / Speech
P3（Seer）公开 P5 查杀
Impact: +0.41
Tags: info_release, vote_guidance
```

## 颜色

```
绿色：好人阵营正贡献
红色：狼人阵营正贡献
橙色：关键失误
蓝色：信息释放
灰色：普通事件
```

------

# 六、玩家评分榜

## 不要只显示 FinalScore

每个玩家展示：

```
FinalScore
ProcessScore
RoleProcessScore
SpeechScore
CounterfactualImpact
MistakePenalty
Confidence
```

## 表格形式

| Rank | Player | Role | Persona | Final | Process | Role | Speech | CF Impact | Confidence |
| ---- | ------ | ---- | ------- | ----- | ------- | ---- | ------ | --------- | ---------- |
|      |        |      |         |       |         |      |        |           |            |

## 点击玩家展开

展开后显示：

```
Top 3 good opportunities
Top 3 bad opportunities
关键证据
角色建议
```

------

# 七、怀疑度热力图：Suspicion Heatmap

这是展示狼人杀“信息变化”的核心图。

## 目的

直观看到：

```
谁什么时候被怀疑；
怀疑是怎么升高/降低的；
某个发言/投票是否改变了局势。
```

## 图表

```
X轴：事件序列 / 回合
Y轴：玩家
颜色：公共狼面 suspicion score
```

示例：

```
        E1  E2  E3  E4  E5  E6
P1      .2  .3  .4  .6  .7  .8
P2      .3  .2  .2  .2  .1  .1
P3      .4  .5  .3  .2  .2  .1
```

## hover 展示

```
P5 suspicion = 0.78
原因：
- 被预言家查杀
- Day2 投票矛盾
- 发言未回应质疑
```

## 量化指标

信息变化可以定义：

```
SuspicionSwing(event) =
Σ |suspicion_after(player) - suspicion_before(player)|
```

这个值越大，说明该事件对场上判断影响越大。

可以用于找“信息爆点”。

------

# 八、投票流向图：Vote Flow / Sankey

## 目的

展示白天票型如何形成。

狼人杀最精彩的地方之一是归票和冲票。投票流向图很直观。

## 展示方式

每一天一张图：

```
投票者 → 被投票者
```

也可以展示：

```
Day1 票型
P1 → P4
P2 → P4
P3 → P5
P4 → P5
...
```

## 额外标记

```
被投出玩家身份
是否为狼人
pivot vote
是否存在反事实改票
```

## 关键指标

```
VoteCorrectness
PivotVoteImpact
VoteConcentration
WolfVotingCoordination
```

### PivotVoteImpact

```
如果改变某一票会改变放逐结果，则该票是 pivot vote。
```

报告展示：

```
P2 的投票是关键票。
如果 P2 从 P4 改投 P5，当日出局对象将从好人 P4 变为狼人 P5。
```

------

# 九、关键操作高光：Top Opportunities

## 目的

展示本局最精彩的操作。

每个 opportunity 都有：

```
OpportunityScore = OpportunityWeight × DecisionQuality
```

选 Top 5。

## 高光卡片内容

```
玩家
角色
阶段
操作
机会价值
决策质量
局部影响
证据
为什么好
```

示例：

```
高光 #1
P3 / Seer / Day2 Speech
公开 P5 查杀并归票

OpportunityWeight: 0.91
DecisionQuality: 0.88
Impact: +0.42

原因：
预言家已查到狼人，且当日好人 P4 被集火。
公开查杀有效提升 P5 狼面，并推动归票转向。
```

## 卡片视觉

```
大分数
角色 icon
impact bar
证据按钮
```

------

# 十、关键失误：Bad Opportunities

同样展示 Top 5 低质量机会。

## 卡片内容

```
玩家
角色
阶段
操作
低质量原因
MistakeSeverity
Counterfactual
证据
建议
```

示例：

```
失误 #1
P6 / Witch / Night2
毒杀 P2

DecisionQuality: 0.21
MistakeSeverity: 0.83

原因：
P2 公共怀疑度较低，且没有查验或票型证据支持。
反事实：
如果女巫不毒，P2 不会额外死亡，好人阵营保留一名关键投票位。
```

------

# 十一、反事实推演区

## 目的

展示“如果当时换一种动作会怎样”。

分三类显示。

## 1. 投票反事实

展示原票型和反事实票型。

```
原始：
P4 3票 → 出局，好人

反事实：
如果 P2 改投 P5
P5 3票 → 出局，狼人
```

用并列表格：

| 原始票型 | 反事实票型 |
| -------- | ---------- |
| P4: 3    | P4: 2      |
| P5: 2    | P5: 3      |

## 2. 技能反事实

展示局部结果变化：

```
女巫毒好人
Actual: Good -1
Counterfactual: 不毒 → Good 不减员
Local Delta: +0.35
```

## 3. 信息释放反事实

展示为估计，不要过度承诺：

```
预言家未公开查杀
如果公开：
P5 suspicion 预计从 0.42 → 0.72
可能改变归票方向
Confidence: 0.65
```

必须标注：

```
Estimated，不代表必然改变最终胜负。
```

------

# 十二、玩家个人卡片

每个玩家一张卡，点击展开。

## 展示

```
玩家名
角色
MBTI/persona
阵营
生存状态
FinalScore
Confidence
```

## 雷达图

建议维度：

```
角色任务
发言质量
投票质量
技能质量
反事实贡献
鲁棒性
```

## 操作列表

按时间显示：

```
Day1 Speech
Day1 Vote
Night2 Skill
Day2 Speech
...
```

每个操作显示：

```
score
confidence
good/bad tag
evidence
```

------

# 十三、精彩程度量化：Game Drama Score

你说要“看出来狼人杀对局的有趣”，这个可以量化。

定义一个本局精彩度：

```
DramaScore =
  0.25 * CampAdvantageSwing
+ 0.20 * SuspicionSwing
+ 0.20 * PivotVoteCount
+ 0.15 * CounterfactualImpactSum
+ 0.10 * RoleSkillImpact
+ 0.10 * ComebackScore
```

## 各项含义

```
CampAdvantageSwing:
阵营优势曲线波动越大，说明局势越跌宕。

SuspicionSwing:
怀疑度变化越大，说明信息博弈越激烈。

PivotVoteCount:
关键票越多，投票越紧张。

CounterfactualImpactSum:
反事实影响越大，说明关键决策多。

RoleSkillImpact:
神职技能影响越大，局面越精彩。

ComebackScore:
落后一方是否反超。
```

## 报告展示

顶部显示：

```
本局精彩指数：87 / 100
看点：
1. Day2 预言家公开查杀造成最大怀疑度变化；
2. Day2 投票存在 pivot vote；
3. 女巫毒药造成高影响反事实；
4. 好人阵营在 Day2 完成局势反转。
```

这个比空泛文字强很多。

------

# 十四、多局 HTML 测评看板展示什么

多局报告不是讲某一局，而是证明评分器有效。

## 页面结构

```
1. 数据规模
2. Ablation 对比
3. 角色区分度
4. Role-Action Matrix
5. 校准曲线
6. Leaderboard
7. Valid Agent 通过率
8. 低置信角色说明
```

------

## 1. 数据规模卡

```
Games: 97
Opportunities: 2461
Labeled Samples: 688
Roles: 6
Opportunity Types: 10
Valid Reports: N
```

------

## 2. Ablation 对比图

展示：

```
A: old rule
B: opportunity-only
C: small model
D: small model + BGE-M3
```

指标：

```
Pairwise Accuracy
Witch d
Guard d
Hunter d
Overall d
```

用柱状图。

------

## 3. 角色区分度图

每个角色一组：

```
good mean
bad mean
gap
Cohen's d
confidence
```

Guard / Hunter 标注特殊说明：

```
Guard: 正向弱区分
Hunter: low confidence due to low shot opportunity
```

------

## 4. Role-Action Matrix

表格热力图。

| Role | Action | Samples | Good Mean | Bad Mean | Gap  | d    | Confidence |
| ---- | ------ | ------- | --------- | -------- | ---- | ---- | ---------- |
|      |        |         |           |          |      |      |            |

用颜色表示 gap：

```
绿色：区分好
黄色：中等
红色：不足
灰色：样本不足
```

------

## 5. 模型校准图

分桶：

```
0-0.2
0.2-0.4
0.4-0.6
0.6-0.8
0.8-1.0
```

展示：

```
预测分数 vs 实际 good rate
```

如果曲线单调上升，说明评分可靠。

------

## 6. Leaderboard

不要只看胜率。

展示：

```
ProcessScore
RoleProcessScore
SpeechScore
CounterfactualImpact
MistakePenalty
Valid Pass Rate
Low Confidence Rate
```

可以按：

```
role
persona
strategy_version
model
```

切换。

------

# 十五、HTML 技术实现建议

## 原则

```
1. 单文件 HTML；
2. CSS 内嵌；
3. JS 内嵌；
4. 数据 JSON 内嵌；
5. 图表优先 SVG / Canvas；
6. 不强依赖外部 CDN；
7. 支持离线打开。
```

## 推荐方案

### 简单稳妥版

```
Python 生成 HTML
+ Jinja2 模板
+ 内嵌 CSS
+ 内嵌 JSON
+ SVG 图表
```

优点：

```
稳定、离线、好调试。
```

### 图表库选择

如果可以内嵌 JS：

```
ECharts standalone min.js 内嵌
```

或者：

```
Plotly min.js 内嵌
```

但文件会大。

更稳的是：

```
matplotlib / plotly 先生成 SVG 或 PNG
再 base64 内嵌 HTML
```

我建议：

```
时间线、卡片、表格：HTML/CSS/JS
热力图、折线图、雷达图：SVG 或 base64 PNG
```

------

# 十六、HTML 报告生成流程

```
review_with_learned_scores_v3.json
+ replay.json
+ suspicion_matrix.json
+ opportunities.jsonl
+ counterfactuals.json
+ validation_result.json
↓
report_data_builder
↓
chart_data_builder
↓
html_renderer
↓
single_game_review.html
```

多局看板：

```
scoring_validity_report.json
+ role_action_matrix.csv
+ ablation_summary.csv
+ leaderboard.csv
+ valid_summary.json
↓
dashboard_data_builder
↓
html_renderer
↓
scoring_validity_dashboard.html
```

------

# 十七、给本地 Agent 的任务指令

直接复制给本地 Agent：

```
当前进入 V3：HTML 可视化复盘报告 + 多局测评有效性看板。

目标：
不再主要产出 Markdown，而是生成打开即用的 HTML 报告。HTML 要以图、表、时间线、卡片为主，减少空泛文字。

任务 1：明确两类 HTML 输出
1. 单局复盘报告：
   output: data/health/review_game_<game_id>.html
2. 多局测评看板：
   output: data/health/scoring_validity_dashboard.html

任务 2：单局 HTML 报告必须包含以下模块：
1. 顶部总览卡：
   - game_id
   - winner
   - MVP
   - total_days
   - drama_score
   - valid_agent_grade
2. Camp Advantage Curve：
   - 展示阵营优势随事件变化
   - 标注关键事件
3. Interactive Timeline：
   - 按 Night/Day 分组展示事件
   - 每个事件显示 actor、target、action、impact、evidence
4. Scoreboard：
   - FinalScore
   - ProcessScore
   - RoleProcessScore
   - SpeechScore
   - CounterfactualImpact
   - MistakePenalty
   - Confidence
5. Suspicion Heatmap：
   - X 轴事件
   - Y 轴玩家
   - 颜色为 suspicion score
6. Vote Flow：
   - 每天投票者 → 被投票者
   - 标记出局者身份
   - 标记 pivot vote
7. Top Good Opportunities：
   - Top 5 高质量机会卡片
8. Top Bad Opportunities：
   - Top 5 低质量机会卡片
9. Counterfactual Panel：
   - vote_flip exact
   - skill_swap local
   - info_release estimated
10. Player Cards：
   - 每个玩家一张卡
   - 雷达图
   - Top good/bad actions
11. Valid Agent Panel：
   - passed
   - grade
   - publish_allowed
   - issues
12. Evidence Drawer：
   - 点击 evidence_event_id 展开原始事件

任务 3：设计 DramaScore
计算：
DramaScore =
0.25 * CampAdvantageSwing
+ 0.20 * SuspicionSwing
+ 0.20 * PivotVoteCount
+ 0.15 * CounterfactualImpactSum
+ 0.10 * RoleSkillImpact
+ 0.10 * ComebackScore

输出：
- drama_score
- top_drama_moments

任务 4：多局 scoring_validity_dashboard.html 必须包含：
1. 数据规模卡：
   games / opportunities / labeled_samples / roles / valid_reports
2. Ablation 对比：
   A old rule
   B opportunity-only
   C small model
   D small model + BGE-M3
3. Role-wise Cohen's d 图
4. Role-Action Evaluation Matrix 热力表
5. Calibration chart：
   score bin vs empirical good rate
6. Leaderboard：
   role / persona / strategy_version / model
7. Valid Agent Summary：
   pass rate
   evidence coverage
   critical issue count
8. Known Limits：
   Guard medium confidence
   Hunter low confidence
   embedding gain limited

任务 5：HTML 技术要求：
1. 单文件 HTML；
2. CSS 内嵌；
3. 数据 JSON 内嵌；
4. 尽量离线可打开；
5. 图表可以用 SVG/base64 PNG；
6. 如果使用 ECharts/Plotly，必须内嵌 min.js，不依赖 CDN；
7. 最终打开 HTML 不需要额外配置。

任务 6：生成报告数据中间层：
1. single_game_report_data.json
2. dashboard_report_data.json

任务 7：输出验收文件：
1. data/health/review_game_<game_id>.html
2. data/health/scoring_validity_dashboard.html
3. data/health/single_game_report_data.json
4. data/health/dashboard_report_data.json
5. docs/html_report_design_v3.md

禁止：
1. 不要只生成 Markdown；
2. 不要只堆文字；
3. 不要依赖外部 CDN；
4. 不要隐藏 Hunter low-confidence；
5. 不要把 embedding 说成主要提升；
6. 不要只展示 FinalScore，必须展示过程分和机会级证据。
```