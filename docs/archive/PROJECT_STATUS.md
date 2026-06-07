# AI Werewolf 项目状态

> 更新: 2026-06-05 | 分支: `main` @ `40a76fe`
> 验证: `scripts/run_backend_full_strict.py` → **STRICT MODE: PASSED**

---

## 整体进度

| Track | 状态 | 关键指标 |
|-------|------|----------|
| **A** 基础对局 | ✅ 完成 | 7 人标准局全流程, CognitiveAgent Observe-Think-Act |
| **B** 评测复盘 | ✅ 完成 | 三级评分级联, PerStepScorer 100% 覆盖, PublishedReview |
| **C** 自进化 | ✅ 完成 | 99 lessons/局, 4-filter 安全管线, SAVEPOINT 隔离 |

---

## 当前架构

```
CognitiveAgent (Observe-Think-Act, 3-layer prompt)
  → StrategyRetriever (BM25 + 倒排索引 + 4-filter)
  → WerewolfGame (phased state machine, parallel _batch_ask)
  → PlayerView (3-view information isolation, 92 checks passed)
  → PerStepScorer (Tier1→Tier2→Tier3 cascade)
  → KnowledgeAbstractor → strategy_knowledge_docs → 下一局
```

详见 [`ARCHITECTURE.md`](ARCHITECTURE.md) 和 [`DATA_FLOW.md`](DATA_FLOW.md)。

---

## 快速命令

```bash
# 全量严格验证
python scripts/run_backend_full_strict.py

# 单局 LLM 对局
python scripts/run_full_llm_pipeline.py

# 多 Tier 对比实验
python scripts/multi_tier_experiment.py

# 启动后端
make dev

# 启动前端
cd frontend && npm run dev

# 跑测试
pytest tests/ -q

# 启动预检
python -m backend.ops.preflight
```

---

## 数据库

**PostgreSQL** @ `127.0.0.1:5433/werewolf` | 21 张表

关键表: `games`, `players`, `agent_decisions`, `strategy_knowledge_docs`, `published_reviews`, `leaderboard_entries`

---

## 已知限制

| 项 | 说明 |
|----|------|
| LLM 延迟 | 单次调用 3-20s, 引擎层并行化缓解 |
| 前端 | Replay Viewer 单独规划, 当前为上帝视角观战 |
| Track C 收敛 | Evolution loop 待更多对局验证 |
| Embedding | 豆包 embedding endpoint 暂不可用, 使用本地 hash |

---

*由小爪整理 (๑•̀ㅂ•́)و✧*
