# AI Werewolf 全量审计总览

> 审计日期: 2026-05-28 | 最后更新: 2026-06-01 | 审计范围: 全项目 | 审计方式: 只读 | 审计者: Claude (wxhfy 授权)

---

## 1. 项目如何运行

```bash
# 后端
uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload

# 前端
cd frontend && npm install --legacy-peer-deps && npm run dev
# 打开 http://localhost:3001

# 一局游戏 (启发式)
python -m backend.run_demo --seed 7

# 一局游戏 (LLM, 需要 DOUBAO_API_KEY)
curl -X POST "http://localhost:8000/api/rooms?name=Demo&seed=7&player_count=7&agent_type=llm"
curl -X POST "http://localhost:8000/api/rooms/<room_id>/games"
```

**⚠️ README 引用的 `make` 命令不可用 (Makefile 不存在)**。

---

## 2. 游戏引擎完成度: 85%

- ✅ 7~12 人板子完整流程 (夜晚→白天→胜负)
- ✅ 8 个可玩角色 (Werewolf/WhiteWolfKing/Seer/Witch/Guard/Hunter/Villager/Idiot)
- ✅ 警长系统 (竞选+1.5票权重)
- ✅ PK 加赛 (平票→加赛发言→再投票)
- ✅ 白狼王自爆 (打断白天发言)
- ✅ 猎人开枪 (死亡触发，毒杀除外)
- ⚠️ 6 个模板角色未接入引擎 (Cupid/BigBadWolf/WolfCub/WolfKing/Knight/Elder)

---

## 3. Agent 三层结构真实存在吗？

| 层 | 状态 | 证据 |
|----|------|------|
| **Persona** (30+人物, MBTI+背景) | ✅ **IMPLEMENTED** | 完整进入 Prompt (system_prompt 全文注入) |
| **Role** (8 角色独立 Prompt) | ✅ **IMPLEMENTED** | ROLE_SYSTEM_PROMPTS + ACTION_STRATEGIES + ACTION_PLAYBOOKS |
| **Strategy** | ⚠️ **HALF** | strategy_bias + 检索知识 能影响行为, 但 **strategy_id 不存在** |

**结论**: Agent = Persona × Role × (strategy_bias) — 缺 strategy_id 追踪。

---

## 4. Prompt 如何拼接

### 发言路径 (Talk)
```
System: 身份 + 胜利条件 + Persona(全字段) + Behavior(xml) + Task + Bias + Guidelines
User:   GameContext + Stance + PersonalityDecision + TodayTranscript + SelfSpeech +
        PhaseHint + StyleGuardrails + RepeatGuardrails + SpeakOrderHint +
        Examples + RetrievedLessons + Bias + EndInstruction
→ LLM → 自由文本发言
```

### 行动路径 (Vote/Attack/Divine/Guard/Shoot)
```
System: RolePrompt + Character + CommunicationProfile(xml) + PlayerMind(xml) + Constraints + Bias
User:   State + Goal + Facts + Speeches + Events + PrivateInfo + Strategy + Bias +
        Retrieved + Instruction + AntiHallucination + Format(JSON)
→ LLM → JSON → parsed Decision
```

完整证据: `docs/prompt_composition_audit.md`

---

## 5. 各角色实现情况

| 角色 | 独立 Prompt | 引擎逻辑 | 私有信息 | 状态 |
|------|-----------|---------|---------|------|
| Werewolf | ✅ | ✅ 狼队讨论投票 | ✅ 狼队友+讨论 | COMPLETE |
| WhiteWolfKing | ✅ | ✅ 自爆打断 | ✅ 狼队友 | COMPLETE |
| Seer | ✅ | ✅ 查验 | ✅ 查验历史 | COMPLETE |
| Witch | ✅ | ✅ 救/毒/跳过 | ✅ 被刀目标+药状态 | COMPLETE |
| Guard | ✅ | ✅ 不能连守同人 | ✅ 上次守护目标 | COMPLETE |
| Hunter | ✅ | ✅ 死亡开枪 | ✅ 开枪状态 | COMPLETE |
| Villager | ✅ | 无夜逻 | 仅公开信息 | COMPLETE |
| Idiot | ✅ | ✅ 首次放逐存活 | 无 | COMPLETE |

---

## 6. Strategy 层是否真实接入？

| 机制 | 状态 | 影响 |
|------|------|------|
| `strategy_bias` dict | ✅ IMPLEMENTED | 进入 Prompt，影响 LLM 行为 |
| `RetrievedStrategyLesson` (DB检索) | ✅ IMPLEMENTED | 进入 Prompt |
| `strategy_library.yaml` (~200条) | ❌ CONFIG_ONLY | 未被代码使用 |
| `RoleStrategyCard` (Track C DB) | ⚠️ INDIRECT | 通过检索间接使用 |
| **`strategy_id`** | ❌ NOT_FOUND | **不存在!** |

**结论**: 策略偏差机制存在但无 ID 追踪，无法做三层测评。

---

## 7. B 方向完整实现情况

| 版本 | 核心能力 | 状态 |
|------|---------|------|
| V1 | Rule-based 整局评分 | ✅ |
| V2 | PreAction/OutcomeImpact 分离, 0后验污染 | ✅ |
| V3 | 46特征, 中文发言分析, 怀疑矩阵 | ✅ |
| V4 | 难负样本+反事实对+per-role-action LR | ✅ |
| V5 | 数据归一化+GroupKFold+6因子置信度 | ✅ |
| V6 | AI代人工review+难负样本重平衡 | ✅ |
| V7 | 私有上下文感知评分 (Witch/Seer) | ✅ |

**Gate**: PASS_WITH_LIMITATIONS (8/12 PASS, 4 LOW_CONF)
**关键指标**: PaW=0.877, 0后验污染, 0 visibility violations

---

## 8. 评分系统可信度

| 维度 | 评估 |
|------|------|
| 后验污染 | ✅ 0 violations (V2起) |
| 信息泄露 | ✅ 0 visibility violations (V7确认) |
| 跨角色可比 | ❌ NOT VALID (by design) |
| 概率校准 | ❌ RANKING ONLY (ECE=0.166) |
| 4个 LOW_CONF role-actions | ⚠️ 样本不足 |
| Speech 验证 | ❌ 0 labeled samples |
| 标签质量 | ⚠️ AI代标, 未人工验证 |

---

## 9. 当前能否做 Persona × Role × Strategy 测评？

| 测评类型 | 可行性 | 当前实现 |
|----------|--------|---------|
| Persona × Role | ✅ YES | MBTI Dashboard v7 |
| Persona × Role × Strategy | ❌ NO | strategy_id 不存在 |

---

## 10. 当前最应该做的下一步

### 立即 (本周)
1. **补齐 `strategy_id`** — 定义 + 注入 + 记录 (Part 5 §5.5)
2. **标注 ≥100 speech quality samples** — 验证或降级 speech scoring
3. **创建 Makefile + 更新 requirements.txt**

### 短期 (本月)
4. **增加 Witch Save / Seer Release bad label 标注** (≥10 each)
5. **人工验证 AI 标注一致性** (抽样 50-100 条)
6. **确认单局复盘 HTML 使用 V7 scores**

### 中期 (1-2月)
7. **统一 B 评分管道** (单入口脚本)
8. **导入 strategy_library.yaml 到 DB**
9. **Persona × Role × Strategy 三层正式评测**
10. **大规模对局 (500+ games)**

---

## 审计文档索引

| Part | 文档 | 核心发现 |
|------|------|---------|
| 0 | `docs/project_runtime_audit.md` | Makefile 不存在, requirements.txt 不完整 |
| 1 | `docs/project_structure_audit.md` | 53个脚本碎片化, 29个后端文件组织结构 |
| 2 | `docs/game_engine_flow_audit.md` | 完整 Mermaid 状态机, 信息隔离严格 |
| 3 | `docs/agent_architecture_audit.md` | Persona+Role 完整进入 Prompt, Strategy 半存在 |
| 4 | `docs/role_implementation_audit.md` | 8角色全部有独立逻辑+Prompt |
| 5 | `docs/strategy_layer_audit.md` | strategy_id 不存在, 策略库未被代码使用 |
| 6 | `docs/prompt_composition_audit.md` | 完整 Prompt 示例 (4角色×多场景) |
| 7 | `docs/observability_audit.md` | Final Prompt 未记录, evidence 不可点击 |
| 8 | `docs/track_b_implementation_audit.md` | V1→V7 完整实现, Gate PASS_WITH_LIMITATIONS |
| 9 | `docs/persona_role_strategy_eval_readiness.md` | 只支持 Persona×Role, 缺 strategy_id |
| 10 | `docs/project_risk_and_next_steps.md` | 6个P0, 6个P1, 6个P2 + 路线图 |
