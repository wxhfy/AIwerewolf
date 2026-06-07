# AI Werewolf 系统深度审查报告（2026-06-06）

## 📋 执行摘要

**测试范围**: 代码审查 + API测试 + 真实游戏运行  
**测试时间**: 2026-06-06 18:30 - 18:50  
**核心发现**: 系统存在 **严重性能问题**，游戏创建请求超时 5 分钟

---

## 🔴 严重问题（P0 - 阻塞用户使用）

### 1. 游戏运行极度缓慢，超时 5 分钟 ⭐️⭐️⭐️⭐️⭐️

**现象**:
```
创建 7 人局游戏 → 等待 5 分钟 → 超时
```

**测试细节**:
- 发送 `POST /api/games?player_count=7` 
- 等待 300 秒（5分钟）后超时
- 后端进程仍在运行（PID 3232611）
- 内存中游戏数为 0（说明游戏要么崩溃要么还在跑）

**根本原因分析**:

1. **串行执行导致速度慢**
   ```python
   # backend/engine/game.py 已被修改为串行
   self._run_actor_sequence(Phase.DAY_BADGE_SPEECH, candidates, handle)
   ```
   
   **理论耗时计算**（7人局）:
   - 警徽发言（3候选人串行）: 3 × 10秒 = **30秒**
   - 白天发言（7人串行）: 7 × 10秒 = **70秒**
   - 夜晚行动（4个角色串行）: 4 × 8秒 = **32秒**
   - **单轮合计**: 132秒 ≈ 2.2分钟
   - **完整游戏（3-5轮）**: 6-11分钟

2. **API 自动运行完整游戏**
   ```python
   # backend/app.py:110
   state = game.play()  # 同步阻塞，等游戏结束才返回
   ```
   这意味着 HTTP 请求必须等游戏**完全结束**才能返回！

3. **LLM API 可能更慢**
   - Doubao API 单次调用可能需要 15-30 秒
   - 串行执行 × 慢速 API = 灾难

**用户体感影响**:
- 用户点击"创建游戏" → **等待 5-10 分钟** → 页面超时
- **完全无法使用**

**解决方案**:
1. **立即回滚到并行执行** （Quick Fix）
2. **拆分 API**：
   - `POST /api/games` → 只创建，立即返回 ID
   - `POST /api/games/{id}/start` → 异步启动游戏
3. **添加 WebSocket** 实时推送进度

**涉及文件**:
- `backend/engine/game.py` (已暂存改动)
- `backend/app.py:94-112`

---

### 2. create_game API 设计缺陷 ⭐️⭐️⭐️⭐️⭐️

**问题**: API 会自动运行完整场游戏，用户无法观战

**代码证据**:
```python
# backend/app.py:110-112
state = game.play()  # 自动跑完游戏！
_rooms.games[state.id] = state
return state.moderator_dict() if show_private else state.public_dict()
```

**用户体感**:
1. 用户点"创建游戏"
2. 等待 5-10 分钟（如果不超时）
3. 直接看到游戏结束结果
4. **没有任何观战过程**

**期望行为**:
1. 创建游戏 → 立即返回 `{id: "xxx", status: "created"}`
2. 用户可以观看游戏进行
3. 游戏异步推进，前端实时接收更新

**修复优先级**: 🔥 最高

---

### 3. 缺少关键前端页面 ⭐️⭐️⭐️⭐️

**缺失页面**:
- ❌ `/games` - 游戏列表页
- ❌ `/game/create` - 游戏创建页

**现有页面**:
```
✅ /                     (首页)
✅ /personas             (角色库)
✅ /evolution            (进化看板)
✅ /room/[id]/play       (游戏详情)
✅ /room/[id]/human      (真人参与)
✅ /games/[id]/report    (游戏报告)
⚠️  /eval/dashboard      (超时/hydration错误)
```

**用户体感**:
- 用户创建游戏后**不知道去哪里看**
- 没有入口浏览历史游戏

**修复成本**: 低（15分钟）

---

## 🟡 需要修复的问题（P1）

### 4. 数据库中有僵尸游戏 ⭐️⭐️⭐️

**现象**:
```sql
SELECT id, status, created_at FROM games WHERE status = 'running' ORDER BY created_at DESC LIMIT 5;

cab179b6-f2dc-4f36-beaa-12b1960ad8c2 | running | 2026-06-06 10:42:50
afb5d8e5-... | running | 2026-06-06 10:28:11
54fe3a0c-... | running | 2026-06-06 10:21:22
```

**问题**: 这些游戏永远不会结束

**原因**: 
- 游戏崩溃/超时后状态未更新
- 缺少超时清理机制

**解决方案**:
```sql
-- 立即清理
UPDATE games SET status = 'timeout' 
WHERE status = 'running' 
AND created_at < NOW() - INTERVAL '1 hour';

-- 长期方案：添加定时清理任务
```

---

### 5. 前端 Hydration 错误 ⭐️⭐️

**错误信息**:
```
Warning: Text content did not match. 
Server: "2026/6/6 18:29:34" 
Client: "2026/6/6 18:29:35"
```

**原因**: SSR 时服务端和客户端时间戳不一致

**位置**: `frontend/app/eval/dashboard/page.tsx:39`

**修复**:
```tsx
const [timestamp, setTimestamp] = useState<string | null>(null);
useEffect(() => {
  setTimestamp(new Date().toLocaleString());
}, []);
```

---

## 📊 代码审查发现

### Git 未提交改动
```
M  backend/engine/game.py  (串行执行改动)
?? docs/goal.md
```

**建议**: 
- 如果串行执行是有意的 → 立即提交并说明原因
- 如果是实验性改动 → 回滚到并行执行

---

## 🧪 测试结果

### API 测试
| 端点 | 状态 | 备注 |
|------|------|------|
| `GET /api/personas` | ✅ 200 | 37 个角色 |
| `GET /api/games` | ✅ 200 | 0 个游戏 |
| `GET /api/history` | ✅ 200 | 5 条记录 |
| `GET /api/health` | ❌ 500 | 未实现 |
| `POST /api/games` | ⏱️ 超时 | 5 分钟无响应 |

### 前端测试
| 页面 | 状态 | 备注 |
|------|------|------|
| `/` | ✅ | 首页正常 |
| `/personas` | ✅ | 37 个角色卡片 |
| `/games` | ❌ 404 | 缺失 |
| `/game/create` | ❌ 404 | 缺失 |
| `/eval/dashboard` | ⚠️ 超时 | Hydration 错误 |

### 真实游戏测试
| 配置 | 结果 | 耗时 |
|------|------|------|
| 7人局 | ❌ 超时 | >300秒 |
| 3人局 | ⏱️ 测试中 | 待确认 |

---

## 🎯 修复优先级

### 立即修复（今天）
1. **回滚串行执行** → 并行执行（5分钟）
2. **创建 `/games` 列表页**（15分钟）
3. **清理僵尸游戏**（1分钟）

### 本周修复
4. **重构 create_game API** → 拆分创建和启动（2小时）
5. **修复 Hydration 错误**（30分钟）
6. **创建 `/game/create` 页面**（1小时）

### 长期优化
7. **添加 WebSocket 实时推送**（1天）
8. **添加游戏超时机制**（2小时）
9. **性能监控和日志**（1天）

---

## 💡 立即可执行的命令

### 1. 回滚串行执行
```bash
cd /home/fyh0106/AIwerewolf
git diff backend/engine/game.py  # 查看改动
git checkout HEAD -- backend/engine/game.py  # 回滚
# 或者
git stash  # 暂存改动
```

### 2. 清理僵尸游戏
```bash
docker exec werewolf-pg psql -U werewolf -d werewolf -c \
  "UPDATE games SET status = 'timeout' WHERE status = 'running' AND created_at < NOW() - INTERVAL '1 hour';"
```

### 3. 重启后端（应用回滚）
```bash
pkill -f "python.*app.py"
cd backend && python app.py &
```

---

## 📸 测试证据

- `/tmp/diagnosis_home.png` - 首页正常
- `/tmp/diagnosis_personas.png` - 角色库正常
- `/tmp/diagnosis_games.png` - 404 错误
- `/tmp/game_response.json` - 待生成（3人局测试完成后）

---

## 🔍 待确认问题

### 3人局测试（进行中）
- **目的**: 确认是否是串行执行导致超时
- **预期结果**: 
  - 如果 3 人局也超时 → 可能是 LLM API 问题
  - 如果 3 人局正常 → 确认是串行执行性能问题
- **状态**: 后台运行中，最多 10 分钟

---

**报告生成时间**: 2026-06-06 18:50  
**下次审查**: 修复后重新测试  
**责任人**: wxhfy + AI 助手（小爪）
