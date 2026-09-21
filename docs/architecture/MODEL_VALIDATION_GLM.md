# GLM 官方与托管模型链路验证

> 本文同时记录 SiliconFlow 托管的 `THUDM/GLM-4-9B-0414` 与智谱 BigModel 官方免费模型 `glm-4-flash-250414` 的真实整局验证。智谱官方 Chat Completions 地址为 `https://open.bigmodel.cn/api/paas/v4/chat/completions`。项目配置 API Root `https://open.bigmodel.cn/api/paas/v4`，客户端自动追加 `/chat/completions`。

## 验证结论

本地执行环境已使用 SiliconFlow 的免费模型 `THUDM/GLM-4-9B-0414` 完成两层验证：

1. 单请求连通性验证成功，返回预期标记，耗时 4.551 秒。
2. 7 人纯 AI 整局验证成功，游戏正常进入 `GAME_END`。

整局结果：

| 指标 | 结果 |
|---|---:|
| 模型 | `THUDM/GLM-4-9B-0414` |
| Provider | `siliconflow` |
| 玩家数 | 7 |
| 最终胜方 | 狼人阵营 |
| 结束天数 | 第 2 天 |
| 总耗时 | 215.94 秒 |
| Agent 决策数 | 46 |
| 模型成功决策 | 46 |
| JSON 修复 | 0 |
| 确定性兜底 | 0 |
| Harness 事件 | 388 |
| 平均端到端决策耗时 | 约 4.69 秒 |

这次结果证明整局不是依靠兜底逻辑“假跑通”：46 次决策均由真实模型成功完成，数据库中保留了完整决策和 Harness 事件。

另执行了一次 `agentic` 模式真实请求：GLM 正确接受包含 `submit_action`、Skill 加载和角色视角工具的 `auto` 工具协议，并直接选择 `vote:P2`。本次没有调用额外工具，说明模型可以在证据充分时直接结束，而不是机械消耗工具预算。

## 运行配置

```yaml
provider: siliconflow
model: THUDM/GLM-4-9B-0414
tool_calling: true
temperature: 0.35
timeout: 35
max_retries: 0
deadline_ms: 35000
```

API Key 只从环境变量 `SILICONFLOW_API_KEY` 读取，不写入配置、日志和仓库。

## 如何复现

Provider 工厂已支持以下等价名称：

```text
siliconflow
silicon_flow
```

智谱官方 Provider 使用 `bigmodel`、`zhipu` 或 `glm`，读取 `BIGMODEL_API_KEY`、`ZHIPU_API_KEY` 或本机既有的 `GLM_API_KEY`。两类 Provider 不共享密钥和模型名称。

智谱官方推荐配置：

```powershell
$env:LLM_PROVIDER = "bigmodel"
$env:BIGMODEL_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
$env:BIGMODEL_MODEL = "glm-4-flash-250414"
$env:BIGMODEL_API_KEY = "<local-secret>"
python -m backend.run_demo --seed 21 --provider bigmodel
```

2026-09-21 使用本机 `novel_map_clean` 已有的 `GLM_API_KEY`，通过上述官方链路完成了 7 人真实整局验证：

| 指标 | 结果 |
|---|---:|
| Provider | `bigmodel` |
| 模型 | `glm-4-flash-250414` |
| 玩家数 | 7 |
| 最终阶段 | `GAME_END` |
| 最终胜方 | 狼人阵营 |
| 结束天数 | 第 2 天 |
| 持久化模型决策 | 28 |
| 非法决策 | 0 |
| Harness 事件 | 234 |

验证期间还修复了两条 demo 专属启动链路问题：命令行默认值覆盖 `LLM_PROVIDER`，以及 YAML 配置路径绕过持久化初始化。当前 demo 会在终局写入最终状态，但不会同步执行 Track B/C，正式 Match Worker 仍使用带 Outbox 的原子完成事务。

也可以把 `BIGMODEL_BASE_URL` 配成完整的 `https://open.bigmodel.cn/api/paas/v4/chat/completions`，Provider 会自动去掉末尾路径，再由统一客户端追加一次。模型名应以当前智谱账号实际开放的免费模型为准。

推荐配置：

```powershell
$env:LLM_PROVIDER = "siliconflow"
$env:SILICONFLOW_MODEL = "THUDM/GLM-4-9B-0414"
$env:AGENT_DECISION_DEADLINE_MS = "35000"
python -m backend.run_demo --seed 21
```

## 结果解释

- 当前主流程、信息隔离、结构化动作、持久化和终局推进已经能够在真实模型下工作。
- 当前性能瓶颈主要是模型等待时间以及不能并行的顺序发言，不是 Python 状态机本身。
- 单局约 216 秒不等于系统吞吐只能串行处理一局。生产吞吐由 Match Worker 数量、模型并发和数据库容量共同决定。
- 这次验证只证明可执行性和基础稳定性，不等于发言质量、推理质量和策略演进已经达到研究级标准。
