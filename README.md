# AIwerewolf

构建一个 AI 狼人杀多智能体对战系统。核心是多 Agent 协作/对抗机制：每个 Agent 根据扮演角色（狼人、预言家、女巫等）拥有独立目标、策略与行动空间，在严格信息隔离下进行推理、发言与决策。

## 当前 Demo

已实现一个离线可玩的 6 人 AI 狼人杀基础框架：

- 角色：狼人、预言家、女巫、猎人、守卫、村民
- 流程：夜晚守护/狼人刀人/女巫用药/预言家查验/夜晚结算/白天发言/投票/猎人开枪/胜负判定
- Agent：AIWolf 风格生命周期接口 + 离线启发式 Agent
- 信息隔离：普通玩家只看公开信息，狼人只额外知道狼队友，预言家只收到自己的查验结果
- 可观测：结构化事件日志，支持公开视角和主持视角
- UI：FastAPI 托管的最小观战页

## 运行

```bash
python -m pip install -r requirements.txt
python -m backend.run_demo --seed 7
python -m backend.run_demo --config configs/demo.yaml --show-private
```

启动 Web 观战页：

```bash
uvicorn backend.app:app --reload --host 0.0.0.0 --port 8000
```

打开 `http://localhost:8000`，点击“运行一局”生成并查看完整对局。

## API

```bash
curl -X POST "http://localhost:8000/api/games?seed=7"
curl "http://localhost:8000/api/games"
curl "http://localhost:8000/api/games/<game_id>?show_private=true"
```

## 扩展点

- 新角色：在 `backend/engine/rules.py` 添加 `RoleSpec`，再在 `backend/engine/game.py` 增加对应阶段或动作结算。
- 新 Agent：实现 `backend/agents/base.py` 的 `Agent` 协议并返回 `Decision`，无需改引擎主循环。
- 新动作：在 `backend/engine/actions.py` 注册 `ActionRule`，由阶段处理器读取并结算。
- 前端：当前 `frontend/` 是静态观战页，后续可迁移为 Next.js 并沿用 `/api/games` 协议。

## 验证

```bash
pytest -q
```
