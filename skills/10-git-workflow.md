---
name: git-workflow
description: 分支命名、Commit 规范、PR 模板、Review checklist、合并策略
audience: claude, codex, human
version: 1.0.0
updated: 2026-05-22
---

# Git 工作流 + PR 规范

> **⚠️ 单人模式覆盖**：本文件 §一 / §三 / §七 中关于"main 受保护、禁止直推、要 PR、要 N 人 approve"的条款，**在当前单人开发阶段被 `CLAUDE.md / AGENTS.md` 顶部"项目运行模式"段覆盖**。AI 可在用户授权下直接 push 到 main。团队 ≥ 2 人时本覆盖失效、恢复本文件原规则。

## 一、分支模型

**主干**：`main`（受保护，禁止直推）。<sup>单人模式下豁免——见 `CLAUDE.md` 顶部"项目运行模式"</sup>

**功能分支命名**：

```
<type>/<author>-<short-topic>
```

| `<type>` | 用途 |
|----------|------|
| `feat`   | 新功能 |
| `fix`    | Bug 修复 |
| `refactor` | 重构（不改行为） |
| `docs`   | 仅文档 |
| `test`   | 仅测试 |
| `chore`  | 配置/依赖/工具 |

**示例**：
- `feat/alice-witch-poison-prompt`
- `fix/bob-hunter-double-shoot`
- `refactor/cathy-visibility-cache`

**禁止**：`dev`、`tmp`、`mybranch`、姓名拼音首字母（与 author 冲突）。

---

## 二、Commit 信息规范

参考已有提交（如 `b5da379 Switch to LLM-only mode, add PostgreSQL/SQLite database layer`），保持**简短、有动词、聚焦一件事**。

### 推荐格式

```
<type>(<scope>): <imperative summary, <= 70 chars>

<可选正文，解释 why，不解释 what>
```

| `<type>` | 何时用 |
|----------|--------|
| `feat`   | 新增功能 |
| `fix`    | 修 Bug |
| `refactor` | 重构 |
| `docs`   | 文档 |
| `test`   | 测试 |
| `chore`  | 杂项 |
| `perf`   | 性能 |

`<scope>` 用模块名：`engine` / `agents` / `frontend` / `db` / `api` / `prompt` / `skills`。

### 示例

```
feat(agents): add hunter shoot decision after night kill
fix(frontend): prevent double websocket on language switch
refactor(engine): extract phase resolver into ResolutionEngine
docs(skills): clarify pr review checklist
```

### 反例（不要这样写）

```
update                       ← 没有 type、scope、动词
Fixed bug                    ← 过去式、scope 缺失、无指向
WIP                          ← 不要在 main/PR 上出现
朕修复了猎人开枪的 bug          ← 主语不是开发者，且不要用"朕"
```

---

## 三、PR 流程

### 开 PR 之前

1. 已 `git pull --rebase origin main`，本地无冲突
2. 已跑 `pytest tests/`，全绿
3. 改了前端的话，本地 `uvicorn backend.app:app --reload` 跑过一遍点过对应界面
4. 改了 API/事件契约的话，**已同步更新 `skills/50-api-contract.md`**
5. 改了规范的话，**已在 PR 描述里显式说明"修改 skills/xxx 第 N 条"**

### PR 描述模板

```markdown
## 改了啥
<一句话总结>

## 为什么
<动机、关联 issue、上下文>

## 影响面
- [ ] 后端 engine
- [ ] 后端 agents
- [ ] 后端 api/protocols
- [ ] 前端
- [ ] DB schema
- [ ] 文档/规范

## 测试方式
- [ ] `pytest tests/` 通过
- [ ] `python -m backend.run_demo --seed 7` 通过
- [ ] 浏览器手测：<具体步骤>

## AI 协作披露
- [ ] 本 PR 由 AI（Claude / Codex / 其他）参与生成
- AI 改动的范围：<哪些文件 / 哪些函数>
- 人工 review 重点：<哪些地方我重点看过>

## Checklist
- [ ] 符合对应 skills/ 规范
- [ ] 无新增未授权依赖
- [ ] 无 API Key / 秘密泄漏
```

### Review 要求

- **至少 1 人 approve 才能合并**。改动符合下表"重灾区"的，**需要 2 人 approve**。
- Review 截止时间：**24h 内给出首次反馈**（工作日）。
- Reviewer 不是质检，是同伴——发现问题用 "**建议**"/"**疑问**"/"**必须**" 三档标注。

| 重灾区文件（动了要 2 人 approve） |
|------------------------------------|
| `backend/engine/models.py` |
| `backend/engine/phases.py` |
| `backend/engine/game.py` |
| `backend/protocols/schemas.py` |
| `backend/db/models.py` |
| `skills/*.md` |
| `CLAUDE.md` / `AGENTS.md` / `SKILLS.md` |

### Reviewer 必检 checklist

- [ ] 改动符合对应 `skills/` 规范
- [ ] 类型注解齐全（后端）/ i18n 字典更新（前端）
- [ ] 没有把 API Key、Prompt 全文、私有数据写进代码 / commit message
- [ ] 没有引入未在 `requirements.txt` 的依赖
- [ ] 跨模块改动有对应的契约更新
- [ ] AI 生成代码段已被人工通读过（PR 作者负全责）

---

## 四、合并策略

- 默认 **Squash Merge**，PR 标题直接当 commit message
- PR 体积控制：尽量 **< 400 行 diff**，超过的拆 PR
- **不允许 force push 到 main**
- 在自己的 feature 分支上 force push 没问题（rebase 后），但要群里说一声

---

## 五、冲突处理

1. 始终 `git rebase origin/main`，不要 `git merge`（避免 merge commit 污染历史）
2. 冲突时优先保留 main 的逻辑，自己的改动重新叠上
3. `engine/models.py`、`protocols/schemas.py` 冲突 → **群里同步后再解**，不要单方面强解

---

## 六、紧急情况

| 场景 | 操作 |
|------|------|
| main 挂了 | 群里 @全员，回滚提交（`git revert <sha>`），不要 `reset --hard` |
| API Key 误提交 | **立刻**轮换 Key + `git filter-repo` 清历史 + 重写 force push（这次允许） |
| 答辩冻结期需要 hotfix | PR 标题加 `[HOTFIX]`，1 人 approve 即可 merge |

---

## 七、AI 助手在 Git 操作上的红线

> **单人模式覆盖**：第一条"禁止 AI 直接 push 到 main"在单人阶段豁免（见 `CLAUDE.md` 顶部"项目运行模式"）；其他条款仍生效。

- ~~**禁止** AI 直接 `git push` 到 main~~ <sup>单人模式豁免</sup>
- **禁止** AI 自主创建 PR 不告知人类
- **禁止** AI 修改 `.git/`、`.gitignore` 添加排除规则把秘密"藏起来"
- AI 可以：写 commit message 草稿、跑 `git status`/`git diff`/`git log`、在 feature 分支上 commit/push
- AI 修改 commit message 或执行 rebase **必须**人类显式确认

---

*Version 1.0.0 — 2026-05-22 — 初始建立。*
