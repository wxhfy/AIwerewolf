---
name: agent-development
description: Agent Protocol / Decision 契约 / 信息隔离 / CognitiveAgent / LLM-only 规则
audience: claude, codex, human
version: 2.0.0
updated: 2026-06-08
---

# Agent 开发规范

> 适用范围：`backend/agents/` 目录。
> 当前对局 AI 席位默认且强制使用 LLM-compatible `CognitiveAgent`；`agent_type=heuristic` 会被 `backend/agents/factory.py` 拒绝。`HeuristicAgent` 和 legacy `LLMAgent` 仍可作为单元测试、历史兼容或调试参考，但不能作为正式对局 AI 席位。

---

## 一、Agent Protocol 接口（不可破坏）

单一事实来源：`backend/agents/base.py`。

```python
class Agent(Protocol):
    player_id: str

    def initialize(self, view: PlayerView, game_setting: dict) -> None: ...
    def update(self, view: PlayerView, request: str) -> None: ...
    def day_start(self) -> None: ...
    def talk(self) -> Decision: ...
    def vote(self) -> Decision: ...
    def attack(self) -> Decision: ...
    def divine(self) -> Decision: ...
    def guard(self) -> Decision: ...
    def witch_act(self, victim_id: str | None) -> list[Decision]: ...
    def shoot(self) -> Decision: ...
    def boom(self) -> Decision: ...
    def transfer_badge(self, candidates: list[str]) -> Decision: ...
    def finish(self, winner: str | None) -> None: ...
```

改这里会触发跨模块连锁反应：引擎主循环、`HumanAgent`、`CognitiveAgent`、legacy agents、前端真人操作、测试和文档都要同步。

新增 / 删除 / 改签名必须：

1. 事前说明影响面；
2. 同步更新 `skills/50-api-contract.md` 的内部协议段；
3. 增加或修正对应测试；
4. 在单人模式下仍按重灾区谨慎处理。

新增 Agent 类型时实现 Protocol 即可，不要求继承公共基类。

---

## 二、Decision 返回契约

单一事实来源：`backend/engine/models.py`。

```python
@dataclass
class Decision:
    actor_id: str
    action_type: ActionType
    target_id: str | None = None
    speech: str | None = None
    reasoning: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 字段要求

| 字段 | 要求 |
|---|---|
| `actor_id` | 必须等于 `self.player_id`，不能伪造其他玩家 |
| `action_type` | 必须是当前 Phase 允许的动作 |
| `target_id` | 需要目标时必须是合法玩家 id；无目标用 `None` |
| `speech` | `talk` / 遗言 / 警长总结等发言动作必须非空；不要包含 system prompt 或私有推理全文 |
| `reasoning` | 必填非空，供 `DecisionAudit`、Track B/C 复盘和调试使用 |
| `metadata` | 只放结构化审计信息，如 `segments`、`source`、`fallback`、`tool_trace`、`retrieved_doc_ids` |

### 当前 ActionType

```
talk, vote, attack, divine, guard, witch_save, witch_poison, shoot, boom, skip
```

### 反例

```python
# 错：旧字段名，当前 Decision 不接受 player_id/action/target/save
Decision(player_id=self.player_id, action=ActionType.VOTE, target="P1", save=False)

# 错：reasoning 为空
Decision(actor_id=self.player_id, action_type=ActionType.VOTE, target_id="P1", reasoning="")

# 错：把提示词或私有规划写进公开 speech
Decision(actor_id=self.player_id, action_type=ActionType.TALK, speech="你是狼人杀中的预言家。我的隐藏计划是...", reasoning="...")
```

---

## 三、信息隔离（铁律）

Agent 只能从 `view: PlayerView` 读取当前允许看到的信息。单一事实来源：`backend/engine/visibility.py`。

`PlayerView` 当前包含：

```python
@dataclass(frozen=True)
class PlayerView:
    game_id: str
    player_id: str
    day: int
    phase: str
    self_player: dict[str, Any]
    players: list[dict[str, Any]]
    public_events: list[dict[str, Any]]
    private_events: list[dict[str, Any]]
    known_wolves: list[dict[str, Any]]
    observations: list[str]
    legal_targets: dict[str, list[dict[str, Any]]]
```

红线：

- 禁止 Agent 接收或缓存完整 `GameState`。
- 禁止 Agent 通过 import 引擎或 DB 反查当前局隐藏信息。
- 狼队协作也必须走 `PlayerView` / `private_events` / 合法 wolf team view。
- Prompt 中不得加入 `PlayerView` 外的当前局私密信息。
- 给 `PlayerView` 加字段时必须先从 Visibility 层定义可见性，并补 `tests/test_visibility_final_agent_input.py` 或相关测试。

公开视角规则：

- `show_private=false` 时，夜间子阶段和夜间行动细节会在 `GameState.public_dict()` 中脱敏。
- 前端不能拿 private snapshot 后再自己过滤来冒充公开视角。

---

## 四、CognitiveAgent 组织

当前主路径：

```
backend/agents/cognitive/
├── agent.py              # CognitiveAgent，Protocol 适配层
├── agent_loop.py         # 工具调用式决策循环
├── observe.py            # PlayerView -> Observation / BeliefTracker
├── memory.py             # Memory / Planner / role state
├── social_model.py       # trust / suspicion / deception signals
├── prompts.py            # Cognitive prompt 组装
├── retrieval_prod.py     # Track C strategy retrieval
├── tools.py              # search_strategies / recall_memory / check_rules / ...
├── wolf_team.py          # 狼队合法可见协作信息
└── strategies/           # 分角色策略骨架
```

认知流程：

```
PlayerView -> Observation -> Memory/Belief/SocialModel/Planner
           -> AgentLoop(tools + LLM)
           -> Decision
           -> WerewolfGame 校验/结算/审计
```

Agent 只输出意图，绝不直接修改 `GameState`。

---

## 五、Prompt 与策略层

当前项目采用三层语义：

```
Persona / MBTI：说话风格、认知习惯、风险偏好
Role：身份、技能、胜利条件、反模式
Strategy：从 Track C knowledge / strategy cards 检索出的打法建议
```

注意：

- 角色层只能描述“身份和能力”，不要塞硬玩法。
- 策略层才能教“怎么玩”，并且要带来源、适用条件和可见性过滤。
- Prompt 不得硬编码真实 API 地址、API Key、玩家隐藏身份或当前局上帝视角。
- 公开发言必须经过引擎层清洗和分段逻辑，不能把内部计划句发布到 `CHAT_MESSAGE`。

---

## 六、LLM-only 与失败处理

核心约定：

1. 正式对局 AI 席位必须走 LLM-compatible agent：真实 LLM 或 test-only `LLM_PROVIDER=fake`。
2. `agent_type=heuristic` 在 `create_agents()` 中会抛 `ValueError`。
3. `_TEST_ALLOW_FAKE_LLM=true` 是唯一允许 fake provider 的测试入口；生产或正式实验不得开启。
4. `AIWEREWOLF_STRICT_MODE=true` 是默认口径：LLM 失败、空发言、非法目标、非法动作应抛错或记录 invalid，不得悄悄改为启发式代决策。
5. 某些“解析修复”（例如 native tool-call 空响应后要求同一个 LLM 用文本 `DECISION: {...}` 修复）不算 heuristic fallback；它仍然必须来自 LLM 响应。

审计字段：

- `DecisionAudit.is_valid`
- `DecisionAudit.error_type`
- `DecisionAudit.fallback_used`
- `DecisionAudit.fallback_reason`
- `DecisionAudit.raw_output`
- `DecisionAudit.parsed_action`
- `DecisionAudit.metadata`

正式实验结论必须能证明 `fallback_count=0` 或说明 fallback 样本已剔除。

---

## 七、HumanAgent

`HumanAgent` 用于真人混战：

- 不调 LLM；
- 引擎通过 `pending_input` 暂停等待；
- 前端通过 `POST /api/rooms/{room_id}/action` 提交 `{action, target, speech}`；
- 后端把 payload 转成当前 human seat 对应玩家的 `Decision`；
- 人类不响应时由前端提示，后端不应伪造人类选择。

---

## 八、新增 Agent / 修改 Agent 的流程

1. 先读 `backend/agents/base.py`、`backend/engine/models.py`、`backend/engine/visibility.py` 和本文件。
2. 明确新 Agent 是否允许正式对局使用；若是 AI 席位，必须 LLM-compatible。
3. 实现 Protocol 全部方法，尤其不要漏 `transfer_badge()`。
4. 在 `backend/agents/factory.py` 注册或显式拒绝 `agent_type`。
5. 增加测试：至少覆盖初始化、一次发言、一次投票、一次夜间动作、失败路径。
6. 如影响前端选项或 API 参数，同步 `frontend/types/index.ts`、i18n 和 `skills/50-api-contract.md`。

---

## 九、AI 改 Agent 的红线

- [ ] 不破坏 Agent Protocol 和 Decision 字段名。
- [ ] 不让 AI 席位绕过 LLM-only 约束。
- [ ] 不吞掉 LLM 失败并伪造“正常决策”。
- [ ] 不把当前局 private 信息越权写入 Prompt。
- [ ] 不把其他玩家 private reasoning 给当前 Agent。
- [ ] 不把 Prompt 全文、API Key、`.env` 写进代码或 commit。
- [ ] 改 Prompt / Strategy 必须提供验证方式或样例输出。

详见 `70-ai-collaboration.md`。

---

*Version 2.0.0 — 2026-06-08 — 同步当前 CognitiveAgent / LLM-only / Decision 字段实现。*
