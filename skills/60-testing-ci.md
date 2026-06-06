---
name: testing-ci
description: pytest 组织、smoke 测试、PR 必过项、本地自检命令
audience: claude, codex, human
version: 1.0.0
updated: 2026-05-22
---

# 测试与 CI 规范

> 当前已有测试:
> - `tests/test_engine.py` — 引擎单元测试
> - `tests/test_api.py` — FastAPI 路由测试
> - `tests/test_llm_config.py` — LLM 配置测试
> - `tests/ui_smoke.mjs` — Playwright UI smoke(Node ESM)
> - `scripts/e2e_smoke.py` — 端到端 smoke

---

## 一、测试金字塔(目标)

```
       ▲  UI smoke(慢、脆、贵)
      ▲ ▲ E2E API smoke
     ▲ ▲ ▲ FastAPI 路由测试
    ▲ ▲ ▲ ▲ 引擎单元测试(快、稳、便宜)
```

**60% 引擎单元测试 + 30% API 测试 + 10% smoke** 是合理比例。
新功能首选单元测试,只有跨层逻辑才上 smoke。

---

## 二、目录结构

```
tests/
├── test_engine.py        # 引擎核心:Phase、Visibility、Resolution
├── test_api.py           # FastAPI 路由
├── test_llm_config.py    # LLM 客户端配置
├── ui_smoke.mjs          # Playwright(Node ESM)
└── __init__.py           # (按需添加)

scripts/
├── e2e_smoke.py          # 端到端 HTTP smoke
├── llm_agent_smoke.py    # 单 Agent LLM 烟雾测试
├── llm_game_smoke.py     # 完整 LLM 对局 smoke
└── human_smoke.py        # 人类玩家流程
```

### 命名约定

- 测试文件:`test_<module>.py`
- 测试函数:`test_<scenario>_<expected>()`,如 `test_game_plays_to_winner`
- smoke 脚本:`<purpose>_smoke.py` / `<purpose>_smoke.mjs`

### 反例

- `test1.py` / `mytest.py`(无意义命名)
- `tests/test_helpers.py`(辅助函数应在被测模块旁边)
- `test_*` 函数没断言(空跑 ≠ 测试)

---

## 三、写单元测试的规则

### 引擎测试必备模式

```python
def test_visibility_hides_roles_from_villager() -> None:
    game = WerewolfGame(seed=3)
    state = game.state
    game.initialize()
    villager = next(p for p in state.players if p.role == Role.VILLAGER)
    view = Visibility().for_player(state, villager.id)

    for player in view.players:
        if player["id"] == villager.id:
            assert player["role"] == Role.VILLAGER.value
        else:
            assert "role" not in player
            assert "alignment" not in player
```

**要点**:

1. **始终给 `seed`**:对局必须可复现,不允许随机失败
2. **断言要具体**:`assert state.winner is not None` 还行,但更好的是 `assert state.winner in {"village", "wolf"}`
3. **一个测试一个意图**:不要在一个函数里塞 10 个不相关断言
4. **遍历多 seed**:关键测试要 `for seed in range(1, 8): ...`

### Mock 与 Fixture

- **绝对禁止** mock LLM 调用做"假绿"测试
- `LLMAgent` 测试用真实 fallback 路径(关掉网络或拨非法 API)
- 需要复用 fixture 时,在 `tests/conftest.py`(目前未建)集中定义

---

## 四、FastAPI 路由测试

使用 `TestClient`(starlette):

```python
from fastapi.testclient import TestClient
from backend.app import app

def test_create_game_returns_winner():
    client = TestClient(app)
    res = client.post("/api/games?seed=7&agent_type=llm")
    assert res.status_code == 200
    body = res.json()
    assert body["winner"] in {"village", "wolf"}
```

**注意**:

- CI / 本地 smoke 用 `LLM_PROVIDER=fake` + `agent_type="llm"`；不得用 `agent_type="heuristic"` 代替对局
- 路由变更要在 `test_api.py` 同步加测试
- 错误路径(404 / 400)也要覆盖

---

## 五、Smoke 测试

### E2E HTTP smoke(`scripts/e2e_smoke.py`)

- 自动起 uvicorn → 调一遍核心 API → 断言响应 → 关闭
- 用于 **PR 前手跑** 或 **答辩前总体验证**
- 不在 PR CI 跑(慢)

### UI Smoke(`tests/ui_smoke.mjs`)

- Playwright 起浏览器 → 模拟点击 → 截图 / 断言
- 改前端的 PR **必须本地跑通后再提**
- 当前依赖 Node + Playwright:`node tests/ui_smoke.mjs`(需先 `npx playwright install chromium`)

---

## 六、PR 必过项

每个 PR 在合并前**必须**:

| 检查 | 命令 |
|------|------|
| 单元测试全绿 | `pytest tests/ -x` |
| Demo 跑通 | `python -m backend.run_demo --seed 7` |
| 改了前端要手测 | 浏览器实际点一遍(`30-frontend-conventions.md` 第八节) |
| 改了 API 要 e2e | `python scripts/e2e_smoke.py` |
| 改了 Agent 要 LLM smoke | `python scripts/llm_agent_smoke.py`(成本看着办) |

**Reviewer 必检**:

- [ ] PR 描述里的"测试方式"清单全部勾选
- [ ] 改动如果是 bugfix,**必须**有覆盖该 bug 的新增测试
- [ ] 新增依赖必须在 `requirements.txt` 登记

---

## 七、本地自检命令(贴在 README 也行)

```bash
# 快速跑全部 pytest
pytest tests/ -x -v

# 跑单个测试
pytest tests/test_engine.py::test_game_plays_to_winner -v

# 启动 demo
python -m backend.run_demo --seed 7

# 启动 web,浏览器看
uvicorn backend.app:app --reload --host 0.0.0.0 --port 8000

# E2E HTTP smoke(自起服务)
python scripts/e2e_smoke.py

# UI smoke(需先装 playwright)
npx playwright install chromium  # 一次性
node tests/ui_smoke.mjs

# LLM 相关 smoke(需 .env 里有 API Key)
python scripts/llm_agent_smoke.py
python scripts/llm_game_smoke.py
```

---

## 八、CI(若尚未配置,建议清单)

> 当前未发现 `.github/workflows/`。建议配置后写本节,以下是参考:

```yaml
# .github/workflows/test.yml(建议)
name: tests
on: [push, pull_request]
jobs:
  pytest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install -r requirements.txt
      - run: pytest tests/ -x -v
```

**不要在 CI 跑**:

- LLM 真实调用(费钱、不稳；CI 用 fake LLM stub)
- UI smoke(慢,需要 headless 浏览器额外配置)

**可以在 CI 跑**:

- pytest 全套(纯 Python,fake LLM)
- e2e_smoke.py(纯 HTTP,fake LLM)
- mypy / ruff / black(若引入)

---

## 九、覆盖率目标

| 模块 | 覆盖率目标 |
|------|------------|
| `engine/` | ≥ 80%(核心) |
| `agents/heuristic.py` | ≥ 70% |
| `agents/llm_agent.py` | ≥ 50%(主要测 fallback 路径) |
| `protocols/` | ≥ 70% |
| `db/` | ≥ 50% |
| `frontend/` | 不做硬性要求,有 UI smoke 即可 |

不强制覆盖率门槛(项目周期短),但 PR 描述里出现"无测试"的改动要被质疑。

---

## 十、答辩前总体验证

冻结期(2026-06-08 起)之前,跑完整 checklist:

- [ ] `pytest tests/` 全绿
- [ ] `python scripts/e2e_smoke.py` 通过
- [ ] `node tests/ui_smoke.mjs` 通过
- [ ] `python scripts/llm_game_smoke.py` 跑通完整一局(7P / 9P / 12P 各 1 次)
- [ ] 浏览器手测 AI vs AI + AI + Human + 主持视角 + 中英文切换
- [ ] DB 持久化:跑 3 局后查 `/api/history`,数据完整

---

## 十一、AI 写测试的红线

- [ ] 不 mock LLM 让测试假绿
- [ ] 不写"空断言"测试(`assert True`)
- [ ] 不在 CI 路径上跑真实 LLM 调用
- [ ] 测试有 seed,可复现
- [ ] 改了引擎 / 路由 / Agent 都补对应测试
- [ ] 不 disable 失败的测试,要 fix 或开 issue

详见 `70-ai-collaboration.md`。

---

*Version 1.0.0 — 2026-05-22 — 初始建立。*
