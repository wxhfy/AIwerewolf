# AI Werewolf 工程化验收门禁

本文定义真实模型对局进入下一阶段前必须满足的四类基础门禁。门禁关注的是系统是否可靠运行，不替代 Track B/C 的策略质量评估。

## 1. 真实模型调用

目标：确认对局确实由配置的模型完成，而不是 fake、静态规则或隐式 fallback。

必须满足：

- `provider`、`model_name` 被写入每条 `agent_decisions`。
- `metadata.model_backed=true`。
- `fallback_used=false`。
- 严格模式下模型不可用应让对局失败，不能静默替换为 fake。
- `ALLOW_FALLBACK=false` 时，模型请求失败或修复失败必须返回失败状态；确定性兜底只允许测试或明确开发环境启用。
- Harness 事件至少包含 `model.requested`、`model.responded`、`action.accepted`。

## 2. 游戏流程完整性

目标：状态机、事件、快照和终局结果保持一致。

必须满足：

- 对局最终进入 `GAME_END`。
- `games.status=finished`，且有 `winner`、`finished_at`。
- 最终快照中的存活玩家、死亡记录和 `GAME_END` 事件一致。
- 胜负原因必须符合当前规则包：
  - `all_wolves_dead`：狼人全部出局，好人胜利。
  - `wolves_reached_parity`：狼人数量达到好人阵营存活数量。
  - `all_gods_dead`：启用屠边规则时，神职全部出局。
  - `all_villagers_dead`：启用屠边规则时，普通村民全部出局。

当前狼人杀规则包采用“人数平衡 + 屠边”胜负规则。若后续切换为其他规则，必须单独建立新的 `rule_pack_id`，不能在引擎中隐式改变语义。

## 3. 动作合法性

目标：模型只能从服务端生成的动作空间中选择动作，领域引擎是最终裁判。

边界分为三层：

1. `DecisionAdapter` 只生成当前角色和阶段允许的候选动作。
2. Harness 校验 `option_id`、响应结构和动作参数；最多允许一次低成本修复。
3. `ActionValidator` 在引擎执行前再次校验角色、存活状态、目标状态、警长候选集和 PK 候选集。

最终统计必须区分：

- `is_valid`：最终执行动作是否合法。
- `repair_used`：模型第一次输出是否需要修复。
- `fallback_used`：是否使用了兜底动作。

`is_valid=1` 不代表模型第一次就正确，因此不能只看最终合法率。

## 4. 信息隔离

目标：每个角色只能看到自己的私有事实、队友共享事实和公开信息。

运行时 `Visibility` 必须 fail-closed：

- 非狼人没有 `known_wolves`。
- 非本人玩家不能携带 `role` 或 `alignment`。
- 狼人只能看到狼人队友的角色信息。
- 私有事件必须包含当前玩家在 `visible_to` 中。
- 公开事件流不能混入私有事件。
- 公开发言中的狼人私有视角、隐藏夜间动作和系统字段必须被审计。

## 5. 当前状态

截至 2026 年 9 月 24 日：

- 真实 GLM 对局已完成，使用 `bigmodel/glm-4-flash-250414`，未使用 fake fallback。
- 本次新增了 `PlayerView` 运行时隔离断言。
- 修复了决策持久化中 `alive_count=0` 的摘要错误。
- 动作验证新增警长竞选和 PK 投票候选集约束。
- 后端完整测试集通过，静态检查通过。

下一阶段再优化发言理解、信念更新和策略质量，不应绕过以上四类基础门禁。
