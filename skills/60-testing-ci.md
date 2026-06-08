---
name: testing-ci
description: pytest 组织、smoke 测试、CI、本地自检命令
audience: claude, codex, human
version: 2.0.0
updated: 2026-06-08
---

# 测试与 CI 规范

> 当前审计快照（2026-06-08）：`tests/` 下有 39 个 `test_*.py` 文件，约 397 个 pytest 测试函数；CI 已配置在 `.github/workflows/ci.yml`。

---

## 一、测试分层

```
       ▲  UI smoke / Playwright（慢，手动或发布前跑）
      ▲ ▲ E2E API smoke（跨层）
     ▲ ▲ ▲ FastAPI 路由测试
    ▲ ▲ ▲ ▲ 引擎 / Agent / DB / Eval 单元测试
```

新功能优先补单元测试；只有跨后端、前端、数据库或 WebSocket 的流程才补 smoke。

---

## 二、目录与命名

```
tests/
├── test_*.py                 # pytest 单元/集成测试
├── helpers/                  # 测试辅助对象
└── ui_smoke.mjs              # Playwright UI smoke

scripts/
├── e2e_smoke.py              # HTTP smoke
├── llm_agent_smoke.py        # 单 Agent LLM smoke
├── llm_game_smoke.py         # 完整对局 smoke
└── human_smoke.py            # 真人玩家流程 smoke
```

- 测试文件：`test_<module>.py`
- 测试函数：`test_<scenario>_<expected>()`
- smoke 脚本：`<purpose>_smoke.py` / `<purpose>_smoke.mjs`
- 辅助 fixture 放在 `tests/conftest.py` 或 `tests/helpers/`

---

## 三、单元测试规则

1. 对局相关测试必须固定 `seed`，避免随机红。
2. 断言要具体，不写 `assert True` 或只检查“没有异常”。
3. 一个测试只验证一个意图。
4. 引擎关键路径可以遍历多个 seed。
5. 改动 bugfix 时必须补能复现该 bug 的测试。
6. 不在 CI 路径调用真实 LLM；CI 使用 test-only fake LLM。

示例：

```python
def test_visibility_hides_roles_from_villager() -> None:
    game = WerewolfGame(seed=3, player_count=7)
    game.initialize()
    villager = next(p for p in game.state.players if p.role == Role.VILLAGER)

    view = Visibility().for_player(game.state, villager.id)

    for player in view.players:
        if player["id"] == villager.id:
            assert player["role"] == Role.VILLAGER.value
        else:
            assert "role" not in player
            assert "alignment" not in player
```

---

## 四、LLM 与 Agent 测试

正式对局 AI 席位只能走 LLM-compatible `CognitiveAgent`：

- `agent_type=heuristic` 应被拒绝。
- CI / 本地离线测试使用 `LLM_PROVIDER=fake`，且必须显式设置 `_TEST_ALLOW_FAKE_LLM=true`。
- fake LLM 只能用于测试和 smoke，不得作为正式实验或产品结论证据。
- strict 实验要求 `fallback_count=0`；若出现 fallback/invalid，样本必须标记或剔除。

推荐环境：

```bash
_TEST_ALLOW_FAKE_LLM=true \
LLM_PROVIDER=fake \
AIWEREWOLF_STRICT_MODE=true \
ALLOW_FALLBACK=false \
python -m pytest tests/ -q --timeout=120
```

---

## 五、FastAPI 路由测试

使用 `fastapi.testclient.TestClient`：

```python
from fastapi.testclient import TestClient
from backend.app import app


def test_health_ok() -> None:
    client = TestClient(app)
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
```

路由变更必须同步：

- `skills/50-api-contract.md`
- `frontend/types/index.ts` 或前端调用点（如契约被前端使用）
- 对应 `tests/test_api*.py`

---

## 六、Smoke 测试

常用命令：

```bash
# 后端 HTTP smoke
python scripts/e2e_smoke.py

# 单 Agent LLM smoke（需要真实 key，或明确 fake 环境）
python scripts/llm_agent_smoke.py

# 完整对局 smoke（真实 LLM 成本较高）
python scripts/llm_game_smoke.py --seed 1 --max-seed 1

# UI smoke（需先安装浏览器）
cd frontend
npx playwright install chromium
node ../tests/ui_smoke.mjs
```

改前端页面、WebSocket、房间流或真人操作时，至少跑一次浏览器手测；发布前再跑 UI smoke。

---

## 七、本地自检命令

```bash
# Python lint
ruff check backend/ scripts/ tests/ configs/
ruff format --check backend/ scripts/ tests/ configs/

# 全量 pytest（离线 fake LLM）
_TEST_ALLOW_FAKE_LLM=true LLM_PROVIDER=fake python -m pytest tests/ -q --timeout=120

# 单文件/单测试
python -m pytest tests/test_api.py -q
python -m pytest tests/test_engine.py::test_game_plays_to_winner -q

# 后端服务
uvicorn backend.app:app --reload --host 0.0.0.0 --port 8000

# 前端
cd frontend
npm install
npm run lint
npm run build
npm run dev
```

---

## 八、CI

当前 CI 文件：`.github/workflows/ci.yml`

CI 必须做两件事：

1. `ruff check` + `ruff format --check`
2. `python -m pytest tests/ -q --timeout=120`

CI 不应该：

- 调真实 LLM API。
- 因为缺真实 key 就吞掉 pytest 失败。
- 跑大体积实验、Playwright 截图或真实模型批量对局。

CI 应该显式设置：

```yaml
_TEST_ALLOW_FAKE_LLM: "true"
LLM_PROVIDER: fake
AIWEREWOLF_STRICT_MODE: "true"
ALLOW_FALLBACK: "false"
```

---

## 九、覆盖率目标

| 模块 | 目标 |
|------|------|
| `backend/engine/` | 核心规则、阶段、结算、Visibility 必须有高覆盖 |
| `backend/agents/cognitive/` | AgentLoop、工具、解析、strict/no-fallback 路径重点覆盖 |
| `backend/protocols/` | 房间、真人输入、WebSocket snapshot 覆盖核心路径 |
| `backend/db/` | 初始化、写入、查询、幂等与失败容忍覆盖关键路径 |
| `backend/eval/` | scorer、review、knowledge lifecycle 覆盖业务不变量 |
| `frontend/` | 不设硬覆盖率门槛，但关键页面需 lint/build 和 smoke |

---

## 十、答辩 / 发布前 Checklist

- [ ] `ruff check backend/ scripts/ tests/ configs/`
- [ ] `ruff format --check backend/ scripts/ tests/ configs/`
- [ ] `_TEST_ALLOW_FAKE_LLM=true LLM_PROVIDER=fake python -m pytest tests/ -q --timeout=120`
- [ ] `python scripts/e2e_smoke.py`
- [ ] `cd frontend && npm run lint && npm run build`
- [ ] 浏览器手测：AI vs AI、AI + Human、主持视角、公开视角、中英文切换
- [ ] DB 持久化：跑局后 `/api/history`、`/api/replay/{game_id}` 可查
- [ ] `git status --short --ignored` 无应入库的大文件、日志、密钥、缓存

---

## 十一、AI 写测试红线

- [ ] 不 mock 真实 LLM 结果来制造“假绿”；测试用 fake LLM 必须显式 test-only。
- [ ] 不写空断言。
- [ ] 不在 CI 真实扣费。
- [ ] 不禁用失败测试；要修复或明确记录为外部依赖问题。
- [ ] 不把 `.env`、API key、prompt 全文写入测试快照。

详见 `70-ai-collaboration.md`。
