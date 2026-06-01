# AI Werewolf 项目状态速览

> 更新时间：2026-06-01

---

## 📊 整体进度

| Track | 状态 | 完成度 | 说明 |
|-------|------|--------|------|
| **A** 基础对局 | ✅ 完成 | 100% | 7-12人板子、完整流程、三类Agent |
| **B** 评测复盘 | ✅ 完成 | 100% | 多维评分、Reviewer Agent、HTML报告 |
| **C** 自进化 | ✅ 完成 | 100% | 策略知识库、进化循环、A/B验证 |

---

## 🎮 核心功能

### 对局引擎
- **板子支持**: 7-12人（默认7人：2狼+预言家+女巫+猎人+守卫+村民）
- **角色**: 狼人、白狼王、预言家、女巫、猎人、守卫、村民、白痴
- **完整流程**: 夜晚→天亮→警徽竞选→发言→投票→遗言→结算

### Agent 类型
| 类型 | 说明 | 用途 |
|------|------|------|
| **LLMAgent** | 调用 DeepSeek/豆包 API | 主力 Agent |
| **HeuristicAgent** | 纯离线启发式 | Fallback + 测试 |
| **HumanAgent** | 接收人类输入 | 人机混战 |

### 人设系统
- **Persona**: MBTI、年龄、背景、说话风格、压力反应
- **PlayerMind**: 勇气、记忆偏好、桌面存在感
- **角色策略卡**: 每个角色×Persona 独立策略 profile

---

## 🔧 技术栈

| 层 | 技术 |
|----|------|
| **后端** | Python 3.12 + FastAPI + WebSocket |
| **前端** | Next.js 15 + React 19 + Tailwind CSS |
| **数据库** | PostgreSQL（推荐）/ SQLite（fallback） |
| **LLM** | 方舟 doubao-seed 2.0 / DeepSeek v4 Flash |
| **评测** | scikit-learn + BGE-M3 embedding |

---

## 📁 关键目录

```
AIwerewolf/
├── backend/
│   ├── agents/          # Agent 实现
│   │   ├── llm_agent.py       # LLM Agent (2000+ 行)
│   │   ├── heuristic.py       # 启发式 Agent
│   │   ├── characters.py      # 人设系统
│   │   └── prompts.py         # Prompt 模板
│   ├── engine/          # 游戏引擎
│   │   ├── game.py            # 核心游戏逻辑 (1400+ 行)
│   │   ├── models.py          # 数据模型
│   │   └── rules.py           # 规则配置
│   ├── eval/            # 评测系统
│   │   ├── review.py          # 复盘系统
│   │   ├── track_b.py         # Track B 评测
│   │   └── evolution.py       # Track C 进化
│   └── llm/             # LLM 客户端
├── frontend/            # Next.js 前端
├── docs/                # 文档（见 DOC_INDEX.md）
├── scripts/             # 工具脚本
├── tests/               # 测试用例
└── configs/             # 配置文件
```

---

## 🚀 快速命令

```bash
# 跑一局游戏（启发式，秒级）
make demo

# 跑一局游戏（LLM Agent）
python -m backend.run_demo --config configs/demo.yaml

# 启动后端
make dev

# 启动前端
cd frontend && npm run dev

# 跑测试
make test

# 查看文档
cat docs/DOC_INDEX.md
```

---

## 📈 最近更新

### 2026-06-01
- 文档清理完成（从 50+ 个减少到 20 个）
- 文档索引更新 (`docs/DOC_INDEX.md`)
- 项目状态速览更新 (`docs/PROJECT_STATUS.md`)
- README.md 文档地图更新
- LLM Agent 对话过程可捕获 (`scripts/real_game_demo.py`)
- 评测系统重大升级：
  - ProcessScoreV3：角色归一化、置信度感知评分
  - HybridScorer：规则+LLM+反事实混合评分框架
  - PerStepScorer：发言/投票/夜间行动逐步评分
  - PersonaScorer：人设一致性评分
  - StrategyScorer：策略影响评分
  - EloRating：跨局 Elo 排名
  - ScoreCalibrator：Ridge 回归校准

### 2026-05-31
- Track C 自进化系统完成
- 评测系统最终优化

### 2026-05-30
- 前端 UI 完善
- WebSocket 实时推送

---

## ⚠️ 已知问题

详见 `docs/DEVELOPMENT_ISSUES.md`（70KB，非常详细）

主要关注：
- LLM 调用延迟（5-25s/次）
- 部分角色评分区分度不足
- 前端某些边界情况处理

---

## 📞 联系方式

- **项目地址**: `/home/fyh0106/AIwerewolf/`
- **文档目录**: `docs/`
- **测试脚本**: `scripts/`

---

*由小爪整理 (๑•̀ㅂ•́)و✧*
