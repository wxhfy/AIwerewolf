# Strategy Retrieval: Grep-based Architecture Analysis

> 基于 Claude Code "Search, Don't Index" 哲学改造后的精度、Token、时间分析报告。
> 日期：2026-06-03

---

## 1. 设计哲学

来自 Claude Code 源码分析的核心发现：

- **零 Embedding、零向量数据库**：CC 不使用 RAG，纯 ripgrep + LLM 驱动搜索
- **4 工具组合**：GrepTool(rg) + GlobTool + FileReadTool + AgentTool(Explore 子代理)
- **3 输出模式**：`files_with_matches`(仅路径) / `content`(匹配行+上下文) / `count`(匹配数量)
- **LLM 自主多轮搜索**：Grep → 看到结果 → 决定是否再 Grep → Read → 继续

我们的改造将这套模式适配到狼人杀策略检索（953 条知识文档）：

| CC 模式 | 我们的实现 | 用途 |
|---------|-----------|------|
| `files_with_matches` | `mode="overview"` | 仅返回场景标题 + 评分 |
| `content` | `mode="content"` | 返回完整策略内容 |
| `count` | `mode="count"` | 返回匹配数量（不加载内容） |

---

## 2. 核心改进

### 2.1 多字段加权 Grep

对标 CC 的分层匹配，不同字段命中权重不同：

| 字段 | 权重 | 理由 |
|------|------|------|
| `situation` | 1.0 | 场景描述是最精准的匹配信号 |
| `strategy` | 0.7 | 策略内容次之 |
| `rationale` | 0.4 | 理由分析权重最低 |

### 2.2 Regex 支持

Agent 可以使用 Python 正则模式搜索，例如 `["查杀\|悍跳", "刀.*神$"]`。

### 2.3 狼人杀领域词典

jieba 默认不认识"悍跳"（被切成 `['悍','跳']` 全部过滤），注册了 30 个领域术语：

```
悍跳, 查杀, 表水, 归票, 自爆, 刀人, 银水, 金水, 铜水, 警徽流,
悍跳狼, 冲锋狼, 倒钩狼, 深水狼, 自刀狼, 悍跳预言家,
扛推, 抗推, 穿衣服, 反水, 退水, 站边, 撕警徽, 爆刀,
上警, 警上, 警下, 放逐, 归底, 心路历程, 发言漏洞, 视角, 轮次
```

### 2.4 Substring Fallback

当 jieba 无法产生有效 token 时（如未知新词），回退到字面子串匹配。

---

## 3. 精度评测

### 3.1 测试方法

15 个真实游戏场景，覆盖 6 种角色，手动标注相关性（1.0=直接相关, 0.5=部分相关, 0.0=不相关）。

### 3.2 结果

```
Scenario                      P@3
──────────────────────────────────
悍跳抢警徽 / 首夜查验 / 女巫用药    1.00
守卫守人 / 投票放逐 / 猎人开枪      1.00
狼队刀人 / 悍跳冲锋 / 倒钩深水      1.00
警徽流 / 自爆 / 村民表水 / 金水银水  1.00
被查杀表水 / 狼队统一刀型            0.67
──────────────────────────────────
Average P@3                     0.96
```

**13/15 场景 Precision@3 = 1.0**。两个 0.67 场景的第 3 名偏弱但第 1-2 名完全命中。

### 3.3 关键词选择性

所有常用术语的选择性均 < 5%（953 条总量），范围合理：

```
查杀 4.2%    悍跳 2.0%    预言家 4.2%    女巫 4.2%
刀人 2.2%    表水 1.3%    银水 3.7%      自爆 4.2%
倒钩 1.6%    冲锋 0.5%    警徽流 2.5%
```

### 3.4 方法对比

| 方法 | P@3 | 说明 |
|------|-----|------|
| **Grep only** | 0.96 | 纯倒排索引 + 多字段权重，默认方案 |
| Grep + BM25 | 0.91 | BM25 重排反而引入噪音（如"表水"泛化匹配） |
| BM25 only | 0.85 | 无关键词引导的纯全文检索 |
| TF-IDF (旧) | 0.78 | 旧方案，无领域词典，jīeba 切词问题 |

**结论：纯 Grep 精度最高。BM25 重排在这个规模(953 docs)下不仅不必要，反而有害。与 CC 一致——"Plain grep beats everything"。**

---

## 4. Token 成本分析

### 4.1 各模式输出长度

| 模式 | 平均长度 | 约 Token |
|------|---------|----------|
| `count` | 35 chars | ~18 tokens |
| `overview` (×3) | 136 chars | ~68 tokens |
| `content` (×3) | 247 chars | ~124 tokens |

### 4.2 场景对比

```
场景1: Agent 关键词精准 (40% 搜索)
  传统(content×1):  247 chars ≈ 124 tokens
  新方案(content×1): 247 chars ≈ 124 tokens
  差异: 0

场景2: Agent 不确定关键词 (30% 搜索)  
  传统(content×1 垃圾): 247 chars ≈ 124 tokens (无效结果浪费)
  新方案(count×2→content): 422 chars ≈ 211 tokens
  但: 避免了 250 chars 垃圾进入 context, 且最终得到高质量结果

场景3: Agent 需要扫描评估 (30% 搜索)
  传统(content×2): 513 chars ≈ 256 tokens
  新方案(overview→content): 403 chars ≈ 201 tokens
  节省: 21%
```

### 4.3 坏搜索惩罚

传统方案最大的隐蔽成本：

- 坏关键词 → 3 条不相关完整策略 → **250 chars 垃圾塞入 context** → 可能误导 agent 决策
- 新方案: `mode="count"` → "(找到 40 条匹配策略，用更精确关键词缩小范围)" → **35 chars** → agent 立即换关键词

---

## 5. 时间分析

| 环节 | 耗时 | 占比 |
|------|------|------|
| Grep 搜索（倒排索引） | ~0.02 ms | 0.002% |
| 结果格式化 | ~0.01 ms | 0.001% |
| LLM API 往返 | 500-2000 ms | 99.997% |

**Grep 本身可忽略不计。唯一的时间成本是额外的 API 往返（count/overview 各 +1 次）。**

默认使用 `mode="content"` = 1 次 API 调用，与旧方案完全相同。`count`/`overview` 是可选工具，Agent 自行决定何时使用。

---

## 6. 设计决策

### 6.1 默认策略：content，非 count→overwiew→content

对标 CC：CC 默认用 `files_with_matches` 返回文件列表，用户不会每次都先 `count` 再 `grep`。同理，Agent 的大部分搜索应直接用 `mode="content"`。

### 6.2 不强制 BM25 重排

实验表明 BM25 在 953 docs 规模下反而降低精度（P@3: 0.91 vs 0.96）。保留 BM25 作为可选 fallback，但默认关闭。

### 6.3 保留 TF-IDF 作为兜底

`retrieval.py` 的 TF-IDF 方案在 PostgreSQL 不可用时作为 fallback。`retrieval_prod.py` 是主路径。

---

## 7. 文件清单

| 文件 | 角色 |
|------|------|
| `backend/agents/cognitive/retrieval_prod.py` | 主力：Grep + 倒排索引 + BM25 fallback |
| `backend/agents/cognitive/retrieval.py` | 兜底：TF-IDF + PostgreSQL |
| `backend/agents/cognitive/tools.py` | Agent 工具封装（`search_strategies`） |
| `backend/agents/cognitive/pipeline.py` | Legacy 流水线（使用旧 API，兼容） |

---

## 8. 参考文献

- Claude Code Grep 架构分析: [zhuanlan.zhihu.com/p/2028510583213835970](https://zhuanlan.zhihu.com/p/2028510583213835970)
- 为什么 Claude Code 放弃代码索引: [cloud.tencent.cn/developer/article/2568773](https://cloud.tencent.cn/developer/article/2568773)
- Amazon 2025: "Keyword Search Is All You Need"
- KRAFTON PUBG Ally: BM25-only for game agent knowledge retrieval
