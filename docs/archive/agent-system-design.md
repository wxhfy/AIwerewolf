# AI Werewolf Agent 系统设计详解

> 生成时间：2026-05-26 | 基于项目实际代码与开发记录

---

## 目录

- [一、设计目标与核心命题](#一设计目标与核心命题)
- [二、整体架构](#二整体架构)
- [三、信息隔离 —— 架构级安全保障](#三信息隔离--架构级安全保障)
- [四、双层扮演架构（wolfcha 风格）](#四双层扮演架构wolfcha-风格)
- [五、Prompt 工程详解](#五prompt-工程详解)
- [六、防幻觉多层防御体系](#六防幻觉多层防御体系)
- [七、关注角度系统](#七关注角度系统)
- [八、LLM 调用与重试策略](#八llm-调用与重试策略)
- [九、HeuristicAgent 兜底机制](#九heuristicagent-兜底机制)
- [十、角色定义系统（Role Registry）](#十角色定义系统role-registry)
- [十一、Agent 完整生命周期](#十一agent-完整生命周期)
- [十二、设计亮点总结](#十二设计亮点总结)
- [十三、踩过的关键坑](#十三踩过的关键坑)
- [附录：关键文件索引](#附录关键文件索引)

---

## 一、设计目标与核心命题

整个 Agent 系统的核心命题是：

> **让 7 个 AI 在严格信息隔离下，扮演各自的狼人杀角色，展现出不同的人格和推理方式，产生真实可信、有差异化的对局过程。**

这意味着 Agent 不能是"7 个一模一样的 GPT 在说话"，而必须满足：

1. **信息隔离**：每个 Agent 只能看到自己角色应该知道的信息
2. **角色差异化**：不同角色有不同的胜利条件、行动能力和策略
3. **人格差异化**：同一角色由不同人格扮演，会产生不同的发言和行为
4. **防幻觉**：LLM 不能编造不存在的游戏事件
5. **高可用**：LLM API 不稳定时对局不能中断

---

## 二、整体架构

```
┌─────────────────────────────────────────────────────────┐
│                    游戏引擎 WerewolfGame                  │
│                                                         │
│  Phase 推进 → _ask(player, request, action_fn)           │
│    │                                                    │
│    ├─ 1. Visibility.for_player(state, id) → PlayerView │
│    ├─ 2. agent.update(view, request)                   │
│    ├─ 3. agent.talk() / vote() / attack() ...          │
│    ├─ 4. ActionValidator.validate(decision)            │
│    └─ 5. 执行 Decision，记录 DecisionAudit              │
│                                                         │
└─────────────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│                    Agent (Protocol)                       │
│                                                         │
│  ┌─────────────┐  ┌───────────────┐  ┌──────────────┐  │
│  │  LLMAgent   │  │ HeuristicAgent│  │  HumanAgent  │  │
│  │  (主力)      │  │   (兜底)       │  │  (人类玩家)   │  │
│  │             │  │              │  │              │  │
│  │ LLM调用     │  │ 规则引擎      │  │ WebSocket   │  │
│  │ + 人格系统   │  │ + 嫌疑打分    │  │ 等待输入     │  │
│  │ + Prompt工程 │  │ + 角色模板    │  │              │  │
│  └──────┬──────┘  └──────┬───────┘  └──────┬───────┘  │
│         │                │                  │          │
│         │    fallback ──→│                  │          │
│         │   (LLM失败时)   │                  │          │
└─────────┼────────────────┼──────────────────┼──────────┘
          │                │                  │
          ▼                ▼                  ▼
       Decision          Decision          Decision
```

### Agent 协议（Protocol，非 ABC）

```python
class Agent(Protocol):
    def initialize(view: PlayerView, game_setting: dict) -> None: ...
    def update(view: PlayerView, request: str) -> None: ...
    def day_start() -> None: ...
    def talk() -> Decision: ...
    def vote() -> Decision: ...
    def attack() -> Decision: ...
    def divine() -> Decision: ...
    def guard() -> Decision: ...
    def witch_act(victim_id: str) -> list[Decision]: ...
    def shoot() -> Decision: ...
    def boom() -> Decision: ...
    def transfer_badge(candidates: list[str]) -> Decision: ...
    def finish(winner: str) -> None: ...
```

使用 Protocol 而非 ABC 的原因是：不需要继承关系，只要对象满足这个接口就能被引擎调用。这让 HeuristicAgent、LLMAgent、HumanAgent 各自独立实现，互不依赖。

### Agent 工厂

```python
def create_agents(players, agent_config) -> dict[str, Agent]:
    # 根据配置创建不同类型的 Agent：
    #   human_seat  → HumanAgent（该座位是人类玩家）
    #   type="heuristic" → HeuristicAgent（纯规则）
    #   type="llm"  → LLMAgent（LLM + Heuristic fallback）
    #   provider="doubao" → 火山方舟 Doubao-Seed-2.0-pro
    #   provider="deepseek" → DeepSeek v4 Flash
```

---

## 三、信息隔离 —— 架构级安全保障

这是整个系统最底层的设计原则：**Agent 永远接触不到 `GameState`，只能拿到 `PlayerView`**。

```
Visibility.for_player(state, player_id) → PlayerView {
    player_id: str,
    day: int,
    phase: str,
    self_player: dict,        # private_dict() — 自己的完整信息
    players: list[dict],      # 按角色过滤后的其他玩家信息
    public_events: list[dict],# 所有 visibility="public" 的事件
    private_events: list[dict],# visibility="private" 且该玩家在 visible_to 中
    known_wolves: list[dict], # 仅狼阵营可见
    observations: list[str],  # 从 PRIVATE_INFO 事件提取的消息
}
```

### 三层可见性规则

| 查看者 vs 目标 | 看到什么 |
|---|---|
| 自己看自己 | `private_dict()` — 完整信息（角色、阵营、人格） |
| 狼队友看狼队友 | `private_dict()` — 狼人互相认识 |
| 其他所有情况 | `public_dict()` — 仅公开信息（名字、座位号、存活状态） |

这意味着：
- **村民永远不知道谁是预言家**，只能从发言推理
- **狼人互相知道身份**，但不知道具体谁是预言家/女巫/守卫
- **预言家的查验结果**通过 `private_event`（`SEER_CHECK` 类型）只推给预言家本人
- **女巫的用药记录**通过 `private_event`（`WITCH_SAVE`/`WITCH_POISON` 类型）只推给女巫本人

### 设计价值

这不是"靠 Prompt 让 LLM 假装不知道"——这是在**架构层面**物理隔离了信息。即使 LLM 想作弊，它拿到的 `PlayerView` 里根本就没有不该看到的数据。

---

## 四、双层扮演架构（wolfcha 风格）

这是整个 Agent 系统最精妙的设计：**角色（Role）决定"你要赢"，人格（Character）决定"你怎么说话"**。

```
Agent = Role + Character
         │       │
         │       └─ Persona (25 个维度) + PlayerMind (6 个维度)
         │          → 决定说话风格、推理方式、压力反应、桌面表现
         │
         └─ Role (7 个可选角色)
            → 决定胜利条件、行动能力、策略指引
```

### Layer 1: Role（角色层）

来自 `prompts.py` 和 `profiles.py`：

```
每个角色有：
  ├─ ROLE_SYSTEM_PROMPT: 角色定位（你是...你的目标是...）
  ├─ ACTION_STRATEGIES: 每个行动的详细策略（talk/vote/attack/divine/guard/shoot/boom）
  ├─ ROLE_PROFILES: 战术画像（table_goal/speech_style/pressure_style/reveal_policy）
  └─ Playbook: 行动剧本（public_debate/vote_logic/night_logic/reveal_logic）
```

例如预言家：

```
系统提示词:
  "你是狼人杀中的预言家。你的目标是用查验结果引导好人阵营投票，找出所有狼人。"
  "核心策略：合理使用查验能力，在关键轮次跳身份给出查验结果。"

发言策略:
  "如果你有查验结果且值得公开，明确报出查验对象和结果。"
  "如果还没跳身份，先以村民角度给出推理和怀疑对象。"

投票策略:
  "如果有查杀，优先投票查杀目标。"
  "如果没有查杀，推动桌面最不自然的带节奏位出局。"

查验策略:
  "优先查验高影响力位、警长位、主动带节奏位。"
  "避免重复查验已经足够清楚的目标。"
```

### Layer 2: Character（人格层）

来自 `characters.py`，灵感来自 wolfcha 的 `Persona` + `PlayerMind` 双接口设计。

#### Persona（25 个维度）

```python
@dataclass
class Persona:
    # 基本信息
    mbti: str              # "INTJ", "ENFP", "ESTP" ...
    gender: str            # "male" | "female" | "nonbinary"
    age: int               # 19-45
    name: str              # 林思远, 陈小玉, 大壮 ...
    basic_info: str        # 1-2 句背景故事

    # 风格标签
    style_label: str       # "analytical", "aggressive", "observant" ...

    # 说话风格
    vocabulary_style: str  # "学术化" / "大白话" / "诗意散文式" / "极简"
    speech_length_habit: str  # "简洁有力" / "中等偏长" / "短促有力"

    # 推理方式
    reasoning_style: str   # "逻辑链条式" / "直觉快判" / "深层动机分析"
    logic_style: str       # "前置假设+反证排除" / "证据链+时间线核对"

    # 社交行为
    social_habit: str      # "独立分析" / "主动倾听" / "敢带头冲锋"
    humor_style: str       # "dry" / "self_deprecating" / "sarcastic" / "none"

    # 压力应对
    pressure_style: str    # "列出更多证据" / "直接反踩" / "用玩笑化解"
    uncertainty_style: str # "直接承认不确定" / "沉默观察" / "抛几个假设"

    # 狼人伪装（仅当角色是狼时生效）
    wolf_deception_style: str  # "利用数据感制造伪分析" / "伪装成中立好心的观察者"

    # 弱点
    mistake_pattern: str   # "偶尔过度自信忽略情绪线索" / "太冲的情况下容易踩错人"

    # 其他
    voice_rules: list[str] # ["concise", "structured"]
    trigger_topics: list[str]  # ["票型异常", "前后矛盾", "信息差"]
    werewolf_experience: str   # "中级玩家" / "老玩家" / "新手"
```

#### PlayerMind（6 个维度）

```python
@dataclass
class PlayerMind:
    courage: str            # "bold" / "cautious" / "calculated"
    memory_bias: str        # "recent" / "first_impression" / "selective" / "comprehensive"
    suspicion_threshold: str  # "low" / "medium" / "high"
    self_protection: str    # "aggressive" / "passive" / "sacrificial"
    logic_depth: str        # "shallow" / "moderate" / "deep"
    table_presence: str     # "dominant" / "balanced" / "quiet"
```

### 人格池：30+ 个预定义角色

每个角色都有真实的人类职业背景、性格和说话风格：

| 人格 | MBTI | 职业 | 风格标签 | 说话特点 |
|------|------|------|----------|----------|
| 林思远 | INTJ | 数据分析师 | analytical | 用词精准、数据感强、逻辑链条式 |
| 陈小玉 | ENFJ | 小学老师 | persuasive | 口语化、带关怀感、喜欢讲故事 |
| 大壮 | ESTP | 建筑工头 | aggressive | 大白话直球、短促有力、吼就完了 |
| 王雅文 | INFJ | 心理咨询师 | insightful | 文雅细腻、多用比喻、深层动机分析 |
| 赵铁柱 | ISTP | 汽修师傅 | observant | 极简，像修车报告，能一个字绝不用两个字 |
| 苏晓晓 | ESFP | 戏剧学院学生 | expressive | 像在讲故事，有开头高潮结尾 |
| 李默 | ISTJ | 会计 | meticulous | 正式严谨，像在做审计报告 |
| 周星野 | ENTP | 脱口秀演员 | provocative | 幽默辛辣，夹杂流行梗 |
| 白晓晴 | ENFP | 自媒体主播 | energetic | 口语化节奏感强，自带 BGM |
| 顾景行 | INTP | 算法工程师 | academic | 技术词汇，喜欢用类比解释复杂关系 |
| 雷昊 | ESTJ | 刑警 | interrogator | 短句命令式语气，审讯式提问 |
| 卓砚 | ESTJ | 媒体总编 | anchor | 新闻式表达，权威感强 |

完整池有 30+ 个角色，包含了各种 MBTI 类型、职业背景和说话风格的组合。

### 8 种思维模板（PlayerMind 池）

```python
MIND_POOL = [
    # 激进直觉型
    {"courage":"bold", "memory_bias":"first_impression", "suspicion_threshold":"low",
     "self_protection":"aggressive", "logic_depth":"shallow", "table_presence":"dominant"},
    # 深度分析型
    {"courage":"calculated", "memory_bias":"comprehensive", "suspicion_threshold":"medium",
     "self_protection":"passive", "logic_depth":"deep", "table_presence":"balanced"},
    # 谨慎保守型
    {"courage":"cautious", "memory_bias":"recent", "suspicion_threshold":"high",
     "self_protection":"sacrificial", "logic_depth":"moderate", "table_presence":"quiet"},
    # ... 共 8 种
]
```

### 组合空间

每个 Agent = 随机抽取 1 个 Persona × 1 个 PlayerMind × 引擎分配的 1 个 Role。

**30+ × 8 × 7 = 1680+ 种可能的玩家画像**。每局随机抽取，保证每次对局都有不同的"人物组合"。

---

## 五、Prompt 工程详解

### 5.1 发言 Prompt（talk）—— 最复杂的 Prompt

发言采用了 **"System Prompt 分片 + 动态组装"** 的设计，灵感来自 wolfcha 的多层 prompt 结构：

```
┌────────────────────────────────────────────────────┐
│              System Prompt（分片组装）               │
├────────────────────────────────────────────────────┤
│                                                    │
│  Part 1 [cacheable]: 身份 + 胜利条件 + 角色策略      │
│    "你是 3号「林思远」，身份: 预言家。"                │
│    "【你的阵营】预言家。放逐所有狼人时好人胜利。"       │
│    "【你的玩法】如果你有查验结果且值得公开..."          │
│                                                    │
│  Part 2 [cacheable]: 角色设定（来自 Persona）         │
│    "你是林思远，28岁，男。数据分析师..."               │
│    "说话风格：用词精准、数据感强..."                   │
│                                                    │
│  Part 3 [non-cacheable]: 任务描述（按阶段动态变化）    │
│    自由发言: "从上一个发言者的观点切入..."             │
│    警徽竞选: "你不是来点评别人的，你是来争取警徽的"     │
│    遗言:     "交代身份、留下信息、点出最可疑的人"       │
│                                                    │
│  Part 4 [cacheable]: 行为特征 <hidden_traits>        │
│    "发言特点：简洁有力..."                            │
│    "压力下的反应：被质疑时列出更多证据..."              │
│    "这轮可以从一个具体的观察切入" ← 每轮随机变化        │
│                                                    │
│  Part 5 [cacheable]: 底线规则 + 输出格式              │
│    "只基于本局实际信息发言，严禁编造"                   │
│    "绝对不要说「请X号发言」「过」「下一位」"             │
│    "返回 JSON 字符串数组，每个元素是一条消息气泡"       │
│                                                    │
├────────────────────────────────────────────────────┤
│              User Prompt                            │
├────────────────────────────────────────────────────┤
│                                                    │
│  【当前局势】第2天 白天 自由发言                       │
│    存活玩家: 1号 白晓晴, 3号 林思远, 5号 大壮...      │
│    出局玩家: 4号 陈小玉 (狼人杀死)                    │
│    警长: 1号                                        │
│                                                    │
│  【规则提醒】阶段顺序 + 信息可用性时间线                │
│    "第一夜刀口是随机的，第一天信息量极少"               │
│                                                    │
│  【历史】第1天发言摘要 + 投票记录                      │
│                                                    │
│  【查验记录】第1夜: 5号 大壮 - 狼人                   │
│                                                    │
│  【本日讨论记录】已发言者的内容摘要（最后10条）          │
│                                                    │
│  【你本日已说过的话】防止重复发言                      │
│                                                    │
│  【发言顺序】第3/5个发言                              │
│    已发言: 1号白晓晴, 2号赵铁柱                       │
│    上一个发言的是2号赵铁柱，他说：「...」               │
│    "你可以从回应他的观点开始——认同、质疑、补充都可以"    │
│                                                    │
│  <focus_angle>  ← 动态关注角度                       │
│    你被1号白晓晴点名提到了，可以考虑回应                 │
│    可以回应一下警长的方向                              │
│  </focus_angle>                                     │
│                                                    │
└────────────────────────────────────────────────────┘
```

**关键设计细节**：

1. **System Prompt 分片标记 cacheable**：身份、人格、规则等不会变的部分标记为 `cacheable: True`；任务描述（随 phase 变化）标记为 `cacheable: False`。这对于支持 LLM prompt caching 的 API 能显著降低延迟和成本。

2. **发言顺序感知**：`_build_speak_order_hint()` 统计当日已发言者和未发言者，给出"你是第 M/N 个发言"的定位，并**把上一个发言者的内容截取给当前发言者**，引导 Agent 回应而非自言自语。

3. **JSON 数组输出**：`["第一段发言", "第二段发言"]`，每段渲染为独立气泡，实现自然的多段发言。

4. **每轮随机 mood**：`["这轮可以轻松一点", "这轮直接说重点", "这轮先回应前一个人再表态", ...]`，防止同一人格每轮说话节奏完全一样。

### 5.2 行动决策 Prompt（vote/attack/divine/guard 等）

行动决策采用完全不同结构的**分层信息块** Prompt：

```
=== 当前状态 ===
你是 @3号:林思远，扮演 Seer
第2天 / DAY_VOTE阶段
存活玩家：@1号:白晓晴, @3号:林思远, @5号:大壮...
已死亡：@4号:陈小玉

=== 角色目标 ===
（来自 ROLE_PROFILES 的 table_goal + speech_style）

=== 已发生事实速查（这是你能信任的全部桌面信息） ===  ← 防幻觉核心！
  · 第1天 系统：1号白晓晴 当选警长
  · 第1天 4号陈小玉 出局（原因：狼人杀死）
  · 第1天投票：白晓晴→大壮；林思远→陈小玉；...
  · 第1天 林思远：我觉得5号发言有点问题...
（去重 + 按天分组 + 截断，LLM 必须把这里当唯一事实来源）

=== 今日发言记录 ===
  1号白晓晴：我昨晚查了5号，是狼人...
  2号赵铁柱：跟1号走...

=== 发言顺序 ===
（同 talk 的发言顺序感知）

=== 本轮关注角度 ===
  你可以回应1号的发言
  昨天白晓晴和你投了同一个目标

=== 最近公开事件原始日志 ===
（最近 20 条 raw events，保留完整上下文）

=== 你的私有信息 ===
（预言家查验记录 / 女巫药水状态 / 狼队友列表）

=== 行动策略 ===
投票策略：如果有查杀，优先投票查杀目标...

=== 当前指令 ===
Choose exactly one vote target from the options.
可选择的玩家：@1号:白晓晴, @3号:林思远, @5号:大壮...

=== 反幻觉硬性纪律 ===
- 严禁编造未在「事实速查」或「最近公开事件」里出现的内容
- 不要谈论「投票阶段还没发生」的票
- 提到任何其他玩家时，必须写成 @N号:名字 的形式
- 不要假装自己是其他角色
- 发言不要超过 3 句话

请只输出 JSON：{"reasoning": "你的思考过程（1-2句）", "target": "玩家名字"}
```

---

## 六、防幻觉多层防御体系

这是从实际踩坑中演化出来的完整防御体系：

| 层级 | 机制 | 解决的问题 | 对应 Issue |
|------|------|------------|------------|
| **L1: 事实速查** | `_build_fact_sheet()` 去重+按天分组+截断到最近 10 条发言、最近 2 天投票，标记为"唯一事实来源" | LLM 编造"X 投了 Y""我救了 Z"等不存在的游戏事件 | C2 |
| **L2: 反幻觉纪律** | Prompt 末尾 5 条硬约束：禁止编造、禁止跨阶段引用、强制 @N号:名字 格式、禁止冒充角色、禁止复述设定 | 全面的行为边界约束 | C2 |
| **L3: System/User 边界** | 自身人设放 system prompt（"仅描述你自己"），不放进 user prompt | LLM 误解"自己的角色设定"为"对全场玩家的观察"（"陈小玉话不多但逻辑完整"） | C2 |
| **L4: Phase 动态切换** | 统计当日 CHAT_MESSAGE 数，0 时切到"禁止评价/怀疑/暗示"的硬约束 | 第一天没信息时 LLM 凭印象编造指控（"大壮看起来就很可疑"） | C3 |
| **L5: 遗言独立分支** | `is_last_words` 分支：禁止"请X号发言""下一位""过"等传话筒表述 | 狼人遗言写"接下来有请@1号:白晓晴发言" | C4 |
| **L6: 信息时间线提示** | Prompt 中加入"第一夜刀口随机""各阶段信息可用性"规则说明 | LLM 不理解"第一天白天不应该有强指控" | C3 |
| **L7: 角色私有信息隔离** | 预言家验人/女巫用药/狼队友列表通过 private_events 传递，非对应角色根本看不到 | LLM 编造不属于自己角色的信息 | 架构级 |
| **L8: Heuristic fallback** | LLM 全部失败后自动切规则 Agent | API 故障时对局不中断 | C1 |

### L4 详解：Phase 动态切换

```python
def talk(self) -> Decision:
    today_chat_count = sum(
        1 for e in view.public_events
        if e.get("day") == view.day
        and e.get("type") == "CHAT_MESSAGE"
        and e.get("phase") == view.phase
    )
    is_first_speaker = today_chat_count == 0
    # is_first_speaker 会传递到 prompt 构建链中，
    # 影响 "当前处境" 和 "底线规则" 的内容
```

当 `is_first_speaker=True` 时，Prompt 会加入额外约束：
- "你是第一个发言，没有人可以参考"
- "信息不足是正常的，可以说「信息不足，先听听大家发言」"
- 移除"必须指出嫌疑对象"的要求

---

## 七、关注角度系统

`_build_perspective_hints()` 是让 7 个 Agent **说不同话**的关键机制。每次发言前，动态分析游戏状态，给每个 Agent 生成独特的关注角度：

```python
def _build_perspective_hints(self) -> str:
    hints = []

    # 1. 被点名回应（最高优先级）
    #    扫描当日所有发言，检查是否包含 "@N号" 引用

    # 2. 座位相邻死者
    #    检测自己的座位号是否与死亡玩家相邻（环形）

    # 3. 警长关系（奇偶日交替变化）
    #    奇数日：回应警长方向
    #    偶数日：质疑警长方向

    # 4. 投票一致性（day 2+ 生效）
    #    分析昨日投票，找到跟自己投了同一目标的人

    # 5. 发言位置感知
    #    第一个发言 vs 靠后发言 → 不同的提示

    return 最多选 2 条 → 通过 <focus_angle> XML 标签注入
```

**具体示例**：

```
Agent A（被点名了）:
  <focus_angle>
  - 你被1号白晓晴点名提到了，可以考虑回应
  - 你和出局的4号陈小玉座位相邻，可以从这个角度聊一句
  </focus_angle>

Agent B（警长，第一天）:
  <focus_angle>
  - 你是警长，你的发言会影响别人，可以自然给出你的方向
  - 你是第一个发言，没有人可以参考，可以先抛出一个起手判断
  </focus_angle>

Agent C（跟票者，第二天）:
  <focus_angle>
  - 昨天白晓晴和你投了同一个目标，可以想想这件事要不要提
  - 你已经听了大部分人的发言，可以挑你最在意的一点回应
  </focus_angle>
```

这保证了：同一轮发言中，每个 Agent 关注的东西不同，不会出现"7 个人都在说同一件事"的机械感。

---

## 八、LLM 调用与重试策略

### 8.1 双 Provider 支持

```python
# backend/llm/__init__.py
def create_client(provider, model):
    if provider == "doubao":
        # 火山方舟 Ark API
        # Model: Doubao-Seed-2.0-pro
        # Base URL: https://ark.cn-beijing.volces.com/api/v3
    elif provider == "deepseek":
        # DeepSeek API
        # Model: deepseek-v4-flash（内置 Chain-of-Thought）
        # Base URL: https://api.deepseek.com
    else:
        # _UnavailableLLMClient → 立即抛 RuntimeError → 强制 fallback
```

### 8.2 发言的重试策略（`_ask_talk_wolfcha`）

```
第 1 次尝试：
  temperature = speech_temperature (默认 1.1，高随机性)
  max_tokens = 1536
  输出解析：JSON 字符串数组 ["msg1", "msg2"]
  → 成功 → 用 \n\n 连接，返回多段发言
  → 失败 → 进入第 2 次

第 2 次尝试：
  temperature = 0.9（稍降随机性）
  max_tokens = 1536
  追加提示："请输出JSON字符串数组。"
  → 成功 → 返回
  → 失败 → 进入第 3 次

第 3 次尝试（raw text fallback）：
  取第 1 次的原始输出，清洗掉前缀/引号/代码块
  → 文本长度 ≥ 2 字符 → 当纯文本发言使用
  → 失败 → 使用 HeuristicAgent fallback
```

### 8.3 行动决策的重试策略（`_ask_json_inner`）

```
第 1 次尝试：
  temperature = base_temp (默认 0.4，低随机性，追求准确)
  max_tokens = 640

第 2 次尝试：
  temperature = 0.2（进一步降低）
  max_tokens = 960（1.5x 放大）

第 3 次尝试：
  temperature = 0.1（几乎确定性）
  max_tokens = 1600（2.5x 放大）
  追加强制性指令："只输出 JSON，不要额外解释"

全部失败 → HeuristicAgent fallback
```

### 8.4 JSON 解析（`_coerce_json`）

```python
def _coerce_json(text):
    # 1. 直接 json.loads(text)
    # 2. 提取 text 中第一个 { 到最后一个 } 之间的内容 → json.loads
    # 3. 返回 None（触发 fallback）
```

### 8.5 Timeout 设置的教训

原始设置：`timeout = 12s`
问题：DeepSeek-v4-flash 内置 Chain-of-Thought，reasoning 消耗 5-8s，content 生成再消耗 3-5s，总计 8-13s → 大量超时 → fallback 率 50-65%

最终设置：`timeout = 120s`
理由：两次 LLM 调用（第 1 次失败 + 第 2 次重试）各需要 8-20s 的完整推理链路，120s 提供足够余量。引擎的 snapshot drain 在独立线程中并行运行，UI 不会因为等待 LLM 而卡住。

---

## 九、HeuristicAgent 兜底机制

```
每个 LLMAgent 构造时：
  self.fallback = HeuristicAgent(player_id, seed=seed, character=character)

每次行动的标准流程：
  ┌──────────────────────────────────────────┐
  │ 1. fallback = self.fallback.attack()     │  ← 预先生成备用决策
  │ 2. LLM 调用（最多 3 次重试）               │
  │ 3. 成功 → 返回 LLM 决策                   │
  │ 4. 失败 → 返回 fallback 决策              │
  │    （meta 中标记 source="fallback"）       │
  └──────────────────────────────────────────┘
```

### HeuristicAgent 的核心逻辑

```
1. 嫌疑度打分系统：
   - 投票记录分析：投了好人 → 加分；投了狼人 → 减分
   - 发言模式分析：空泛发言 → 加分；具体推理 → 减分
   - 死亡关联分析：邻近死者 → 加分

2. 已知信息追踪：
   - 预言家查验结果 → known_wolves / known_good
   - 狼队友列表 → 投票时保护队友

3. 角色行为模板：
   - 每个角色每种行动有预定义的规则模板
   - 人格参数影响模板选择和参数

4. 发言构建：
   - 根据信息量（none/limited/moderate/strong）选择模板
   - 根据人格风格标签调整措辞
```

### 效果

修复前（timeout=12s, max_tokens=320）：
- LLM 调用成功率：35-50%
- Fallback 率：50-65%
- 对局质量崩塌

修复后（timeout=120s, max_tokens=800+）：
- LLM 调用成功率：100%
- 每个调用耗时：3.6-4.1s
- Fallback 率：0%（仅 API 完全不可用时触发）

---

## 十、角色定义系统（Role Registry）

### 问题：散落在 7 个文件中的角色定义

之前添加一个新角色需要手动修改 7 个文件：
1. `engine/models.py` — Role 枚举
2. `engine/rules.py` — 角色配置
3. `engine/actions.py` — 行动权限
4. `agents/playbooks.py` — 行动剧本
5. `agents/profiles.py` — 角色画像
6. `agents/prompts.py` — 提示词
7. `frontend/types/index.ts` — 前端类型

漏改一处 = KeyError 500。

### 解决方案：Role Registry

```
backend/engine/roles/
  __init__.py      → 导出 ROLE_REGISTRY
  registry.py      → RoleSpec dataclass + register_role() API
  basic.py         → Villager
  gods.py          → Seer, Witch, Hunter, Guard
  wolves.py        → Werewolf, WhiteWolfKing
  wolfcha.py       → Idiot
  extensions.py    → Cupid, BigBadWolf, WolfCub, WolfKing, Knight, Elder
                     (playable=False，模板预留)
  README.md        → 使用说明
```

**RoleSpec 数据结构**：

```python
@dataclass
class RoleSpec:
    role: Role           # 枚举值
    zh_name: str         # 中文显示名
    en_name: str         # 英文显示名
    is_god: bool         # 是否为神职
    wakes_up_at_night: bool  # 是否有夜晚行动
    pack: str            # 所属包名
    playable: bool       # 是否可玩（False=模板预留，不进入自动配置）
    tags: list[str]      # 标签
```

**Import-time 校验**：

```python
# engine/rules.py
for config in WOLFCHA_ROLE_CONFIGS.values():
    for role in config:
        spec = ROLE_REGISTRY.get(role)
        if spec is None or not spec.playable:
            raise RuntimeError(f"Role {role} is not playable!")
# → 漏配立即在 import 时爆炸，而非运行时 KeyError
```

**LLM Agent 的兜底防护**：

```python
# llm_agent.py
profile = ROLE_PROFILES.get(self.role, ROLE_PROFILES[Role.VILLAGER])
# → 即使新角色没配 profile，也不会 KeyError，而是降级到村民
```

---

## 十一、Agent 完整生命周期

```
┌─────────────────────────────────────────────────────────┐
│                    GAME START                            │
│                                                         │
│  Factory: create_agents(players, config)                │
│    ├─ 读取 agent_type: "llm" | "heuristic"              │
│    ├─ 读取 provider: "doubao" | "deepseek"              │
│    ├─ 读取 human_seat（如果有人类玩家）                    │
│    ├─ 创建角色-人格映射表（build_character_roster）        │
│    │    └─ 每个 player 分配 1 Persona + 1 PlayerMind     │
│    ├─ LLMAgent(player_id, seed, provider, model,        │
│    │            temperature, speech_temperature,         │
│    │            character)                               │
│    │    └─ 内部: self.fallback = HeuristicAgent(...)    │
│    └─ 返回 dict[player_id, Agent]                       │
│                                                         │
├─────────────────────────────────────────────────────────┤
│                    INITIALIZATION                        │
│                                                         │
│  engine: agent.initialize(view, game_setting)           │
│    LLMAgent:                                            │
│      ├─ self.view = view                                │
│      ├─ self.memory = [                                 │
│      │     "我是林思远，扮演预言家。",                     │
│      │     build_role_brief(Role.SEER)  ← 角色剧本       │
│      │   ]                                              │
│      └─ self.fallback.initialize(view, game_setting)    │
│    HeuristicAgent:                                      │
│      ├─ 存储 view                                       │
│      ├─ 初始化嫌疑度打分表                                │
│      └─ 识别狼队友（如果是狼）                             │
│                                                         │
├─────────────────────────────────────────────────────────┤
│                    EACH PHASE                            │
│                                                         │
│  engine: agent.update(view, request)                    │
│    LLMAgent:                                            │
│      ├─ self.view = view                                │
│      ├─ self.memory.append(f"{request} day=... phase=.")│
│      └─ self.fallback.update(view, request)             │
│                                                         │
│  engine: agent.day_start()                              │
│    └─ 重置每日状态（嫌疑增量等）                           │
│                                                         │
│  ┌─ 夜晚阶段 ─────────────────────────────────────┐     │
│  │ agent.guard()                                   │     │
│  │   → _target_action("guard", fallback, ...)     │     │
│  │   → 分层信息块 Prompt                            │     │
│  │   → LLM 调用（3 次重试）                         │     │
│  │   → Decision(target_id, reasoning)             │     │
│  │                                                 │     │
│  │ agent.attack()  (狼人)                          │     │
│  │ agent.divine()  (预言家)                        │     │
│  │ agent.witch_act(victim_id)  (女巫，可多决策)     │     │
│  └────────────────────────────────────────────────┘     │
│                                                         │
│  ┌─ 白天阶段 ─────────────────────────────────────┐     │
│  │ agent.talk()                                    │     │
│  │   → Wolfcha 式 System Prompt 分片组装            │     │
│  │   → User Prompt（上下文 + 发言记录 + 关注角度）    │     │
│  │   → LLM 调用（3 次重试，JSON 数组解析）           │     │
│  │   → Decision(speech, metadata.segments)         │     │
│  │                                                 │     │
│  │ agent.vote()                                    │     │
│  │   → 分层信息块 Prompt                            │     │
│  │   → Decision(target_id, reasoning)             │     │
│  └────────────────────────────────────────────────┘     │
│                                                         │
│  ┌─ 特殊阶段 ─────────────────────────────────────┐     │
│  │ agent.shoot()  (猎人死亡)                        │     │
│  │ agent.boom()   (白狼王自爆)                      │     │
│  │ agent.transfer_badge(candidates)  (警长传位)     │     │
│  └────────────────────────────────────────────────┘     │
│                                                         │
├─────────────────────────────────────────────────────────┤
│                    GAME END                              │
│                                                         │
│  engine: agent.finish(winner)                           │
│    LLMAgent:                                            │
│      ├─ self.winner = winner                            │
│      ├─ self.memory.append(f"游戏结束，{winner}胜利")     │
│      └─ self.fallback.finish(winner)                    │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## 十二、设计亮点总结

| 亮点 | 说明 | 技术价值 |
|------|------|----------|
| **信息隔离是架构级的** | Agent 通过 `Visibility.for_player()` 拿到 `PlayerView`，永远不接触 `GameState` | 不可能作弊，不是"靠 Prompt 假装不知道" |
| **双层扮演** | Role 决定目标策略，Character 决定说话方式，两者独立抽取 | 1680 种玩家画像，每局对局人物组合不同 |
| **防幻觉多层防御** | 8 层防御：事实速查 → 反幻觉纪律 → System/User 边界 → Phase 动态切换 → 遗言分支 → 时间线提示 → 私有信息隔离 → Fallback | 从"LLM 经常编造"到"基本可信" |
| **动态关注角度** | 每个 Agent 每轮发言前获得独特视角（被点名/邻座死者/警长关系/投票一致性） | 7 个人说不同的话，不会同质化 |
| **Prompt 分片 + 缓存标记** | System prompt 标记 cacheable/non-cacheable | 支持 LLM prompt caching，降低成本延迟 |
| **3 次渐进式重试** | 温度逐步降低 + token 逐步放大 + 最终 raw text fallback | LLM 输出不稳定时也能产出可用结果 |
| **Heuristic 兜底** | 每次行动预先生成备用决策 | API 完全故障时对局不中断 |
| **发言顺序感知** | 统计已发言/未发言者，传递上一个发言者内容 | Agent 学会"回应"而非"自言自语" |
| **Role Registry** | Single source of truth + import-time 校验 | 加新角色不会漏配导致 KeyError |
| **决策审计** | 每次 LLM 调用记录 DecisionAudit（原始输出、耗时、token 数、是否 fallback） | 完整的可追溯性，支持复盘分析 |

---

## 十三、踩过的关键坑

这些是 DEVELOPMENT_ISSUES.md §C 中记录的 Agent 相关核心教训：

### 问题 C1：LLM fallback 率 50-65%（最严重）

- **根因**：两层叠加
  1. `max_tokens=320`，DeepSeek-v4-flash 内置 reasoning 吃掉 178 tokens，剩 142 tokens 给 content → JSON 被截断
  2. `timeout=12s`，reasoning 模式常超 10s → 直接超时
- **修复**：`max_tokens` 抬到 800，`timeout` 从 12s → 60s → 120s，加 3 次重试
- **效果**：fallback 率 50-65% → 0%

### 问题 C2：LLM 输出场外知识

- **现象**：LLM 说"陈小玉话不多但逻辑完整""大壮看起来稳"——这些并非来自实际游戏事件
- **根因**：把自身人设描述放在 user prompt 的"你的人设"段，LLM 误解成对全场玩家的观察
- **修复**：人设搬到 system prompt + 标注"仅描述你自己" + 追加 5 条防幻觉硬约束

### 问题 C3：开局即互喷

- **现象**：第一天没人发言时 Agent 已经开始指控他人
- **根因**：talk prompt 强制要求"指出至少 1 名嫌疑 + 1 名信任"，day 1 没信息只能编造
- **修复**：统计当日发言数，0 时切换到"禁止评价/怀疑/暗示"的硬约束

### 问题 C4：遗言传话筒

- **现象**：狼人遗言写"接下来有请@1号:白晓晴发言"
- **根因**：遗言复用普通发言 prompt，没区分场景
- **修复**：`talk()` 加 `is_last_words` 分支，禁止传话筒

### 问题 C5：Timeout 设置不当

- **教训**：reasoning 模型的内置思考 token 消耗必须算进预算；timeout 不要硬编码，要可配置

---

## 附录：关键文件索引

| 文件 | 行数 | 说明 |
|------|------|------|
| `backend/agents/base.py` | ~80 | Agent 协议定义（Protocol） |
| `backend/agents/llm_agent.py` | ~1523 | LLM Agent 完整实现（核心文件） |
| `backend/agents/characters.py` | ~1062 | 人格系统：Persona + PlayerMind + 30+ 角色池 |
| `backend/agents/prompts.py` | ~254 | 角色提示词 + 行动策略 + 输出格式 |
| `backend/agents/profiles.py` | ~200 | 角色战术画像（ROLE_PROFILES） |
| `backend/agents/playbooks.py` | ~300 | 角色行动剧本（build_role_brief） |
| `backend/agents/heuristic.py` | ~600 | 启发式 Agent（嫌疑打分 + 模板发言） |
| `backend/agents/factory.py` | ~80 | Agent 工厂函数 |
| `backend/agents/human_agent.py` | ~100 | 人类玩家 Agent（WebSocket 等待输入） |
| `backend/engine/visibility.py` | ~80 | 信息隔离层（Visibility.for_player） |
| `backend/engine/roles/registry.py` | ~80 | 角色注册表（RoleSpec + ROLE_REGISTRY） |
| `backend/llm/__init__.py` | ~60 | LLM 客户端工厂（doubao/deepseek） |
| `backend/llm/deepseek.py` | ~200 | DeepSeek HTTP 客户端（同步+异步） |
| `docs/DEVELOPMENT_ISSUES.md` | ~466 | 开发问题追踪（§C = Agent 相关问题） |

---

*本文档基于 AI Werewolf 项目实际代码、git 历史和开发记录生成。所有技术细节可追溯至具体文件和 commit。*