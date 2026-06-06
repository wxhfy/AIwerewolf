---
name: agent-development
description: Agent Protocol / Decision 契约 / 信息隔离 / Prompt 模板 / LLM 调用降级
audience: claude, codex, human
version: 1.0.0
updated: 2026-05-22
---

# Agent 开发规范

> 适用范围：`backend/agents/` 目录。
> 当前已有 Agent：`HeuristicAgent`（规则启发式）、`LLMAgent`（LLM + 启发式降级）、`HumanAgent`（人类输入）。
> Prompt 模板：`backend/agents/prompts.py`；角色画像：`backend/agents/profiles.py`、`characters.py`。

---

## 一、Agent Protocol 接口（不可破坏）

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
    def finish(self, winner: str | None) -> None: ...
```

**改这里要触发跨模块连锁反应**（引擎主循环 + 全部 Agent 子类 + 测试）。
任何新增 / 删除 / 改签名的 PR：

1. 必须在群里事前通知
2. 必须在 `skills/50-api-contract.md` 里更新 "内部 Agent 协议" 段
3. 必须 2 人 approve（见 `10-git-workflow.md` 重灾区表）

**新增 Agent 类型**：实现 Protocol 即可，**不要继承**（duck typing）。

---

## 二、Decision 返回契约

```python
@dataclass
class Decision:
    player_id: str           # 必填，必须等于 self.player_id
    action: ActionType       # talk / vote / attack / ... / skip
    target: str | None       # 目标玩家 id；无目标用 None
    speech: str | None       # 发言文本（talk 时必填，其他时可选）
    reasoning: str           # 推理过程（评测复盘必看，必填非空）
    save: bool | None        # 仅 witch_act 用：是否用解药
```

### 必须保证

| 字段 | 检查 |
|------|------|
| `player_id` | 等于 `self.player_id`，不能伪造别人 |
| `action` | 必须是当前 Phase 允许的动作（引擎会再校验，但 Agent 自己也要校验） |
| `target` | 若需要目标，必须是**当前存活**的玩家 id |
| `speech` | `talk` / `last_words` 时必填，<= 3000 字 |
| `reasoning` | 永远非空，至少一句话；用于评测复盘 |

### 反例

```python
# 错：返回了死人当目标
Decision(player_id=self.player_id, action=ActionType.VOTE, target="dead_player_id", ...)

# 错：reasoning 留空
Decision(..., reasoning="")

# 错：speech 包含 system prompt 内容（LLM 复读）
Decision(..., speech="你是狼人杀中的预言家。我决定查验...")
```

---

## 三、信息隔离（铁律）

Agent **只能**从 `view: PlayerView` 读取信息：

```python
@dataclass(frozen=True)
class PlayerView:
    player_id: str
    day: int
    phase: str
    self_player: dict           # 自己的全部信息
    players: list[dict]         # 其他玩家：仅 public_dict()，狼人间可见 private_dict()
    public_events: list[dict]   # 全局公开事件
    private_events: list[dict]  # 仅本 Agent 可见的事件
    known_wolves: list[dict]    # 仅狼人非空
    observations: list[str]     # 提炼后的观察文字
```

### 红线

- **禁止** Agent 接收 `GameState` 全局状态
- **禁止** Agent 在内部偷偷 import `from backend.engine.game import ...` 反查信息
- **禁止** Agent 与 Agent 之间直接通信（狼队私聊也走 `private_events`）
- **禁止** LLM Prompt 里塞入 `PlayerView` 之外的数据

### Visibility 层规则（实现侧）

- `visibility.py` 的 `for_player` 是唯一信息分发口
- 新增私有信息 → 在 `GameEvent` 里加 `visibility="private"` + `visible_to=[...player_ids]`
- 公开信息 → `visibility="public"`
- **不要**给 PlayerView 加新字段而不过 Visibility 层

---

## 四、Prompt 模板组织

```
backend/agents/
├── prompts.py        # 唯一的 Prompt 文件
│   ├── GAME_RULES                  # 全局规则（固定）
│   ├── ROLE_SYSTEM_PROMPTS         # 各角色 system prompt
│   ├── ACTION_STRATEGIES           # 各动作策略指引
│   └── OUTPUT_FORMATS              # 各动作 JSON Schema
├── profiles.py       # ROLE_PROFILES 角色画像（背景设定）
├── characters.py     # AI 人格（MBTI 风格）
├── playbooks.py      # build_role_brief：拼装角色简报
└── llm_agent.py      # LLM 调用 + 解析 + 降级
```

### Prompt 分层结构（来自 WereWolfPlus）

```
SYSTEM:    GAME_RULES + ROLE_SYSTEM_PROMPTS[role] + character persona
USER:      STATE (day/phase/alive) + OBSERVATIONS + ACTION_STRATEGY + OUTPUT_FORMAT
```

### 修改 Prompt 的 PR 要求

- **PR 描述必须贴对比**：改前/改后的 LLM 实际输出（至少 2 种角色 × 2 种 seed）
- 改 `GAME_RULES` 或 `ROLE_SYSTEM_PROMPTS` → 重灾区，2 人 approve
- 改单个 `ACTION_STRATEGIES[role]` → 1 人 approve
- **不要**在 Prompt 里硬编码玩家名 / seat —— 用占位符 `{player_name}` / `{seat}`

### Prompt 禁止内容

- 任何 API Key / 真实接口地址（连示例都不行）
- 推理"作弊"提示（如告诉狼人查验结果）
- 与 `visibility.py` 不一致的信息（如告诉村民"你能看到所有人身份"）
- 给 LLM 看其他玩家私有的 `reasoning` 字段

---

## 五、LLM 调用与降级

### LLM-only 对局的设计

```python
class CognitiveAgent(Agent):
    """LLM-backed agent; failures raise in game mode."""

    def __init__(self, ...):
        self.client = create_client(provider=..., model=...)
        self.client.timeout = 12.0
```

**核心约定**：

1. 对局中的 AI 席位必须走 LLM-compatible Agent（真实 LLM 或 `LLM_PROVIDER=fake` 测试 stub）
2. LLM 调用超时 / 报错 / 输出非法 JSON → **抛错或标记失败**，不得切到 `HeuristicAgent`
3. timeout 上限 **12 秒**，不要无脑加长
4. 必须缓存 `system prompt`（前缀缓存）以省 token
5. `temperature` 默认 `0.4`，狼人/女巫等需要创造性的 ≤ 0.7

### Fallback 触发条件

| 触发场景 | 行为 |
|----------|------|
| LLM 调用 timeout / 异常 | 记录错误并让本局 / 本轮验收失败 |
| LLM 返回非 JSON | 记录解析错误，不发布为 ApprovedReviewReport |
| LLM 返回的 target 不在合法范围 | 记录 invalid decision，不得用 heuristic 替换 |
| LLM 返回的 action 与 phase 不匹配 | 记录 invalid decision，不得用 heuristic 替换 |

### LLM 调用规范

- 用 `backend/llm/create_client()` 统一接口，**不要**自己 `import openai`
- API Key 走 `backend/llm/env.py` 读 `.env`，**永远**不进代码
- 单次调用 `max_tokens` 显式设置（如 `520` 用于发言），不要默认无上限
- 同一个动作的 LLM 调用**只调一次**——不要循环重试，失败就 fallback

---

## 六、HumanAgent

`HumanAgent` 用于 AI + Human 混合对局：

- 不调 LLM，等前端用户输入
- `talk()` / `vote()` 等 block 等待，引擎通过 WebSocket 推 `await_human_input` 事件
- 前端 POST `human_input` API 把决策塞回来
- **不需要**实现 fallback——人类不响应就一直等（前端有超时提示）

---

## 七、新增 Agent 类型流程

1. 在 `backend/agents/` 新建文件，如 `random_agent.py`
2. 实现 Protocol 的全部 13 个方法
3. 在 `backend/agents/factory.py` 的 `create_agents()` 注册新 `agent_type`
4. 在 `tests/test_engine.py` 加一个跑通的测试
5. 在 `backend/app.py` / 前端 select 列表里曝光新类型
6. PR 描述里说明：这个 Agent 何时用、与其他 Agent 的差异、典型胜率

---

## 八、Prompt 工程经验提示

| 经验 | 来源 |
|------|------|
| **角色 + 阵营双层 prompt**：先给角色规则，再给阵营策略 | WereWolfPlus |
| **JSON Output 用 Schema 约束**：用 `"action": "talk", "target": "...", ...` 固定格式 | WereWolfPlus |
| **System Prompt 缓存**：前缀稳定，仅 USER 部分变 | 省 token |
| **观察去重**：相同信息只塞一次，否则 LLM 会复读 | 实战 |
| **明确禁止**：在 prompt 里写"禁止 X"比"请 Y"更有效 | LLM 通病 |
| **fallback 留痕**：失败时存 `last_error` 供复盘 | 评测必需 |

---

## 九、AI 改 Agent 的红线

- [ ] 没有破坏 Agent Protocol 接口
- [ ] Decision 字段齐全，`reasoning` 非空
- [ ] 仅从 `view: PlayerView` 读信息
- [ ] LLM 调用有 fallback
- [ ] Prompt 修改有对比输出
- [ ] 没有把 API Key / Prompt 全文塞进 commit
- [ ] 没有在 Prompt 里写"作弊"信息

详见 `70-ai-collaboration.md`。

---

*Version 1.0.0 — 2026-05-22 — 初始建立。*
