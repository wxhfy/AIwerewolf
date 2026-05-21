---
name: skills-index
description: AI Werewolf 三人协同开发规范索引——任何 AI 助手（Claude/Codex/其他）开工前先读这里
audience: claude, codex, human
version: 1.0.0
updated: 2026-05-22
---

# AI Werewolf 团队协同开发规范

> 本目录是 **团队协作约定** + **代码风格规范** + **AI 协作纪律** 的集合。
> 与 `/SKILLS.md`（项目开发手册，偏背景知识 + 参考库）**不同**：
> - `SKILLS.md` 回答 **"狼人杀游戏怎么做？"**（领域知识）
> - `skills/` 回答 **"我们三人怎么一起做？"**（协作纪律）

---

## 给 AI 助手的开工指引（**必读**）

不管你是 Claude Code / Codex / 其他模型，**开工前请按以下顺序读**：

| 步骤 | 文件 | 何时读 |
|------|------|--------|
| 1 | `/CLAUDE.md`（Claude）或 `/AGENTS.md`（Codex） | 进入项目第一件事 |
| 2 | `/SKILLS.md` | 接到狼人杀业务相关任务（角色、Phase、Prompt） |
| 3 | `skills/00-team-overview.md` | 接到任何任务都要读，了解分工与节奏 |
| 4 | **本任务相关的规范文件**（见下表） | 动手前对照 checklist |
| 5 | `skills/70-ai-collaboration.md` | 任何由 AI 直接改代码的场景 |

**铁律**：动代码前必须查对应规范；规范没覆盖的边角情况，**先问人，不要自己猜**。

---

## 规范文件索引

| 文件 | 主题 | 谁要读 |
|------|------|--------|
| [`00-team-overview.md`](00-team-overview.md) | 三人横向分工模型、开发节奏、决策权 | **全员必读** |
| [`10-git-workflow.md`](10-git-workflow.md) | 分支 / 提交 / PR / Review 规范 | 全员必读 |
| [`20-backend-conventions.md`](20-backend-conventions.md) | Python / FastAPI / DB / LLM 层代码规范 | 改 `backend/` 的人 |
| [`30-frontend-conventions.md`](30-frontend-conventions.md) | Vanilla JS / i18n / WebSocket / CSS 规范 | 改 `frontend/` 的人 |
| [`40-agent-development.md`](40-agent-development.md) | Agent Protocol / Prompt / 信息隔离 | 改 `backend/agents/` 的人 |
| [`50-api-contract.md`](50-api-contract.md) | REST / WebSocket / Schema 契约与变更流程 | 任何跨前后端的改动 |
| [`60-testing-ci.md`](60-testing-ci.md) | pytest / smoke / PR 必过项 | 全员必读 |
| [`70-ai-collaboration.md`](70-ai-collaboration.md) | 与 Claude/Codex 协作的纪律红线 | **全员必读** |

---

## 文档维护约定

- 每篇文件顶部都有 frontmatter（`name` / `description` / `audience` / `version`）
- 更新规范要 **改完代码同一个 PR 内带上**，不能滞后
- 与现有规范冲突时，**新规范胜出**，但 PR 描述必须显式指出"修改了 skills/xxx.md 第 N 条"
- 删除规范条目同样需要 PR review 通过

---

## 三个常见问题

**Q: 我让 AI 改了一段代码，但它没按 skills/ 里的规范来怎么办？**
→ 看 `70-ai-collaboration.md`。简短答案：**人工把规范引用塞回 prompt，或让 AI 重新读 skills/ 对应文件再改**。不要让不合规的代码进 PR。

**Q: 我改的代码同时涉及前后端，要读哪几个文件？**
→ `20` + `30` + `50`（契约必读）。改 Agent 还要加 `40`。

**Q: 规范和我的判断冲突了怎么办？**
→ 先在 PR 描述里写 **"建议修改 skills/xxx 第 N 条，因为…"**，让另外两人 review。不要静默偏离规范。

---

*Version 1.0.0 — 2026-05-22 — 初始建立，覆盖三人横向分工模式。*
