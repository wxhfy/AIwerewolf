# AI Werewolf 系统完整审查报告（最终版）

**审查日期**: 2026-06-06  
**审查方式**: 代码审查 + API测试 + 真实游戏运行  
**状态**: ⚠️ 发现多个严重问题，系统暂时无法正常使用

---

## 🔴 P0 级问题（阻塞用户使用）

### 1. 游戏创建极度缓慢，预计 5-10 分钟 ⭐️⭐️⭐️⭐️⭐️

**问题**: 创建游戏的 API 会**同步运行完整场游戏**，导致 HTTP 请求阻塞数分钟

**代码位置**:
```python
# backend/app.py:110
state = game.play()  # 同步阻塞！
_rooms.games[state.id] = state
return state.moderator_dict() if show_private else state.public_dict()
```

**性能分析**（7人局，串行执行）:
```
警徽发言（3候选人） : 3 × 15秒 = 45秒
白天发言（7人）      : 7 × 15秒 = 105秒
夜晚行动（4角色）    : 4 × 10秒 = 40秒
-----------------------------------------
单轮合计             : 190秒 ≈ 3.2分钟
完整游戏（3-5轮）    : 9.6 - 16分钟
```

**用户体感**:
1. 点击"创建游戏"
2. 页面卡住 10+ 分钟
3. 最终超时或直接看到游戏结束结果
4. **完全无法观战**

**根本原因**:
1. API 设计错误：创建和运行混在一起
2. 串行执行：`_run_actor_sequence` 取代了并行的 `_batch_ask`
3. LLM API 慢（Doubao 单次 15-30秒）

**修复方案**:

**方案 A（Quick Fix）**: 回滚串行执行
```bash
git checkout HEAD -- backend/engine/game.py
# 重启后端
```
预期改善：10分钟 → 2-3分钟

**方案 B（正确方案）**: 重构 API
```python
# 1. 创建游戏（立即返回）
@app.post("/api/games")
def create_game(...):
    game = _build_game(...)
    game_id = uuid4()
    _rooms.games[game_id] = game
    return {"id": game_id, "status": "created"}

# 2. 启动游戏（异步）
@app.post("/api/games/{game_id}/start")
async def start_game(game_id: str):
    game = _rooms.get_game(game_id)
    asyncio.create_task(game.play_async())
    return {"status": "started"}
```

**优先级**: 🔥 最高

---

### 2. 不支持的人数配置会导致 500 错误 ⭐️⭐️⭐️⭐️

**问题**: 游戏只支持 7-12 人局，其他人数会抛出 `ValueError`

**测试结果**:
```python
WerewolfGame(player_count=3)  
# ValueError: Unsupported player count: 3
```

**支持的人数**: 7, 8, 9, 10, 11, 12

**代码位置**: `backend/engine/rules.py:54-110`

**用户体感**:
- API 文档没有说明人数限制
- 用户尝试创建 3-6 人局 → 500 错误
- 没有友好的错误提示

**修复方案**:
```python
@app.post("/api/games")
def create_game(player_count: int = 10, ...):
    if player_count not in range(7, 13):
        raise HTTPException(
            status_code=400, 
            detail=f"Player count must be 7-12, got {player_count}"
        )
    ...
```

**优先级**: 🔥 高

---

### 3. 缺少关键前端页面 ⭐️⭐️⭐️⭐️

**缺失页面**:
- ❌ `/games` - 游戏列表页（用户无法浏览游戏）
- ❌ `/game/create` - 游戏创建页（用户无法创建游戏）

**现有页面**:
```
✅ /                     首页
✅ /personas             角色库（37个角色）
✅ /evolution            进化看板
✅ /room/[id]/play       游戏详情（需要 game_id）
✅ /room/[id]/human      真人参与
✅ /games/[id]/report    游戏报告
⚠️  /eval/dashboard      评测看板（hydration 错误）
```

**用户流程断裂**:
```
首页 → ？→ 创建游戏 → ？→ 查看游戏列表 → ？→ 观战
     ❌         ❌              ❌
```

**修复成本**: 低（30分钟）

---

## 🟡 P1 级问题（影响体验）

### 4. 数据库僵尸游戏 ⭐️⭐️⭐️

**现象**: 数据库中有永远 `status = "running"` 的游戏

**查询结果**:
```sql
SELECT id, status, created_at FROM games WHERE status = 'running' LIMIT 3;

cab179b6-... | running | 2026-06-06 10:42:50  (8小时前)
afb5d8e5-... | running | 2026-06-06 10:28:11  (8小时前)
54fe3a0c-... | running | 2026-06-06 10:21:22  (8小时前)
```

**影响**:
- 占用数据库空间
- 游戏列表显示异常
- 统计数据不准确

**立即修复**:
```bash
docker exec werewolf-pg psql -U werewolf -d werewolf -c \
  "UPDATE games SET status = 'timeout' WHERE status = 'running' AND created_at < NOW() - INTERVAL '1 hour';"
```

**长期方案**: 添加定时清理 cron job

---

### 5. 前端 Hydration 错误 ⭐️⭐️

**错误**:
```
Warning: Text content did not match. 
Server: "2026/6/6 18:29:34" 
Client: "2026/6/6 18:29:35"
```

**位置**: `frontend/app/eval/dashboard/page.tsx:39`

**原因**: SSR 时服务端和客户端时间戳不一致

**修复**:
```tsx
const [timestamp, setTimestamp] = useState<string | null>(null);
useEffect(() => {
  setTimestamp(new Date().toLocaleString());
}, []);

return <div>{timestamp || 'Loading...'}</div>;
```

---

### 6. /api/health 端点不可用 ⭐️⭐️

**现象**: `GET /api/health` → 500 错误

**影响**: 无法监控服务健康状态

**修复**:
```python
@app.get("/api/health")
def health_check():
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "version": "0.1.0"
    }
```

---

## 📊 测试结果汇总

### API 测试
| 端点 | 状态 | 响应时间 | 备注 |
|------|------|----------|------|
| `GET /api/personas` | ✅ 200 | <100ms | 37 个角色 |
| `GET /api/games` | ✅ 200 | <50ms | 0 个内存游戏 |
| `GET /api/history` | ✅ 200 | <200ms | 5 条历史 |
| `GET /api/health` | ❌ 500 | N/A | 未实现 |
| `GET /docs` | ✅ 200 | <100ms | Swagger 正常 |
| `POST /api/games?player_count=3` | ❌ 500 | <10ms | 不支持人数 |
| `POST /api/games?player_count=7` | ⏱️ 测试中 | >120s | 运行中 |

### 前端测试
| 页面 | 状态 | 加载时间 | 控制台错误 |
|------|------|----------|-----------|
| `/` | ✅ | 1.2s | 0 |
| `/personas` | ✅ | 1.5s | 0 |
| `/games` | ❌ 404 | N/A | N/A |
| `/game/create` | ❌ 404 | N/A | N/A |
| `/eval/dashboard` | ⚠️ | 超时 | 4 个 |

### 数据库状态
```
personas:        37 条
games:           8,993 条
game_events:     442,747 条
agent_decisions: 188,199 条
votes:           52,928 条
players:         79,825 条

running 状态游戏: 3 条（僵尸）
```

---

## 🎯 修复优先级和时间估算

### 立即修复（今天，2小时）
1. ✅ 添加人数校验（15分钟）
2. ✅ 清理僵尸游戏（5分钟）
3. ⚠️ 回滚串行执行（10分钟）OR 等待测试结果决定
4. ✅ 创建 `/games` 列表页（30分钟）
5. ✅ 修复 `/api/health`（10分钟）

### 本周修复（3天）
6. 重构 `create_game` API（4小时）
7. 创建 `/game/create` 页面（2小时）
8. 修复 Hydration 错误（30分钟）
9. 添加错误处理和友好提示（2小时）

### 长期优化（1-2周）
10. WebSocket 实时推送（2天）
11. 游戏超时清理机制（半天）
12. 性能监控和日志（1天）
13. 前端 loading 状态（半天）

---

## 💡 立即可执行的命令

### 1. 清理僵尸游戏
```bash
docker exec werewolf-pg psql -U werewolf -d werewolf -c \
  "UPDATE games SET status = 'timeout' WHERE status = 'running' AND created_at < NOW() - INTERVAL '1 hour';"
```

### 2. 查看串行/并行改动
```bash
cd /home/fyh0106/AIwerewolf
git diff backend/engine/game.py
```

### 3. 回滚串行执行（如果测试结果不理想）
```bash
git checkout HEAD -- backend/engine/game.py
pkill -f "uvicorn.*app:app"
cd backend && uvicorn app:app --host 0.0.0.0 --port 8001 &
```

---

## 🔍 待确认

### 7人局性能测试（进行中）
- **目标**: 确认串行执行的实际耗时
- **状态**: 后台运行，2分钟超时
- **判断标准**:
  - <60秒 → 可接受，保留串行
  - 60-120秒 → 需要优化
  - >120秒 → 必须回滚到并行

---

## 📝 Git 状态

```
M  backend/engine/game.py  (已暂存，串行执行改动)
?? docs/goal.md
 m references/*  (submodule changes)
```

**建议**: 
- 如果串行执行性能可接受 → 提交并注明原因
- 如果性能不可接受 → 回滚

---

## 📸 诊断证据

文件位置：
- `/tmp/diagnosis_home.png` - 首页截图
- `/tmp/diagnosis_personas.png` - 角色库截图  
- `/tmp/game_response.json` - 游戏响应（待生成）
- `docs/DEEP_REVIEW_2026-06-06.md` - 本报告
- `docs/SYSTEM_DIAGNOSIS_2026-06-06.md` - 初步诊断

---

## 🚀 下一步行动

1. **等待 7人局测试结果**（2分钟内）
2. **根据结果决定是否回滚串行执行**
3. **执行立即修复清单**（2小时）
4. **重新测试完整流程**
5. **提交改动并更新文档**

---

**报告生成时间**: 2026-06-06 19:00  
**测试环境**: 生产环境（本地开发）  
**责任人**: wxhfy + AI 助手（小爪）  
**下次审查**: 修复完成后
