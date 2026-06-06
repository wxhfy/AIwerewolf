# AI Werewolf 系统大改待办与风险清单

> 生成时间：2026-06-02  
> 口径：以满分验收为目标；S1/S2 小改已在本轮处理，S3 架构级或数据级事项进入本清单。

## 1. P0 必须修复

### P0-1：敏感配置彻底治理与外部密钥轮换
- **问题**：安全扫描发现历史实验脚本中曾硬编码 LLM API key；本轮已移除具体 hardcoded provider key，但仓库仍有多处本地默认数据库连接串和默认密码。
- **影响**：违反 `AGENTS.md` 的密钥红线；影响工程完整度、安全可信度和评委复现安全性。
- **证据**：已修复文件包括 `scripts/finetune_llm_verified.py`、`scripts/ft_quick.py`、`scripts/eval_hybrid_agentic_rrf.py`、`scripts/finetune_llm_batch.py`、`scripts/eval_agentic_search.py`；剩余默认 DB 字符串可由 `rg "wolf_secret_2026"` 查到。
- **推荐方案**：外部立即轮换曾暴露的 LLM key；所有脚本只读 `DATABASE_URL`、`DSV4FLASH_API_KEY` 等环境变量；新增 pre-commit/CI secret scan，阻断 `ark-*`、`sk-*`、`Bearer`、`API_KEY=`、明文 DB URL。
- **为什么不能直接小改**：轮换外部 key 需要账号侧权限；清理所有默认 DB URL 会影响本地 demo、docker、README、实验脚本和 CI，需要统一配置策略。
- **验收标准**：`rg -n "ark-[A-Za-z0-9-]{20,}|sk-[A-Za-z0-9]{20,}"` 无命中；CI secret scan 通过；README 只保留 `.env.example` 配置说明；外部 key 已确认轮换。
- **优先级**：P0

### P0-2：Track B 模型 artifact / 运行环境不兼容导致全量测试失败
- **问题**：全量 `pytest tests/ -q` 仍有大量 Track B / vnext 测试因 `data/health/decision_quality_model.pkl` 反序列化失败而失败。
- **影响**：阻断满分档“评测复盘可复现”“Golden Cases 可校准”“全量测试绿色”。
- **证据**：全量测试曾输出 `TypeError: __randomstate_ctor() takes from 0 to 1 positional arguments but 2 were given`，并伴随 NumPy / SciPy / sklearn 版本不匹配告警。
- **推荐方案**：二选一：重训并重新发布与当前依赖匹配的模型 artifact；或在 `requirements` / lockfile 中固定 artifact 构建时的 NumPy、SciPy、sklearn 版本，并补 artifact manifest。
- **为什么不能直接小改**：需要重建或迁移模型文件，影响多条 Track B/vnext 测试链路和报告脚本。
- **验收标准**：相关 `tests/test_track_b_*`、`tests/test_vnext_*` 不再因 pickle/env 失败；artifact manifest 记录训练依赖版本、数据来源、生成命令和校验 hash。
- **优先级**：P0

## 2. P1 高优先级

### P1-1：缺失 Track B 发布报告和 vnext 报告 artifact
- **问题**：多个测试期待的报告文件不存在。
- **影响**：影响“非技术评委可读”“评测复盘证据链完整”“文档可运行”。
- **证据**：全量测试失败项包括 `docs/track_b_speech_semantic_audit_integration_report.md`、`docs/track_b_speech_act_classifier_v0_report.md`、`docs/track_b_vnext_eval_report.md` 缺失。
- **推荐方案**：恢复或重建生成脚本，生成报告并记录输入数据、模型版本、命令、摘要指标。
- **为什么不能直接小改**：报告不能手写凑数，必须由可复现脚本从真实数据和模型产出。
- **验收标准**：缺失报告文件存在；生成命令可在干净环境跑通；对应测试通过。
- **优先级**：P1

### P1-2：Open Data manifest 和 raw 目录缺失
- **问题**：开放数据管线测试缺少 manifest 和 raw 数据目录。
- **影响**：影响 Golden Cases、公开数据复现、评测数据闭环。
- **证据**：`tests/test_track_b_open_data_full_pipeline.py::test_manifest_exists`、`test_raw_directories_exist` 失败。
- **推荐方案**：明确 open data 目录结构、manifest schema、下载/构建脚本；不能公开的数据以占位 manifest + skip 条件说明。
- **为什么不能直接小改**：涉及外部数据来源、许可、数据清洗和测试口径。
- **验收标准**：manifest 与 raw 目录存在；schema 校验通过；数据许可在文档中说明；相关测试通过。
- **优先级**：P1

### P1-3：前端 Playwright smoke 不稳定
- **问题**：`tests/test_webapp.py::test_webapp` 依赖 `localhost:3001` 和 `/tmp/webapp_test.png`，当前环境截图写入报 `PermissionError`。
- **影响**：前端满分档缺少截图/demo 证据，无法证明 Replay Viewer 在浏览器中稳定可用。
- **证据**：全量测试失败日志显示 `/tmp/webapp_test.png` 权限错误；`npm run build --prefix frontend` 已通过但不能替代运行时 smoke。
- **推荐方案**：测试自身启动 dev server 或复用明确端口；截图写入仓库 `artifacts/` 或 pytest tmp_path；补桌面/移动 viewport 截图。
- **为什么不能直接小改**：需要梳理前端测试夹具、端口管理和 artifact 保存策略。
- **验收标准**：Playwright smoke 在 CI/本地均可运行；截图 artifact 可查看；至少覆盖 lobby、play、dashboard、report 页面。
- **优先级**：P1

### P1-4：知识可信度 / 权限 / 适用条件未完全进入持久化检索链路
- **问题**：`backend/eval/knowledge_confidence.py` 已有 `KnowledgeConfidence`、`KnowledgeAccessControl`、`KnowledgeApplicability`，但 DB `StrategyKnowledgeDoc` 和 `backend.db.persist.retrieve_strategy_knowledge()` 路径未完整证明四层过滤都生效。
- **影响**：影响轻量自进化满分档；错误复盘知识可能污染下一局 Agent。
- **证据**：`backend/db/models.py::StrategyKnowledgeDoc` 主要保存 `confidence`，而 L0-L4 tier、access/applicability 字段并未作为统一持久化契约闭环。
- **推荐方案**：扩展 schema 或 metadata contract；运行时检索统一调用带 tier/access/applicability 过滤的入口；补 L4 block、private scope、role/phase applicability 测试。
- **为什么不能直接小改**：涉及 DB schema、迁移、Agent prompt 注入和历史知识兼容。
- **验收标准**：L4 知识进入决策检索次数为 0；权限过滤测试 100% 通过；检索结果记录 `confidence_tier`、`scope`、`applicability_reason`。
- **优先级**：P1

### P1-5：DecisionTrace 满分字段覆盖率未量化
- **问题**：`backend/engine/models.py::DecisionAudit` 和 `backend/eval/types.py::DecisionTrace` 存在，但没有证明每次决策都有满分要求字段。
- **影响**：影响单 Agent 能力、可观测性和复盘可追溯评分。
- **证据**：目前可见字段包含 observation、raw_output、parsed_action、model/token/latency 等，但 `candidate_actions`、`visible_facts`、`confidence`、`prompt_hash`、`cost` 覆盖率未统计。
- **推荐方案**：统一 runtime decision trace schema；在 `WerewolfGame._record_decision()` 记录候选动作、可见事实摘要、prompt hash、cost；新增覆盖率统计接口。
- **为什么不能直接小改**：会影响 Agent 输出协议、DB schema、报告和前端决策面板。
- **验收标准**：≥95% Agent 决策有完整 DecisionTrace；缺字段有明确原因；覆盖率可由脚本/接口输出。
- **优先级**：P1

### P1-6：正式 LLM-only 验收证据缺失
- **问题**：本轮验证跑通了 heuristic demo、B/C 规格测试和前端 build，但没有生成 `STRICT_NO_FALLBACK` 的真实 LLM 批量验收报告。
- **影响**：用户反复强调正式实验必须在 LLM 下完成；heuristic smoke 不能进入最终验收口径。
- **证据**：`docs/DEVELOPMENT_ISSUES.md` §I 明确记录该偏好；当前报告只能引用 targeted tests 和 demo，不能声称 LLM 对局质量满分。
- **推荐方案**：运行 `scripts/run_full_llm_pipeline.py` 或等价脚本，记录 `runner_mode=llm`、`llm_decision_count`、`fallback_count=0`、token/latency/cost。
- **为什么不能直接小改**：需要可用 API key、模型 endpoint、费用预算和长时间运行。
- **验收标准**：至少 20 局 LLM-only 批量报告；fallback_count=0；失败局有原因；报告进入 `docs/` 或 `artifacts/`。
- **优先级**：P1

## 3. P2 加分项

### P2-1：Golden Cases 数据量、人工标签和置信区间不足
- **问题**：B/C 规格测试通过，但 Golden Cases 的公开数据、人类标签、TPR/FPR 置信区间证据不足。
- **影响**：影响评测复盘方向满分档。
- **证据**：`tests/test_b_full_acceptance.py`、`tests/test_c_acceptance_verification.py` 可验证规格，但 full suite 仍因模型和数据 artifact 不完整失败。
- **推荐方案**：构造并发布固定 bad case / clean case 集；补人工标签说明和 bootstrap CI。
- **为什么不能直接小改**：需要数据标注和统计口径，不应手写通过。
- **验收标准**：Golden Cases TPR ≥80%、FPR ≤20%，带样本数和 CI。
- **优先级**：P2

### P2-2：Replay Viewer 满分功能证据不足
- **问题**：前端已有页面和 build，但 bad case 高亮、反事实面板、视角切换截图证据不足。
- **影响**：影响工程完整度和“非技术评委看懂”。
- **证据**：`frontend/app/games/[id]/report/page.tsx`、`frontend/app/eval/dashboard/page.tsx` 存在；Playwright smoke 未稳定通过。
- **推荐方案**：补 report 页面 bad case/counterfactual 交互截图；前端 smoke 覆盖 public/moderator view。
- **为什么不能直接小改**：需要浏览器运行验证和可能的 UI 状态补齐。
- **验收标准**：截图或 demo 覆盖时间轴、玩家状态、投票流、决策面板、反事实结果。
- **优先级**：P2

### P2-3：50 局标准配置批量稳定性报告缺失
- **问题**：单局 demo 可完成，但满分档要求标准配置 50 局完成率 ≥95%。
- **影响**：影响工程稳定性评分。
- **证据**：本轮执行 `python -m backend.run_demo --seed 7` 可到 `GAME_END`；未生成 50 局统计报告。
- **推荐方案**：新增或恢复 batch runner，固定 `configs/rule_variant_standard.yaml`，输出完成率、异常动作恢复率、平均耗时。
- **为什么不能直接小改**：需要长跑、稳定随机种子和结果 artifact。
- **验收标准**：50 局完成率 ≥95%；异常局有日志；规则变体与配置一致。
- **优先级**：P2

### P2-4：标准规则配置尚未绑定 CI
- **问题**：本轮已把 `configs/rule_variant_standard.yaml` 与 `WOLFCHA_ROLE_CONFIGS` 对齐，但没有 CI 测试强制同步。
- **影响**：后续角色配置可能再次漂移。
- **证据**：本轮用临时脚本验证一致；尚未新增正式测试文件。
- **推荐方案**：新增配置一致性测试，比较 YAML 与 `backend.engine.rules.WOLFCHA_ROLE_CONFIGS`。
- **为什么不能直接小改**：可以小改，但当前优先级低于安全、全量测试和报告 artifact。
- **验收标准**：CI 中配置一致性测试通过；新增/修改角色时测试失败能提示具体人数配置。
- **优先级**：P2

## 4. P3 后续优化

### P3-1：通用 Agent 自主改代码方向暂不主打
- **问题**：当前系统主线是游戏 Agent + 评测复盘 + 轻量策略知识迭代，不是让 Agent 自主修改代码。
- **影响**：避免进阶方向分散，防止为了覆盖 A 方向做高风险代码自修改。
- **证据**：B/C 模块证据明显强于 A；`backend/eval/review.py`、`backend/eval/evolution.py` 已有复盘与策略知识管线。
- **推荐方案**：报告中明确主打 B，C 作为轻量自进化加分；A 只保留过程可审核的开发辅助，不纳入产品目标。
- **为什么不能直接小改**：A 方向需要独立 sandbox、回滚、权限和安全设计。
- **验收标准**：展示材料聚焦 B/C，不声称通用 Agent 自主改代码满分。
- **优先级**：P3

### P3-2：未启用模板角色继续保持不可玩
- **问题**：Cupid、BigBadWolf 等扩展角色模板存在，但未完整接入阶段和技能结算。
- **影响**：若误放入 7-12P 配置，会造成 KeyError 或规则缺失。
- **证据**：`backend/engine/roles/registry.py` 使用 `playable` 区分；`tests/test_role_registry.py` 校验可玩角色配置。
- **推荐方案**：继续保持 `playable=False`；未来按角色逐个补技能、UI、测试后启用。
- **为什么不能直接小改**：新增角色涉及引擎阶段、ActionValidator、Agent prompt、前端 UI、测试。
- **验收标准**：新角色启用前有完整技能结算和至少一个边界测试。
- **优先级**：P3

## 5. 需要架构设计评审的事项

- **知识回流 schema 评审**：统一 `StrategyKnowledgeDoc` 的 tier/access/applicability 字段、迁移策略、历史兼容和 Agent 注入格式。
- **DecisionTrace schema 评审**：确定 runtime trace 与复盘 trace 是否合并，字段如何落库，如何计算 95% 覆盖率。
- **Track B artifact 评审**：决定模型 artifact 是重训、迁移还是 pin 环境；明确 artifact manifest 标准。
- **前端验收夹具评审**：统一 dev server 生命周期、截图 artifact 路径和 CI 浏览器依赖。
- **秘密管理评审**：默认 DB 密码、docker demo、`.env.example`、CI secret scan 的边界。

## 6. 需要数据验证的事项

- **LLM-only 批量对局**：至少 20 局，记录 fallback=0、token、latency、cost、失败原因。
- **50 局标准配置稳定性**：完成率、异常恢复率、规则边界覆盖率。
- **Golden Cases 校准**：TPR/FPR、置信区间、人类标签一致性。
- **A/B tournament**：baseline vs candidate 至少 20 seed，报告胜率/分项指标/显著性。
- **信息隔离全链路**：PlayerView、Memory、Retrieval、Prompt、final_agent_input 泄露数均为 0。

## 7. 暂不建议做的事项

- **不建议现在重写游戏引擎**：当前引擎已能跑通并有边界测试，满分缺口主要在 artifact、量化报告和 trace 覆盖。
- **不建议现在大改前端视觉风格**：前端 build 已通过，优先修 smoke 和 Replay Viewer 证据。
- **不建议把模板扩展角色一次性全部启用**：会放大规则结算和信息隔离风险。
- **不建议声称自进化已显著提升胜率**：没有正式 LLM-only 20 局 A/B 报告前，只能称为轻量自进化设计和规格测试通过。
