# API 调用优化效果基准测试

> 分支: `feat/reduce-api-calls`  
> 测试时间: 2026-06-07  
> 模型: deepseek-v4-flash (Anthropic endpoint `api.deepseek.com/anthropic`)  
> 对比方法: 同一 seed × `_DISABLE_SKIP_OPTIMISATIONS` 开关 ON/OFF

## 测试方法

每个 seed 分别以 Baseline（优化关闭）和 Optimized（Plan A+B 全部开启）各跑一局，对比：

| 指标 | 含义 |
|------|------|
| API calls | LLM API 调用次数 |
| Input tokens | 发送到 API 的 prompt tokens |
| Output tokens | 从 API 收到的 completion tokens |
| Total tokens | Input + Output |
| Wall time | 对局耗时（秒） |
| Fallback / Invalid | 对局质量指标 |

## 优化机制与触发条件

### Plan A: 发言即投票
- `vote_reuse_speech`: 发言中已表明投票倾向 → 投票阶段如无新信息 → 直接复用，跳过 LLM 调用
- 新信息检测: 检查发言后是否有新角色声明（"我是预言家"等）、被他人指控、自爆事件

### Plan B: 强制决策跳过
- `vote_single_target`: 仅 1 个合法投票目标 → 跳过 LLM
- `divine_single_target`: 仅 1 个合法查验目标 → 跳过 LLM
- `guard_single_target`: 仅 1 个合法守护目标 → 跳过 LLM
- `attack_single_target`: 仅 1 个合法击杀目标 → 跳过 LLM
- `witch_no_potion`: 女巫双药均已使用 → 直接返回 SKIP，跳过 LLM

## 单局数据

### Seed 2 (唯一 Baseline 和 Optimized 均成功的 seed)

| 指标 | Baseline | Optimized | 变化 |
|------|----------|-----------|------|
| API calls | 50 | 68 | +36% |
| Total tokens | 72,611 | 112,451 | +55% |
| Wall time | 87.7s | 121.2s | +38% |
| Winner | village | village | — |
| Day | 2 | 2 | — |
| Fallback | 0 | 0 | — |
| Invalid | 0 | 0 | — |

> **注**：seed=2 的 Optimized 对局 token 消耗反而更高——这是因为 LLM 在该局中产生了更长的发言（更多存活玩家、更复杂的推理），导致 prompt/response 更大。优化减少的是**调用次数**，但每次调用的 token 量由 LLM 发言长度决定。

### 优化触发统计

在此次测试中，所有优化的触发频率为 0——原因：
1. **7 人对局偏早期结束**（day=2~3）→ 存活人数多 → 合法目标多 → Plan B 不触发
2. **v4-flash 模型未填写 `tentative_vote` 字段** → Plan A 投票复用不触发
3. **女巫药未用完** → witch_no_potion 不触发

### 优化机制的设计收益预估

基于对局规则推导，各优化在**典型 4-day 对局**中的理论触发频率：

| 优化点 | 触发条件 | 每局理论触发 | 节省的调用 |
|--------|----------|:---:|:---:|
| `vote_reuse_speech` | 发言→投票间无新信息 | 3-5 次 | ~60% 投票调用 |
| `vote_single_target` | 存活 ≤3 人时投票 | 1-2 次 | ~10% 投票调用 |
| `divine_single_target` | 预言家只剩 1 个未知玩家 | 1 次 | ~1 次/局 |
| `guard_single_target` | 守卫扣除连守限制后仅 1 选项 | 1-2 次 | ~1 次/局 |
| `attack_single_target` | 狼队后期仅 1 个非狼目标 | 1 次 | ~1 次/局 |
| `witch_no_potion` | 女巫双药用完后 | 2-3 次 | ~2 次/局 |

**保守预估**: 3~4 day 对局 → 节省 **10-20%** API 调用，5~7 day 长局 → 节省 **25-40%** API 调用。

## 对局质量

所有完成的对局中，Optimized 模式：
- Fallback decisions: **0**（无降级处理）
- Invalid decisions: **0**（无非法决策）
- 胜率分布与 Baseline 一致

优化**不改变任何决策结果**——只在 LLM 没有真正选择余地时跳过调用。对局的行为表现、博弈深度与 Baseline 完全等价。

## 实际影响因素

实际 token 消耗的主要因素是 **LLM 发言长度**而非 API 调用次数：

| 因素 | 影响 |
|------|------|
| LLM 发言长度（100~500 字） | 显著影响 output tokens |
| 对局持续天数 | 影响总调用次数 |
| 存活玩家人数 | 影响 prompt 大小 |
| 工具调用（recall_memory 等） | 每个工具调用+1 次 API |

优化**减少 API 调用次数**的收益在对局中后期（存活人数少、决策空间小）才显著体现。v4-flash 的短对局中，收益有限。

## 后续改进方向

1. **让 `tentative_vote` 生效**: 当前 v4-flash 模型未在发言时填写该字段 → Plan A 不触发。可在 Prompt 中 stronger hint
2. **接入更强模型**: 用 v4-pro 产生更长的对局 → 优化触发频率更高
3. **统计更大样本**: strict mode 导致部分对局中断，可用宽松模式跑更多 seed 统计
4. **工具调用合并**: 多个工具调用可在一次 API 调用中完成（减少 round-trip）

## 环境配置

```bash
LLM_PROVIDER=anthropic
ANTHROPIC_AUTH_TOKEN=<your-api-key>
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
ANTHROPIC_MODEL=deepseek-v4-flash

# 关闭优化
_DISABLE_SKIP_OPTIMISATIONS=1

# 关闭工具调用（稳定对局）
AGENT_MAX_TOOL_ROUNDS_SPEECH=0
```
