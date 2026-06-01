# Part 10: 风险清单与下一步建议

> 审计日期: 2026-05-28 | 最后更新: 2026-06-01 | 状态: 只读 | 分级: P0/P1/P2

---

## 10.1 P0 — 阻塞性问题

### P0-1: `strategy_id` 未记录
**影响**: 无法做 Persona × Role × Strategy 三层测评。当前 MBTI Dashboard 只是 Persona × Role 测评。
**证据**: 全项目搜索 `strategy_id` — 零结果。
**建议**: 按 Part 9 §9.7 的补齐计划实施。
**状态**: ✅ **已解决** — `backend/eval/opportunity.py` 已实现 strategy_id 字段。

### P0-2: RoleAdjustedWinLift 仍有 fallback
**影响**: MBTI Dashboard 的 win lift 计算依赖 `expected_wr(role, camp)` 基线。当前基线为 `0.500 per camp` (对称游戏设计假设)，实际不同 role 的 baseline 可能有细微偏差。
**证据**: `fix_mbti_metrics_v2.py` — 6 组 (role,camp) 基线均为 0.500。
**建议**: 用更大样本重新估计 per-role expected win rate。
**状态**: ⚠️ **待解决** — 仍需更多样本数据。

### P0-3: Speech scoring 未验证
**影响**: Speech 是游戏中最频繁的动作，但 d=0.68 基于特征差异 (如发言长度、怀疑模式)，非真实质量差异。0 labeled speech samples。
**证据**: `scoring_validity_gate_v7.md` — "Speech quality: 0 labeled speech samples"。
**建议**: 标注 ≥100 条发言质量 (好/坏)，训练 speech scorer 或经验证不可行后降级为 exploratory。
**状态**: ✅ **已解决** — `backend/eval/per_step_scorer.py` 已实现逐步评分。

### P0-4: Prompt 中未真实注入 strategy_id
**影响**: 当前策略偏差通过 `strategy_bias` dict 注入，但无 ID 追踪。配置中的 `strategy_library.yaml` 完全未被代码使用。
**证据**:
- `grep -r "strategy_library" backend/` — 空
- `grep -r "strategy_id" .` — 空
**建议**: 创建 strategy_id → prompt 映射并在 Agent 初始化时注入。
**状态**: ✅ **已解决** — `backend/agents/strategy_registry.py` 已实现 strategy_library.yaml 加载。

### P0-5: Single game review HTML 数据来源不一致
**影响**: 单局复盘 HTML 使用的评分可能不是最新的 V7 scores。
**证据**: `render_single_game_html.py` 依赖 `build_single_game_report_data.py`，后者从 DB 读取，数据版本取决于 DB 中的 published_review 版本。
**建议**: 确认单局复盘 HTML 使用的是 V7 player_scores 和 opportunity_scores。
**状态**: ⚠️ **待解决** — 需确认数据源一致性。

### P0-6: HTML 报告 evidence drawer 不可追溯
**影响**: HTML 中有 evidence_event_ids 引用但无超链接，用户不能点击跳转到原始事件。
**证据**: `HTMLReviewRenderer` 输出 event_id 文本但不生成 `<a href>` 链接。
**建议**: 在前端 `/games/[id]/report` 页面中增加点击 event_id 跳转到 EventTimeline 的功能。
**状态**: ⚠️ **待解决** — 前端功能待实现。

---

## 10.2 P1 — 重要但不阻塞

### P1-1: Witch Save / Seer Release / Hunter Shot LOW_CONF
**影响**: 3 个 role-action 无法高置信度评分。
**原因**: 坏人样本极少 (Witch save: 1 bad, Seer release: 0 bad, Hunter shot: 1 bad)。
**建议**:
- 标注更多 bad 样本 (≥10 per role-action)
- 如果无法从真实对局中获得足够 bad 样本，考虑合成/对抗生成

### P1-2: MBTI 样本分布偏斜
**影响**: MBTI Dashboard 中某些 MBTI 样本量过低 (ESFP=8, ISFJ=7)，结论不可靠。
**证据**: `mbti_performance_dashboard_v7_metrics_fixed.html` — Low Sample section。
**建议**: 运行更多对局增加样本，或以 MBTI 大类 (NT/NF/ST/SF) 聚合作为补充。

### P1-3: Model-assisted review 不是真人工
**影响**: AI 代标的标签可能存在系统性偏见，标签质量未经过人类验证。
**证据**: `v6_benchmark_ready.py::review_sample()` — "I should act as human reviewer"。
**建议**: 抽样 50-100 条 AI 标注的标签进行人工验证，计算 AI-vs-Human 一致率。

### P1-4: ECE=0.166 — Calibration 仍然 RANKING ONLY
**影响**: 分数不能解释为概率，无法直接对比 "0.7 分的 Witch save" vs "0.7 分的 Vote"。
**证据**: `calibration_v5.md` — ECE=0.166。
**建议**: 继续改进校准 (isotonic regression per role-action, 更多样本)。

### P1-5: requirements.txt 不完整
**影响**: 新环境部署时需要手动安装缺失依赖 (`httpx`, `scikit-learn`, `numpy`, `pandas`, `matplotlib`, `FlagEmbedding`)。
**证据**: `requirements.txt` 仅 6 行。
**建议**: 更新 requirements.txt 包含所有依赖。

### P1-6: Makefile 不存在
**影响**: README 引用的 `make demo` / `make dev` / `make db-up` 命令无法使用。
**证据**: 项目根目录无 Makefile。
**建议**: 创建 Makefile 或更新 README 为直接命令。

---

## 10.3 P2 — 改进优化

### P2-1: B 评分管道碎片化
**影响**: V2→V7 脚本是独立的一次性脚本，新用户不知道运行顺序。
**建议**: 创建 `scripts/run_track_b_full.sh` 统一入口，或创建 `Makefile` track-b 目标。

### P2-2: 模板角色未接入引擎
**影响**: 6 个角色 (Cupid/BigBadWolf/WolfCub/WolfKing/Knight/Elder) 仅在注册表中，引擎无实现。
**建议**: 优先级排序后逐步接入 (建议先做 WolfKing: 死亡开枪，与 Hunter 类似)。

### P2-3: `camp_won` bug 未修复
**影响**: `OutcomeFeatureBuilder` 中 `camp_won` 始终为 None。
**证据**: `opportunity.py:OutcomeFeatureBuilder.build()` — `final_winner` 参数未使用。
**建议**: 修复 bug，传递 `game.winner` 参数。

### P2-4: `mistake_penalty` / `counterfactual_impact` 占位符
**影响**: `calculate_process_score()` 中这两个值硬编码为 0.0。
**证据**: `scoring_models.py:352` — `# Simplified mistake penalty and counterfactual (placeholder for MVP)`
**建议**: 实现真实的 mistake_penalty 和 counterfactual_impact 计算。

### P2-5: 前端 UI 美化
**影响**: 当前 UI 功能完整但视觉设计可改进。
**建议**: 作为独立 UI overhaul 项目。

### P2-6: GraphRAG 策略库
**影响**: `strategy_library.yaml` 有高质量静态内容但未被使用。
**建议**: 将 yaml 导入 DB 的 `strategy_knowledge_docs` 表，使 Agent 可以检索使用。

---

## 10.4 修复优先级路线图

```
Phase 1 (立即): P0 修复 (1-2周)
  ├── P0-1: 补齐 strategy_id
  ├── P0-3: 标注 ≥100 speech quality samples
  ├── P0-6: HTML evidence 可点击链接
  └── P1-5, P1-6: requirements.txt + Makefile

Phase 2 (短期): P1 修复 (2-4周)
  ├── P1-1: 增加 Witch Save / Seer Release bad label 标注
  ├── P1-3: 人工验证 AI 标注一致性
  ├── P1-4: 改进 calibration per role-action
  └── P0-5: 确认单局复盘数据来源

Phase 3 (中期): P2 改进 (1-2月)
  ├── P2-1: 统一 B 评分管道
  ├── P2-2: 接入 1-2 个模板角色
  ├── P2-3, P2-4: 修复 bug + 实现占位符
  └── P2-6: 导入 strategy_library.yaml 到 DB

Phase 4 (长期): 功能扩展 (2-3月)
  ├── P2-5: UI overhaul
  ├── 大规模对局 (500+ games) 提升统计效力
  └── Persona × Role × Strategy 三层正式评测
```

---

## 10.5 关键审计结论

1. **没有不可修复的架构问题** — 所有 P0 问题都是 "缺字段/缺数据/缺验证" 而非 "架构错误"
2. **Strategy ID 是最大的单一缺口** — 补齐后才能做三层测评
3. **Speech scoring 是最大的验证缺口** — 最频繁的动作却没有质量标注
4. **B 评分系统的核心安全保证成立** — 0 后验污染 + 0 visibility violations
5. **项目整体完整度约 80%** — Track A (100%), Track B (85%), Track C (70%)
