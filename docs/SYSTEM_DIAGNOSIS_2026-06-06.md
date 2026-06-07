# AI Werewolf 系统用户体感问题诊断报告

**诊断日期**: 2026-06-06  
**诊断范围**: 完整系统（基础设施 + 后端 API + 前端 + 游戏流程 + 数据库 + 性能）

---

## 📊 系统基本状态

### ✅ 正常运行的部分
- **PostgreSQL**: 容器运行正常 (Up 2 weeks)，37 个角色数据，8993 场历史游戏
- **后端 API**: 端口 8001 正常响应，Swagger 文档可访问
- **前端**: 首页和角色库页面加载正常，UI 美观
- **历史数据**: 442,747 条游戏事件，188,199 条 Agent 决策记录

---

## 🔴 严重问题（影响核心功能）

### 1. **游戏创建 API 逻辑错误** ⭐️⭐️⭐️⭐️⭐️
**现象**: 
- 后端 `/api/games` POST 请求创建游戏后会**自动运行完整场游戏**（调用 `game.play()`）
- API 返回的是游戏**结束后**的状态，而不是刚创建的游戏 ID
- 诊断脚本尝试创建游戏后提取 `id` 字段失败

**根本原因**:
```python
# backend/app.py:110-112
state = game.play()  # 这里直接把整场游戏跑完了！
_rooms.games[state.id] = state
return state.moderator_dict() if show_private else state.public_dict()
```

**用户体感影响**:
- 用户点击"创建游戏"后**无法看到游戏进行中的过程**
- 直接看到游戏结束结果，完全没有"观战"体验
- 前端无法获取 `game_id` 来跳转到游戏详情页

**解决方案**:
需要拆分为两个接口：
1. `POST /api/games` → 只创建游戏，返回 `{id, status: "created"}`
2. `POST /api/games/{id}/start` → 启动游戏（异步运行或分阶段推进）

**涉及文件**: 
- `backend/app.py:94-112`
- 需要新增游戏状态管理逻辑

---

### 2. **前端服务未正常运行** ⭐️⭐️⭐️⭐️
**现象**:
- 端口 3002 未被占用（lsof 检查为空）
- 但前端页面可以访问（可能是 Next.js dev server 的特殊机制）
- Playwright 测试显示"未发现任何 API 请求"

**用户体感影响**:
- 前端可能没有真正连接后端 API
- 页面可能是静态页面，数据可能是 mock 数据

**排查方向**:
```bash
ps aux | grep next
netstat -tuln | grep 3002
```

---

### 3. **数据库中有 3 个 `running` 状态的僵尸游戏** ⭐️⭐️⭐️
**现象**:
```
d6feec85-64d4-44b8-946c-cdc4a6843556 | running | | 2026-06-06 10:28:11
54fe3a0c-79e7-4a67-abb6-14fd08c66cc7 | running | | 2026-06-06 10:21:22
cab6e52d-3685-4784-bc24-e4dbeafc4a59 | running | | 2026-06-06 10:20:19
```

**用户体感影响**:
- 这些游戏永远不会结束，占用数据库资源
- 可能导致游戏列表显示异常

**解决方案**:
添加游戏超时机制或手动清理：
```sql
UPDATE games SET status = 'timeout' WHERE status = 'running' AND created_at < NOW() - INTERVAL '1 hour';
```

---

## 🟡 需要关注的问题（影响用户体验）

### 4. **缺少关键页面路由** ⭐️⭐️⭐️⭐️
**现象**:
- `/games` → 404（游戏列表页）
- `/room` → 404（房间列表页）
- `/game/create` → 404（游戏创建页）
- `/eval/dashboard` → 超时（评测看板）

**用户体感影响**:
- 用户创建游戏后**不知道去哪里看游戏**
- 没有游戏列表入口
- 评测功能无法使用

**现有页面**:
```
✅ /                 (首页)
✅ /personas         (角色库)
✅ /evolution        (进化看板)
❌ /games            (不存在)
❌ /room             (不存在)
❌ /game/create      (不存在)
⚠️  /eval/dashboard  (超时/hydration错误)
✅ /room/[id]/play   (游戏详情 - 需要 game_id)
✅ /room/[id]/human  (真人参与)
✅ /games/[id]/report (游戏报告)
```

**解决方案**:
1. 创建 `frontend/app/games/page.tsx` 游戏列表页
2. 创建 `frontend/app/game/create/page.tsx` 游戏创建页
3. 修复 `/eval/dashboard` 的 hydration 错误

---

### 5. **前端控制台错误和 Hydration 警告** ⭐️⭐️⭐️
**现象**:
```
[error] Warning: Text content did not match. Server: "2026/6/6 18:29:34" Client: "2026/6/6 18:29:35"
[error] Warning: An error occurred during hydration.
```

**根本原因**:
Next.js SSR 时服务端和客户端渲染的时间戳不一致

**用户体感影响**:
- 页面加载时可能闪烁
- React hydration 失败会导致整个页面重新渲染（慢）

**解决方案**:
```tsx
// 使用 useEffect 确保时间戳只在客户端渲染
const [timestamp, setTimestamp] = useState<string | null>(null);
useEffect(() => {
  setTimestamp(new Date().toLocaleString());
}, []);
```

**涉及文件**: `frontend/app/eval/dashboard/page.tsx:39`

---

### 6. **串行执行导致游戏运行速度慢** ⭐️⭐️⭐️⭐️
**现象**:
`backend/engine/game.py` 已被修改为串行执行（`_run_actor_sequence`）

**用户体感影响**:
- 7 人局警徽发言阶段：3 个候选人串行发言 → **至少 30 秒**（假设每人 10 秒）
- 白天发言阶段：7 人串行发言 → **至少 70 秒**
- **一场完整游戏可能需要 5-10 分钟**（用户无法忍受）

**对比**:
- **并行执行**：7 人同时调用 LLM → 10 秒完成
- **串行执行**：7 人依次调用 LLM → 70 秒完成

**Git 状态**:
```
M  backend/engine/game.py  (已暂存，未提交)
```

**建议**:
1. **回滚到并行执行**（如果没有严重 bug）
2. 或者**混合策略**：重要发言（警徽、遗言）串行，普通发言并行
3. 提交前测试一场完整游戏的耗时

**涉及文件**: `backend/engine/game.py:_badge_speech_phase, _speech_phase`

---

### 7. **健康检查端点不可用** ⭐️⭐️
**现象**:
`GET /api/health` → 500 Internal Server Error

**用户体感影响**:
- DevOps 无法监控服务健康状态
- 前端无法检测后端是否在线

**解决方案**:
```python
@app.get("/api/health")
def health_check():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}
```

---

## 📋 代码和配置问题

### 8. **未提交的改动** ⭐️
```
M  backend/engine/game.py
?? docs/goal.md
```

**影响**:
- 其他开发者/部署环境看不到最新改动
- 回滚困难

**建议**:
立即提交或丢弃改动：
```bash
git add backend/engine/game.py
git commit -m "perf: 串行执行代码（待验证性能影响）"
```

---

## 🎯 优先级排序（从用户体感出发）

| 优先级 | 问题 | 预计影响用户数 | 修复成本 |
|--------|------|---------------|---------|
| P0 | 游戏创建 API 逻辑错误 | 100% | 中 |
| P0 | 缺少游戏列表页 `/games` | 100% | 低 |
| P1 | 串行执行导致游戏太慢 | 100% | 低（回滚） |
| P1 | 缺少游戏创建页 `/game/create` | 80% | 低 |
| P2 | 前端 Hydration 错误 | 50% | 低 |
| P2 | 清理僵尸游戏 | 10% | 低 |
| P3 | 健康检查端点 | DevOps | 低 |

---

## 💡 立即可做的改进

### Quick Win #1: 创建游戏列表页（15 分钟）
```tsx
// frontend/app/games/page.tsx
export default async function GamesPage() {
  const games = await fetch('http://localhost:8001/api/history?limit=50').then(r => r.json());
  return (
    <div>
      <h1>游戏列表</h1>
      {games.map(game => (
        <GameCard key={game.id} game={game} />
      ))}
    </div>
  );
}
```

### Quick Win #2: 回滚串行执行（5 分钟）
```bash
git checkout HEAD -- backend/engine/game.py
```

### Quick Win #3: 清理僵尸游戏（1 分钟）
```bash
docker exec werewolf-pg psql -U werewolf -d werewolf -c \
  "UPDATE games SET status = 'timeout' WHERE status = 'running' AND created_at < NOW() - INTERVAL '1 hour';"
```

---

## 📸 截图证据

诊断过程生成的截图：
- `/tmp/diagnosis_home.png` - 首页正常
- `/tmp/diagnosis_personas.png` - 角色库正常
- `/tmp/diagnosis_games.png` - 404 错误
- `/tmp/diagnosis_eval.png` - hydration 错误

---

## 🔧 下一步行动建议

1. **立即修复** (今天):
   - 创建 `/games` 页面
   - 回滚串行执行或验证性能
   - 清理僵尸游戏

2. **本周修复**:
   - 重构游戏创建 API（拆分创建和启动）
   - 修复 hydration 错误
   - 创建 `/game/create` 页面

3. **持续优化**:
   - 添加游戏超时机制
   - 前端添加 loading 状态
   - 性能监控（游戏耗时统计）

---

**报告生成**: 2026-06-06 18:30  
**诊断工具**: Playwright + curl + Docker + PostgreSQL  
**数据来源**: 实际运行测试 + 代码审查 + 数据库查询
