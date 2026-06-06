# AI Werewolf 策略检索 — 最终方案

> 2026-05-31 | 策略库: 907条 | 测试: 40查询 × 8方法

---

## 一、实验结果

| # | 方法 | NDCG@5 | MRR | 延迟 | 评价 |
|---|------|:------:|:---:|:---:|------|
| 🥇 | **BM25 + BGE Dense RRF** | **0.723** | **0.734** | **70ms** | 全场景最优 |
| 🥈 | BGE DS-RRF + ColBERT | 0.696 | 0.694 | 293ms | Base查询最优(0.905) |
| 🥉 | Dynamic Alpha Fuse | 0.678 | 0.661 | 297ms | P@5最优(0.406) |
| 4 | BGE Dense+Sparse RRF | 0.670 | 0.639 | 166ms | — |
| 5 | BGE Sparse | 0.651 | 0.647 | 80ms | 轻量替代 |
| 6 | BGE Dense | 0.643 | 0.623 | 349ms | Base强/Bias大 |
| 7 | BM25 | 0.597 | 0.576 | **2ms** | 快速降级 |
| 8 | Query Expansion + ColBERT | 0.587 | 0.537 | 361ms | 反而退步 |

### 关键发现

1. **BM25 + BGE Dense RRF 全维度最优**：简单、高效、鲁棒
   - 修复了之前评测里 BM25 idx 的 bug 后，RRF 充分发挥了两者互补性
   - BM25 精确关键词（"查杀"、"警徽流"）+ BGE 语义（"银水" vs "被救者"）
   
2. **BGE Sparse 无法替代 BM25**：学出来的稀疏权重在中文策略文本上不如 BM25 + jieba

3. **ColBERT 在 Base 查询上很强 (0.905)** 但在特殊场景下降明显 (0.417)
   - 原因：特殊场景下 token 级匹配缺乏泛化

4. **Query Expansion 翻车**：加入相关术语反而引入噪声，降低了精度

5. **Dynamic Alpha 的 P@5 最高**：说明按查询熵值调权有一定效果，但不足以弥补排序质量的下降

---

## 二、生产方案

### 工程架构

```
PostgreSQL (strategy_knowledge_docs)
    │
    │ Agent启动时一次性加载 + 构建索引 (~5s)
    ▼
StrategyRetriever
    ├── BM25 Index (jieba tokenize → Okapi BM25)
    ├── BGE-M3 Dense Index (1024-dim, GPU)
    └── BGE-M3 ColBERT Index (可选, +28ms)
    │
    │ 每次查询:
    ├── BM25.search(query) → top-20 (2ms)
    ├── BGE Dense.search(query) → top-20 (30ms)
    ├── RRF fuse → top-20 (1ms)
    └── [可选] ColBERT rerank → top-5 (28ms)
    │
    ▼ ~70ms total (105ms with ColBERT)
format_strategies_for_prompt() → LLM Prompt
```

### 使用方式

```python
from backend.agents.cognitive.retrieval_prod import StrategyRetriever, format_strategies_for_prompt

# Agent 初始化时 (一次性)
retriever = StrategyRetriever(enable_rerank=False)  # False=70ms, True=105ms
retriever.build()  # ~5s, 从 PostgreSQL 加载+构建索引

# 每次决策时
strategies = retriever.search(
    query="我被真预言家查杀了应该怎么应对",
    role="Werewolf",
    phase="DAY_SPEECH",
    k=5,
)
prompt_text = format_strategies_for_prompt(strategies)
```

### 降级方案

| 场景 | 方案 | 延迟 | NDCG@5 |
|------|------|------|--------|
| GPU可用 | BM25 + BGE Dense RRF | 70ms | 0.723 |
| GPU可用 + 高精度 | BM25 + BGE Dense RRF + ColBERT | 105ms | ~0.73 |
| GPU不可用 | BM25 standalone | 2ms | 0.597 |

---

## 三、微调方案

### 数据生成

从策略库自动生成 triplet 训练数据：

```python
from backend.agents.cognitive.retrieval_prod import generate_finetune_data, finetune_retriever

# Step 1: 生成训练数据
retriever = StrategyRetriever(); retriever.build()
docs = retriever.get_docs()
generate_finetune_data(docs, output_path="data/finetune_triplets.jsonl", n_samples=500)
# → 生成 500 条 (anchor, positive, hard_negative) triplets

# Step 2: 对比学习微调
finetuned_path = finetune_retriever(
    model_path="/home/4T-3/PLM/bge-m3/",
    data_path="data/finetune_triplets.jsonl",
    output_path="/home/4T-3/PLM/bge-m3-werewolf-ft/",
    epochs=3,
)
```

### 微调策略

- **损失函数**：MultipleNegativesRankingLoss (in-batch negatives)
- **正例**：同角色+同阶段的策略对
- **难负例**：BM25 检索到的 top 但不相关结果
- **预期提升**：NDCG@5 +3-5%
- **微调耗时**：~10min on cuda:3 (500 triplets, 3 epochs)

### 微调后评估

```
微调后 BGE-M3 → 替换 dense 部分 → 重新跑检索对比
如果 NDCG@5 > 0.75 → 替换生产模型
否则 → 保持 zero-shot (当前 NDCG@5=0.723 已经足够)
```

---

## 四、与前沿方案的对比

| 方案 | 我们是否采用 | 原因 |
|------|:---:|------|
| BM25 + Dense RRF | ✅ 采用 | 全维度最优，简单高效 |
| BGE Sparse (learned) | ❌ 不采用 | 不如 BM25 + jieba |
| ColBERT Rerank | 🟡 可选 | Base查询强但特殊场景弱，+28ms |
| Dynamic Alpha (entropy) | ❌ 不采用 | P@5 略好但 NDCG 下降 |
| Query Expansion | ❌ 不采用 | 引入噪声，反而退步 |
| Cross-Encoder Rerank | ❌ 不采用 | 延迟高(350ms)且质量不如 RRF |
| Fine-tuning BGE-M3 | 🟡 待验证 | 理论+3-5%，需要跑微调确认 |

---

## 五、文件清单

| 文件 | 用途 |
|------|------|
| `backend/agents/cognitive/retrieval_prod.py` | 生产级检索器 + 微调管线 |
| `scripts/eval_final_retrieval.py` | 8方法对比评测脚本 |
| `scripts/eval_all_retrievers.py` | 4方法基础对比 |
| `scripts/eval_fullstack_retrieval.py` | BM25+Dense+Hybrid+Reranker |
| `scripts/eval_hybrid_rerank.py` | Hybrid RRF + Reranker |
| `docs/retrieval_final_design.md` | 本文档 |
| `docs/strategy_retrieval_evaluation.md` | 四方法对比报告 |
| `docs/strategy_retrieval_fullstack_eval.md` | 混合检索报告 |
