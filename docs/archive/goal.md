你现在位于 AI Werewolf / AI狼人杀 项目仓库根目录。

你的任务：基于当前真实代码、文档、数据库、outputs、logs 和实验结果，生成一份“项目结项产品介绍型报告素材包”。

注意：这不是传统研究论文，不要写大段研究背景，不要写国内外研究现状，不要反复展开“为什么”。请像介绍一个已经完成的产品/系统一样，直接介绍：

1. 我们做了什么系统；
2. 这个系统有哪些核心能力；
3. 系统整体架构是什么；
4. 每个模块具体负责什么；
5. 系统如何完成一局 AI 狼人杀；
6. 系统如何记录决策、评分复盘、抽取知识；
7. 最终验收结果和实验结果是什么；
8. 有哪些数据和图表可以支撑；
9. 当前限制和后续方向是什么。

请严格基于真实仓库内容，不要编造。所有关键结论都要尽量标注证据来源，例如：
- 代码文件路径
- 类名 / 函数名
- 脚本名
- 数据库表名
- 输出文件
- JSON / JSONL / CSV / LOG 文件
- 验收报告条目
- 本地重新统计命令

---

# 重要数据要求：必须使用真实全量数据

如果报告中涉及任何数据，例如：
- 20 局实验
- 多局稳定性实验
- 多 Tier 实验
- 胜率
- 胜方分布
- 平均天数
- 平均事件数
- 平均决策数
- 平均 lessons 数
- candidate / active 数量变化
- AgentDecision 数量
- ScoredStep 覆盖率
- Track B 评分数量
- Track C 知识抽取数量
- retrieval 命中率 / 延迟
- LLM latency / token / cost
- fallback 次数
- strict mode 结果

必须遵守以下规则：

1. 优先从原始输出文件读取，例如 outputs/、data/experiment/、reports/、logs/、artifacts/ 中的 JSON、JSONL、CSV、MD、LOG。
2. 如果输出文件不存在，可以使用本地数据库进行全量查询。
3. 如果数据库可用，请通过 SQLAlchemy、psql 或项目已有 persist/query 工具查询真实数据。
4. 查询必须是全量数据，不要只取 limit 20 作为统计结果，除非报告明确写的是“最近 20 局”。
5. 如果代码里有现成统计脚本，可以运行它，但要记录命令、输入文件、输出文件。
6. 如果需要重新运行实验脚本，先判断是否会调用 LLM、是否耗时很长、是否会改变数据库。不要默认重跑昂贵 LLM 实验；如果必须运行，请在报告中标注。
7. 严禁使用 fallback、mock、sample、placeholder、demo 数据填充正式指标。
8. 严禁把文档中的数字直接当成最终统计，除非找不到原始数据，并明确标注“来源：文档记录，未找到原始输出”。
9. 如果发现数据不一致，必须列出冲突来源，并标注“待人工确认”。
10. 如果某项数据无法获得，就写“未找到真实数据”，不要估算。

请在所有数据表旁边标注数据来源，例如：

- 来源：outputs/backend_e2e_report.json
- 来源：PostgreSQL games / agent_decisions 表全量查询
- 来源：data/experiment/summary.json
- 来源：docs/backend_acceptance_criteria.md，未找到原始输出文件
- 来源：重新运行 python scripts/analyze_score_distributions.py 生成

---

# 数据真实性检查要求

请生成一份数据来源审计说明，至少包括：

1. 扫描了哪些目录；
2. 找到了哪些原始实验文件；
3. 哪些数据来自数据库查询；
4. 哪些数据来自文档记录；
5. 哪些数据是重新运行脚本得到的；
6. 是否发现 fallback / mock / demo 字样；
7. 是否发现数据缺失；
8. 是否发现同一指标多个来源不一致；
9. 最终采用哪个来源作为事实；
10. 哪些数据不能写入正式报告。

请搜索并识别以下风险关键词：

fallback
mock
dummy
sample
demo
placeholder
fake
heuristic
dry_run
test_only
synthetic
simulated
estimated
approx
TODO
待确认

如果某个数据文件或脚本结果包含这些关键词，请检查它是否能作为正式数据来源。不能确认时标注“风险数据，不建议用于正式结论”。

---

# 请重点阅读和检查

文档：
- README.md
- AGENTS.md
- DOC_INDEX.md
- PROJECT_STATUS.md
- docs/ARCHITECTURE.md
- docs/DATA_FLOW.md
- docs/backend_acceptance_criteria.md
- docs/evidence_chain_demo.md
- docs/experiment_protocol.md
- docs/retrieval_policy_design.md
- docs/experiments/
- docs/PROJECT_CLOSURE_*.md 如果已存在

后端：
- backend/app.py
- backend/engine/
- backend/agents/
- backend/agents/cognitive/
- backend/eval/
- backend/db/
- backend/ops/

前端：
- frontend/

配置：
- configs/

脚本：
- scripts/run_backend_full_strict.py
- scripts/run_full_llm_pipeline.py
- scripts/multi_tier_experiment.py
- scripts/promote.py
- scripts/run_winrate_experiment.py
- scripts/analyze_score_distributions.py
- scripts 中和 strict、visibility、retrieval、eval、track_b、track_c、experiment、winrate、multi-tier、leaderboard 相关的脚本

数据目录：
- outputs/
- data/
- data/experiment/
- reports/
- logs/
- artifacts/
- .pytest_cache 不作为正式结果来源
- tests/ 只作为测试证据，不作为正式实验数据

数据库：
如果本地 PostgreSQL 可连接，请查询：
- games
- players
- game_events
- game_snapshots
- agent_decisions
- evaluations
- published_reviews
- strategy_knowledge_docs
- knowledge_usage_feedback
- leaderboard_entries
- experiments
- evolution_rounds
- evolution_tournaments

如果数据库不可连接，请记录原因，不要编造数据库统计。

---

# 输出文件

请生成以下文件：

1. docs/PROJECT_CLOSURE_PRODUCT_REPORT_DRAFT.md
2. docs/PROJECT_CLOSURE_DATA_AUDIT.md
3. docs/PROJECT_CLOSURE_EXPERIMENT_RESULTS.md
4. docs/PROJECT_CLOSURE_DESIGN_SELECTIONS.md
5. docs/PROJECT_CLOSURE_FIGURES.md
6. docs/PROJECT_CLOSURE_FACTS.json

---

# 1. docs/PROJECT_CLOSURE_PRODUCT_REPORT_DRAFT.md

生成一篇“产品介绍型项目结项报告”初稿。

标题：

《AI 狼人杀多智能体对战与自进化系统项目结项报告》

文章风格：
- 像正式介绍一个系统 / 产品；
- 不写传统研究背景；
- 不写国内外研究现状；
- 不用大量“为什么”小节；
- 直接介绍系统能力、架构、模块、流程和结果；
- 所有重要数据都要有来源；
- 没有真实数据的地方不要写具体数字。

建议结构如下：

# 摘要

直接说明：
- 本项目完成了什么系统；
- 系统具备哪些能力；
- 系统采用 Play → Evaluate → Evolve 闭环；
- 最终验收和实验结果概况；
- 数据来源说明。

# 1 项目概览

## 1.1 系统定位

说明 AI Werewolf 是一个 AI 狼人杀多智能体对战与自进化系统。

必须体现：
- AI 狼人杀
- 多智能体
- 完整对局
- 信息隔离
- 决策审计
- 赛后评分
- 策略知识回流

## 1.2 项目完成内容

用产品能力方式介绍，不要写成研究背景。

至少包括：
- 完整 AI 对局
- 多角色配置
- 前端观战
- 后端游戏引擎
- 信息隔离
- CognitiveAgent
- AgentLoop 工具调用
- 策略检索
- 决策审计
- 赛后评分
- 复盘报告
- 知识抽取
- 策略回流
- strict mode 验收

## 1.3 项目主线

介绍三条主线：

Play：AI 完成狼人杀对局  
Evaluate：系统对 Agent 决策进行赛后评分  
Evolve：系统将复盘经验转化为策略知识并回流

# 2 产品能力总览

这一章按“能力”介绍，而不是按“为什么”。

## 2.1 AI 自动对局能力
说明系统如何创建玩家、分配角色、推进夜晚和白天、完成胜负判定。

## 2.2 多角色 Agent 能力
说明狼人、预言家、女巫、猎人、守卫、村民、白狼王、白痴等角色支持情况。以代码和配置为准，不要编造角色。

## 2.3 信息隔离能力
说明每个 Agent 只获得 PlayerView。介绍 self view、wolf view、public view。

## 2.4 角色化推理与发言能力
说明 CognitiveAgent 如何 Observe → Think → Act，如何结合 Memory、BeliefTracker、SocialModel、Planner、WolfTeamView、Humanization。

## 2.5 策略检索能力
说明 search_strategies、StrategyRetriever、BM25、倒排索引、RetrievalPolicy、hybrid_role_mbti_global 等实际实现。

## 2.6 决策审计能力
说明 agent_decisions 如何记录 observation、tool_trace、raw_output、parsed_action、model、latency、tokens 等字段。以数据库模型和实际数据为准。

## 2.7 赛后评分能力
说明 PerStepScorer、DecisionScore、ScoredStep、三级评分、highlight/mistake。

## 2.8 复盘报告能力
说明 PublishedReview、Markdown/HTML/JSON 报告输出。

## 2.9 知识抽取与自进化能力
说明 KnowledgeAbstractor、AbstractedLesson、strategy_knowledge_docs、candidate → active → deprecated。

## 2.10 前端观战能力
说明 Next.js/React 前端、房间页、游戏页、玩家卡片、事件时间线、WebSocket snapshot、公开/主持视角、人类 ActionPanel。

# 3 系统架构

## 3.1 总体架构

用一段话介绍系统层次：

Frontend  
→ FastAPI / WebSocket  
→ WerewolfGame  
→ Visibility / PlayerView  
→ CognitiveAgent  
→ AgentLoop / Tools  
→ PostgreSQL  
→ Track B  
→ Track C  
→ StrategyRetriever 回流

## 3.2 核心模块关系

介绍模块之间如何协作。

## 3.3 Play → Evaluate → Evolve 闭环

介绍完整闭环，不要过度论证。

## 3.4 端到端数据流

详细说明：

Frontend
→ FastAPI / WebSocket
→ WerewolfGame
→ Visibility.for_player()
→ CognitiveAgent.update()
→ AgentLoop.run()
→ Decision
→ WerewolfGame._record_decision()
→ agent_decisions
→ PerStepScorer.score_all()
→ DecisionScore
→ ScoredStep
→ PlayerReviewReport / PublishedReview
→ KnowledgeAbstractor
→ AbstractedLesson
→ strategy_knowledge_docs(candidate)
→ promote.py
→ strategy_knowledge_docs(active)
→ StrategyRetriever
→ 下一局 Agent Prompt Layer 3

每一步标注关键文件和函数。

# 4 核心模块介绍

每节按以下结构写：
- 模块职责
- 输入输出
- 关键实现
- 关键文件
- 当前完成状态
- 数据或验收证据

## 4.1 WerewolfGame 对局引擎
## 4.2 Visibility / PlayerView 信息隔离
## 4.3 CognitiveAgent
## 4.4 AgentLoop 与工具调用
## 4.5 StrategyRetriever 策略检索
## 4.6 PostgreSQL 数据与证据链
## 4.7 Track B 赛后评分
## 4.8 Track C 知识自进化
## 4.9 前端观战与交互

# 5 验收结果与实验数据

这一章必须使用真实数据。

## 5.1 数据来源说明

先说明本章数据来自哪里：
- outputs 文件
- data/experiment 文件
- 数据库全量查询
- strict mode 报告
- 文档记录但无原始输出的部分

## 5.2 Strict Mode 全链路验收

整理：
- 命令
- 是否通过
- game_id
- player_count
- day_count
- winner
- duration
- active 前后数量
- candidate 增量
- lessons 数量
- AgentDecision 数量
- ScoredStep 数量
- 报告输出文件

如果某项没有真实原始来源，标注。

## 5.3 模块验收结果

表格字段：

| 模块 | 状态 | 真实数据来源 | 关键指标 | 说明 | 风险 |
| ---- | ---- | ------------ | -------- | ---- | ---- |

模块至少包括：
- DB
- LLM
- Game Engine
- Agent Decision
- Information Isolation
- Strategy Retrieval
- Track B Scoring
- Track B Review
- Track C Knowledge
- Track C Evolution
- Experiment
- Report Export
- Preflight
- Error Handling
- Configuration Validity
- Concurrency / Multi-Game
- Frontend

## 5.4 多局实验结果

请搜索并统计真实多局实验数据。

如果找到 20 局或多局实验，整理：
- 实验文件
- 实验命令
- 实验局数
- 成功 / 失败
- 胜方分布
- 平均天数
- 平均事件数
- 平均决策数
- 平均 lessons
- Track B 覆盖率
- Track C 产出
- fallback 次数
- 错误原因
- 图表数据

如果没有找到原始数据，写：
“未找到原始多局实验数据，不在正式结果中写具体 20 局结论。”

## 5.5 多方案 / 多 Tier 对比结果

请搜索 multi_tier、winrate、retrieval policy、hybrid_role_mbti_global、baseline、ablation 等实验数据。

如果找到，整理：
- 方案名称
- 样本数
- 指标
- 结果
- 是否能支撑选型
- 是否只是趋势

如果没有找到原始数据，写：
“未找到原始多方案对比数据，相关选型只作为工程设计取舍说明。”

## 5.6 结果总结

只总结有数据支撑的结论。

可以写：
- 系统可以完成完整对局；
- 决策可写入审计链；
- 信息隔离验证通过；
- 赛后评分链路可用；
- 知识抽取链路可用；
- 如果多局实验有数据，再写连续运行趋势；
- 如果多方案实验有数据，再写方案对比趋势。

不得写：
- “显著提升”
- “明显优于”
- “自进化效果显著”
- “策略性能大幅提高”

除非有足够统计证据。

# 6 设计取舍与方案说明

这一章不要写太多“为什么”，只做产品方案说明。

表格字段：

| 设计点 | 采用方案 | 替代方案 | 取舍说明 | 数据/证据 | 证据等级 |
| ------ | -------- | -------- | -------- | --------- | -------- |

至少覆盖：
1. Game Engine 独立控制流程；
2. PlayerView 信息隔离；
3. CognitiveAgent；
4. Persona / Role / Strategy 三层结构；
5. AgentLoop 工具调用；
6. BM25 + 倒排索引；
7. hybrid_role_mbti_global；
8. 4-filter 安全管线；
9. 三级评分级联；
10. candidate → active → deprecated；
11. 前端观战控制台；
12. strict mode 作为收敛标准。

证据等级：
- A：有真实实验数据 + 验收结果 + 代码实现；
- B：有验收结果 + 代码实现；
- C：有代码实现 + 设计文档；
- D：主要是设计判断，暂无实验数据。

# 7 项目成果总结

## 7.1 已完成成果
按产品能力总结。

## 7.2 项目价值
总结：
- 完整 AI 多智能体对局；
- 信息隔离可信；
- Agent 决策可追溯；
- 赛后可评分；
- 知识可沉淀；
- 策略可回流；
- 系统可扩展。

## 7.3 当前限制
基于真实文档和代码写。

至少检查：
- LLM 延迟；
- Replay Viewer 是否完整；
- Track C 是否需要更多局数验证；
- Embedding 是否可用；
- 多模型实验是否充分；
- 前端和后端是否有版本口径不一致；
- 文档和代码是否有不一致；
- 工具名称是否和代码一致；
- heuristic fallback 与 LLM-only 说法是否冲突。

## 7.4 后续方向
根据限制提出后续优化方向。

# 附录

## 附录 A 关键文件索引
## 附录 B 验收命令
## 附录 C 数据库核心表
## 附录 D 原始数据文件清单
## 附录 E 数据统计 SQL / 命令
## 附录 F 图表数据表
## 附录 G 不建议写入正式报告的数据

---

# 2. docs/PROJECT_CLOSURE_DATA_AUDIT.md

生成数据审计报告。

结构：

# 数据来源审计报告

## 1. 扫描范围
列出扫描了哪些目录和文件类型。

## 2. 找到的原始数据文件
表格：

| 文件 | 类型 | 内容 | 可解析 | 是否正式数据 | 风险关键词 | 说明 |
| ---- | ---- | ---- | ------ | ------------ | ---------- | ---- |

## 3. 数据库连接与查询结果
如果数据库可连接，列出：
- 连接方式
- 查询时间
- 查询表
- 表记录数
- 关键统计 SQL
- 查询结果

如果不可连接，说明原因。

## 4. 文档记录但无原始数据的指标
表格：

| 指标 | 文档来源 | 数值 | 是否找到原始数据 | 是否建议写入正式报告 |
| ---- | -------- | ---- | ---------------- | -------------------- |

## 5. fallback / mock / demo 风险检查
列出发现的风险数据来源。

## 6. 最终采用的数据源
说明每个核心指标采用哪个来源。

## 7. 不建议使用的数据
列出不可靠数据。

---

# 3. docs/PROJECT_CLOSURE_EXPERIMENT_RESULTS.md

专门整理实验结果。

结构：

# 实验结果汇总

## 1. Strict Mode 单局全链路验收
真实数据表。

## 2. 多局稳定性实验
如果有真实数据，生成统计表和结论。  
如果没有，明确写未找到。

## 3. 多 Tier / 多方案对比实验
如果有真实数据，生成统计表和结论。  
如果没有，明确写未找到。

## 4. Strategy Retrieval 实验
整理检索策略实验，如果有。

## 5. Track B 评分实验
整理评分覆盖率、tier 触发、highlight/mistake，如果有。

## 6. Track C 知识实验
整理 lessons、candidate、active、feedback，如果有。

## 7. 图表数据
生成可直接用于画图的 Markdown 表格。

## 8. 可写结论与不可写结论

分两列：

| 可以写入报告的结论 | 数据来源 |
| ------------------ | -------- |

| 不建议写入报告的结论 | 原因 |
| -------------------- | ---- |

---

# 4. docs/PROJECT_CLOSURE_DESIGN_SELECTIONS.md

生成简洁的产品设计取舍说明。

不要写成长篇“为什么”，按产品方案介绍。

结构：

# 设计取舍说明

## 1. 设计取舍总览

表格：

| 设计点 | 采用方案 | 替代方案 | 取舍说明 | 证据等级 |
| ------ | -------- | -------- | -------- | -------- |

## 2. 核心取舍说明

每个 150–250 字，覆盖：

- Game Engine 独立控制流程
- PlayerView 信息隔离
- CognitiveAgent
- 三层 Prompt
- AgentLoop 工具调用
- BM25 + 倒排索引
- hybrid_role_mbti_global
- 4-filter
- 三级评分
- candidate / active 隔离
- 前端观战控制台
- strict mode

每节包含：
- 当前采用方案
- 替代方案
- 采用原因
- 证据来源
- 数据是否充分

## 3. 可放入报告正文的设计取舍摘要

生成 500 字以内总结。

---

# 5. docs/PROJECT_CLOSURE_FIGURES.md

生成报告图表素材，使用 Mermaid、ASCII 或 Markdown 表格。

至少包括：

## 图 1 产品总体架构图
Frontend、FastAPI、WerewolfGame、Visibility、CognitiveAgent、AgentLoop、StrategyRetriever、PostgreSQL、PerStepScorer、KnowledgeAbstractor。

## 图 2 Play-Evaluate-Evolve 闭环图

## 图 3 单局对局流程图

## 图 4 Agent 决策流程图

## 图 5 赛后评分与知识回流流程图

## 图 6 信息隔离示意图

## 图 7 数据库证据链图

## 图 8 模块验收结果表

## 图 9 多局实验图表
如果有真实多局数据，生成：
- 胜方分布
- 成功/失败
- 每局天数
- 每局决策数
- 每局 lessons 数

如果没有真实数据，写“不生成，未找到原始数据”。

## 图 10 设计取舍证据等级表

每个图下面写 100–200 字说明。

---

# 6. docs/PROJECT_CLOSURE_FACTS.json

生成机器可读事实摘要。

格式：

{
  "project_name": "AI Werewolf",
  "report_type": "product_style_project_closure",
  "one_sentence_summary": "",
  "core_pipeline": ["Play", "Evaluate", "Evolve"],
  "data_policy": {
    "allow_document_only_numbers": false,
    "allow_fallback_data": false,
    "require_raw_outputs_or_db": true,
    "notes": []
  },
  "modules": [
    {
      "name": "",
      "product_capability": "",
      "main_files": [],
      "main_classes_or_functions": [],
      "inputs": [],
      "outputs": [],
      "evidence": [],
      "status": "",
      "risks": []
    }
  ],
  "acceptance": {
    "strict_mode_status": "",
    "command": "",
    "source": "",
    "game_id": "",
    "player_count": null,
    "winner": "",
    "duration_seconds": null,
    "verified_modules": [],
    "partial_modules": [],
    "planned_modules": [],
    "evidence_files": []
  },
  "experiments": {
    "multi_game_found": false,
    "multi_game_count": null,
    "multi_game_files": [],
    "multi_game_summary": null,
    "multi_tier_found": false,
    "multi_tier_files": [],
    "multi_tier_summary": null,
    "retrieval_eval_found": false,
    "retrieval_eval_files": [],
    "claims_supported_by_raw_data": [],
    "claims_document_only": [],
    "claims_not_supported": []
  },
  "database": {
    "available": null,
    "table_count": null,
    "core_tables": [],
    "query_time": ""
  },
  "design_selections": [
    {
      "design_point": "",
      "chosen": "",
      "alternatives": [],
      "selection_note": "",
      "evidence_level": "",
      "evidence": [],
      "has_experiment_data": false
    }
  ],
  "figures_ready": [],
  "report_outline": [],
  "open_questions": []
}

无法确定的字段用 null 或 "待确认"，不要编造。

---

# 最终回复要求

完成后，请总结：

1. 生成了哪些文件；
2. 每个文件的用途；
3. 找到了哪些真实原始数据；
4. 哪些数据来自数据库全量查询；
5. 哪些数据只是文档记录，未找到原始输出；
6. 是否发现 fallback / mock / demo 风险数据；
7. 哪些实验结论可以写入报告；
8. 哪些实验结论不能写入报告；
9. 哪些图表可以直接使用；
10. 哪些问题需要人工确认。

不要只说“已完成”，要列清楚证据来源。