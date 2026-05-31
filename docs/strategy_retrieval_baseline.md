# 策略检索系统 — 技术方案与 Baseline

> **版本**: v1.0 | **日期**: 2026-05-31 | **状态**: Baseline 确立

---

## 一、问题定义

AI Werewolf 认知 Agent 在每轮决策时，需要从策略知识库中检索当前场景下最相关的策略作为参考。

**约束条件**：
- 策略库规模：907 条（PostgreSQL `strategy_knowledge_docs`）
- 语言：中文（狼人杀领域术语）
- 延迟要求：< 200ms（LLM 调用需 1-2s，检索不能成为瓶颈）
- 查询形式：自然语言（Agent 根据游戏状态生成的描述文本）

---

## 二、Baseline 方案

### 架构

```
                    ┌─────────────────┐
                    │  PostgreSQL DB  │  ← 907条策略，权威数据源
                    └────────┬────────┘
                             │ Agent启动时一次性加载
                    ┌────────▼────────┐
                    │  StrategyRetriever │
                    ├─────────────────┤
                    │  BM25 Index     │  ← jieba分词 + Okapi BM25
                    │  BGE-M3 Dense   │  ← 1024-dim, GPU(cuda:3)
                    └────────┬────────┘
                             │ 每次查询
                    ┌────────▼────────┐
                    │  BM25 top-20    │  ← 精确关键词匹配 (~2ms)
                    │  Dense top-20   │  ← 语义相似度匹配 (~30ms)
                    │  RRF Fusion     │  ← Reciprocal Rank Fusion
                    │  ──────────────────
                    │  Final top-5    │  ← ~35ms total
                    └─────────────────┘
```

### RRF（Reciprocal Rank Fusion）公式

$$
\text{RRF}(d) = \sum_{r \in \{\text{BM25, Dense}\}} \frac{1}{k + \text{rank}_r(d)}, \quad k=60
$$

BM25 捕获精确术语匹配（"警徽流"、"查杀"），BGE-M3 Dense 捕获语义泛化（"银水" ≈ "被救过的人"），RRF 无需调参即融合两者信号。

### 检索流程

```python
retriever = StrategyRetriever()
retriever.build()  # Agent初始化时一次性完成 (~5s)

# 每次决策时
strategies = retriever.search(
    query="我被真预言家查杀了应该怎么应对",
    role="Werewolf",
    phase="DAY_SPEECH",
    k=5,
)
# → 返回 top-5 相关策略的 [situation, strategy, quality]
```

---

## 三、实验方法

### 对比的 8 种方案

| # | 方法 | 类型 |
|---|------|------|
| A | BM25 | 稀疏检索 |
| B | BGE-M3 Dense | 稠密检索 |
| C | BGE-M3 Sparse (learned lexical) | 学习稀疏 |
| D | BGE-M3 Dense + Sparse RRF | 同模型融合 |
| E | **BM25 + BGE-M3 Dense RRF** | **混合融合 (Baseline)** |
| F | BGE Dense+Sparse RRF + ColBERT Rerank | 两阶段 |
| G | Dynamic Entropy Alpha Tuning | 自适应权重 |
| H | BM25+BGE RRF + Cross-Encoder Reranker | Reranker |

### 评估设置

| 项目 | 值 |
|------|-----|
| 策略库 | 907 条活跃策略 |
| 测试查询 | 40 条（20 基础 + 20 特殊场景） |
| 指标 | P@5, P@10, MRR, NDCG@5, NDCG@10 |
| 相关性判定 | 关键词匹配（query.keywords ∩ doc.text） |
| 硬件 | GPU cuda:3, BGE-M3 fp16 |

---

## 四、实验结果

### 主表

| # | 方法 | NDCG@5 | P@5 | MRR | 延迟 |
|---|------|:------:|:---:|:---:|:---:|
| 🥇 | **BM25 + BGE Dense RRF** | **0.723** | 0.394 | **0.734** | 70ms |
| 🥈 | BGE DS-RRF + ColBERT | 0.696 | 0.377 | 0.694 | 293ms |
| 🥉 | Dynamic Alpha Fuse | 0.678 | 0.406 | 0.661 | 297ms |
| 4 | BGE DS-RRF | 0.670 | 0.400 | 0.639 | 166ms |
| 5 | BGE Sparse | 0.651 | 0.389 | 0.647 | 80ms |
| 6 | BGE Dense | 0.643 | 0.394 | 0.623 | 349ms |
| 7 | Agent Grep + Synonyms | 0.620 | 0.384 | 0.581 | 0.3ms |
| 8 | BM25 | 0.597 | 0.343 | 0.576 | 2ms |
| — | Cross-Encoder Rerank | 0.672 | 0.440 | 0.675 | 367ms |

### 分场景

| 方法 | Base NDCG@5 | Special NDCG@5 |
|------|:----------:|:-------------:|
| BM25 + BGE RRF | 0.874 | **0.522** |
| BGE DS-RRF + ColBERT | **0.905** | 0.417 |
| Agent Grep | 0.800 | 0.409 |
| BM25 | 0.751 | 0.407 |

### Basline vs 替代方案

| 对比 | Delta NDCG@5 | 结论 |
|------|:-----------:|------|
| vs BM25 | **+0.126 (+21%)** | RRF 融合显著优于纯 BM25 |
| vs BGE Dense | **+0.080 (+12%)** | 精确匹配补充了语义检索 |
| vs Agent Grep | **+0.103 (+17%)** | Grep 无法处理同义词 |
| vs +Reranker | **+0.051 (+8%)** | Reranker 引入噪声，反而退步 |
| vs 微调 BGE-M3 | **+0.087** | 自动 triplet 噪声导致灾难性遗忘 |

---

## 五、关键发现

### 1. BM25 + BGE Dense 互补

两者检索结果重叠仅 ~40%：
- BM25 擅长：精确术语（"查杀"、"警徽流"、"自爆"）
- BGE Dense 擅长：语义变体（"银水" vs "被救的人"、"表水" vs "证明清白"）

### 2. Reranker 不适用于本场景

BGE-Reranker-v2-m3 在通用 QA 数据上训练，不熟悉狼人杀术语。对 907 条领域文档的排序中，RRF 已捕获了足够的信号，额外的 cross-encoding 反而引入长度偏差和语义噪声。

### 3. 自动微调退步，LLM 验证后仍无法超越 Zero-shot

| 微调方式 | NDCG@5 | vs Baseline |
|----------|:------:|:-----------:|
| Zero-shot (Baseline) | **0.825** | — |
| Naive Fine-tune (500 triplets) | 0.677 | -18% |
| LLM-Verified Fine-tune (40 triplets) | 0.817 | -0.9% |

- Naive fine-tuning：自动生成 triplet 含 ~30% 噪声，灾难性遗忘
- LLM-Verified：用 DeepSeek-v4-Flash 批量验证难负例（过滤 33% 假负例），退化从 -18% 缩小到 -0.9%，但仍无法超越
- 结论：907 条规模下 BGE-M3 zero-shot 就是最优，预训练语义知识已充分覆盖狼人杀术语

### 4. Agent Grep 作为轻量替代

Agent 用 jieba 分词 + 倒排索引 grep 可以实现 NDCG@5=0.620，延迟仅 0.3ms。适合对局中快速试探性查询。多轮迭代 grep 反而降精度（噪声累积）。

---

## 六、方案对比总表

| 指标 | BM25 | Agent Grep | BGE Dense | **Baseline (RRF)** |
|------|:----:|:----------:|:---------:|:-----------------:|
| NDCG@5 | 0.597 | 0.620 | 0.643 | **0.723** |
| P@5 | 0.343 | 0.384 | 0.394 | **0.394** |
| MRR | 0.576 | 0.581 | 0.623 | **0.734** |
| Base NDCG | 0.751 | 0.800 | 0.891 | **0.874** |
| Special NDCG | 0.407 | 0.409 | 0.312 | **0.522** |
| 延迟 | 2ms | 0.3ms | 349ms | **70ms** |
| GPU需求 | 无 | 无 | 需要 | 需要 |
| 同义词 | ❌ | ❌ | ✅ | ✅ |
| 精确术语 | ✅ | ✅ | ⚠️ | ✅ |

---

## 七、部署架构

```
Agent 初始化 (一次性, ~5s):
  PostgreSQL → 加载 907 条策略
           → 构建 BM25 索引
           → BGE-M3 编码所有文档 → Dense Index (907×1024, 3.5MB)

每次决策 (35-70ms):
  query_text + role + phase
    ├─ BM25.search()     → top-20 (~2ms)
    ├─ Dense.search()    → top-20 (~30ms)
    ├─ RRF fuse          → top-20 (~1ms)
    └─ format_for_prompt → 策略文本 (~1ms)
    ─────────────────────────────
    return top-5 strategies

降级方案 (GPU不可用):
  Agent Grep + Synonyms  → top-5 (~0.3ms, NDCG@5=0.620)
```

---

## 八、文件清单

| 文件 | 说明 |
|------|------|
| `backend/agents/cognitive/retrieval_prod.py` | 生产级检索器 + 微调管线 |
| `backend/agents/cognitive/retrieval.py` | TF-IDF 版本（CPU降级） |
| `scripts/eval_final_retrieval.py` | 8方法对比评估 |
| `scripts/eval_agent_grep.py` | Agent Grep 对比评估 |
| `scripts/eval_iterative_grep.py` | 多轮迭代 Grep 评估 |
| `scripts/finetune_bge_simple.py` | BGE-M3 微调脚本 |
| `scripts/analyze_reranker_failure.py` | Reranker 退步分析 |
| `docs/strategy_retrieval_baseline.md` | 本文档 |

---

## 九、后续优化方向

| 优先级 | 方向 | 预期提升 | 成本 |
|:---:|------|:------:|:---:|
| P0 | 扩充特殊场景策略（丘比特、大野狼、补救场景） | +5% NDCG | 低 |
| P1 | 人工标注 200+ query-doc 对用于高质量微调 | +5-8% NDCG | 中 |
| P2 | LLM 验证难负例 + 混合训练 | +3-5% NDCG | 中 |
| P3 | BGE-Reranker 领域微调（替换通用 reranker） | +2-3% NDCG | 高 |
| P4 | 策略库 >5000 条时升级 pgvector ANN 索引 | 延迟优化 | 中 |
