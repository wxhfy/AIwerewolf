# 实验数据问题修复报告

生成日期：2026-06-09

范围：处理问题 2-5；问题 1（`positive_display` / MBTI 热力图伪造数据）未触碰。

## 问题 2：测试套件使用系统 Python

根因：测试报 `ModuleNotFoundError: No module named 'langchain_core'` 是因为直接执行 `python3 -m pytest tests/` 会走系统 Python，而依赖安装在项目 `.venv`。

修复：当前 `Makefile` 已将 `PYTHON ?= .venv/bin/python3` 作为默认值，`make test` 展开为 `.venv/bin/python3 -m pytest tests/ -x --tb=short -q`，与 `make dev` 使用同一解释器变量。

验证：`make --dry-run test` 确认测试入口使用 `.venv/bin/python3`。

## 问题 3：狼人胜率 90-100% 异常

根因分析：

- 引擎投票结算本身是确定性的：白天投票按合法目标校验、警长权重计票、平票进入 PK，未发现“好人天然被错误结算”的逻辑问题。
- 7 人局配置是 2 狼 vs 5 好人，且含预言家、女巫、猎人、守卫；不是明显少人导致的单点根因。
- 主要问题在 fake LLM 行为：baseline 路径会按目标列表或公开压力机械选目标，之前只在策略偏置路径过滤“确认好人”；这会让好人容易跟随错误归票或误投金水。狼人策略偏置则会避开队友并优先攻击高价值目标，形成非对称优势。

已执行修复：

- `tests/fake_llm.py`：baseline 和 Track C 路径都过滤已确认好人/金水/可见 `is_wolf=false` 查验目标。
- `tests/fake_llm.py`：公开查杀、归票、嫌疑文本仍可形成压力目标，但不会覆盖确认好人过滤。
- `tests/fake_llm.py`：女巫看到可见刀口且解药可用时会救人，避免 fake baseline 完全不执行基本角色任务。
- `tests/fake_llm.py`：移除守卫“策略偏置下固定优先守神职”的硬编码，避免继续制造角色任务指标下降。

未执行的大范围改动：未把默认实验从 7 人局改为 9 人局。建议先用修复后的 fake LLM 重跑 7 人局，再对比 9 人局；若 7 人局仍明显偏狼，再将实验配置扩大为 9 人局。

## 问题 4：Real LLM 实验样本量不足

根因分析：旧实验输出中 `games_per_framework: 1` 不足以支持框架结论；失败样本被记录为 external failure，但样本量太小会让 1/3 或 2/3 的完成率无法产生稳定统计。

已执行/当前状态：

- `scripts/track_bc_leaderboard_experiment.py`：默认 `DEFAULT_GAMES_PER_FRAMEWORK = 10`，CLI `--games` 默认使用该常量，已超过“至少 5”的下限。
- `scripts/run_retrieval_policy_ablation.py`：默认 `--games` 为 5，并对 incomplete online ablation 加 `evidence_status` 和 claim boundary；未完成时不再输出“recommended default policy”，避免把未完成输出当作策略提升证据。

未执行的大范围改动：未启动真实 LLM 重跑，因为会消耗 API。建议用真实 provider 运行：

```bash
python scripts/track_bc_leaderboard_experiment.py --axis framework --games 10 --game-timeout-s 180
```

## 问题 5：role_task_score 多角色负提升

根因分析：

- `role_task_score` 定义在 `backend/eval/review.py` 的 `MetricsCalculator._role_task_score()`：各角色按职责计算，例如预言家查验/释放信息/投票影响，守卫挡刀/保护关键角色/避免连守，猎人开枪质量，村民投票和公开逻辑。
- Track C 晋级策略在 `backend/eval/evolution.py` 的 `AcceptancePolicy` 中把 `role_task_score_delta >= 0.03` 当作 4 个提升条件之一，而不是硬门槛；因此总分、错误数或非退化 seed 通过时，候选仍可能在角色任务分负提升时被接受。
- 策略注入文案此前强调策略优先级，可能让 agent 过度优化“赢”或遵循策略文本，而不是先完成角色基本职责。

已执行修复：

- `backend/eval/evolution.py`：新增 `ROLE_TASK_DEGRADATION_FLOOR = 0.0`，`ABComparison` 和 `EvolutionComparison` 两条路径都把 `role_task_score_delta >= 0` 作为 hard gate。
- `backend/eval/evolution.py`：paired-seed 的 `candidate_better` / `candidate_non_degraded_seed_count` 同时要求角色任务分不退化。
- `backend/agents/cognitive/agent_loop.py`：Track C 策略知识块加入“本角色基本职责不退化”约束。
- `backend/agents/cognitive/prompts.py`：forced strategy bias 文案改为不得覆盖可见事实、角色规则、合法目标、信息边界或角色基本任务。

## 验证结果

- `ruff check backend/ scripts/ tests/ configs/`：通过。
- `ruff format --check backend/ scripts/ tests/ configs/`：通过。
- 定向回归：`tests/test_llm_config.py tests/test_prompt_layering.py tests/test_track_c_evolution.py::test_paired_tournament_rejects_role_task_degradation_despite_score_lift tests/test_c_acceptance_verification.py::test_c10_acceptance_policy_promotes_or_rejects tests/test_track_bc_leaderboard_experiment.py::test_framework_specs_encode_academic_baseline_and_full_stack tests/test_run_retrieval_policy_ablation.py`：55 passed。
- 后端/评估核心子集：`tests/test_engine.py tests/test_review_metrics.py tests/test_track_c_evolution.py tests/test_c_acceptance_verification.py tests/test_track_bc_leaderboard_experiment.py tests/test_prompt_layering.py tests/test_llm_config.py tests/test_run_retrieval_policy_ablation.py`：170 passed, 2 skipped。

全量 `tests/` 未在本次报告后再次运行；当前已通过覆盖 engine、review、Track C、实验脚本、prompt layer 和 fake LLM 的重点子集。
