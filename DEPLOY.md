# AI Werewolf — 部署指南

## 快速开始

```bash
git clone https://github.com/wxhfy/AIwerewolf.git
cd AIwerewolf
cp .env.example .env
# 编辑 .env，填入 API key
```

---

## 方式一：Docker Compose 部署（推荐）

### 前置要求
- Docker >= 24.0
- Docker Compose >= 2.20

### 国内环境（镜像加速）

**1) Docker Hub 镜像**（解决 base image 拉取问题）

编辑 `/etc/docker/daemon.json`：
```json
{
  "registry-mirrors": [
    "https://docker.1ms.run",
    "https://docker.xuanyuan.me"
  ]
}
```
```bash
sudo systemctl daemon-reload && sudo systemctl restart docker
```

**2) 使用国内镜像构建**（pip/npmmirror 加速）

```bash
# 使用覆盖文件（自动配置阿里云 pip 镜像 + npmmirror）
docker compose -f docker-compose.yml -f docker-compose.mirror.yml up -d --build
```

**3) 或者手动传 build-arg**

```bash
docker compose build \
  --build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
  --build-arg PIP_TRUSTED_HOST=mirrors.aliyun.com \
  --build-arg NPM_REGISTRY=https://registry.npmmirror.com
```

### 海外环境 / CI

直接用默认源，无需任何额外配置：
```bash
docker compose up -d --build
```

### 常用命令

```bash
make deploy              # 生产部署（默认源）
make deploy-dev          # 开发模式（热重载）
make deploy-down         # 停止所有
make deploy-logs         # 查看日志
make deploy-status       # 查看状态
```

### 访问地址

| 服务 | 地址 |
|------|------|
| 前端 | http://localhost |
| API | http://localhost/api |
| Swagger | http://localhost/api/docs |
| WebSocket | ws://localhost/ws |

---

## 方式二：本地开发（无 Docker）

### 前置要求
- Python >= 3.12
- Node.js >= 20
- npm >= 10

### 安装

```bash
# 后端
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# 国内加速：pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

# 前端
cd frontend
npm install --legacy-peer-deps
# 国内加速：npm config set registry https://registry.npmmirror.com && npm install --legacy-peer-deps
cd ..
```

### 配置

```bash
cp .env.example .env
# 编辑 .env，至少配置一个 LLM provider
# 不设置 DATABASE_URL → 自动用 SQLite（无需 PostgreSQL）
```

### 启动

```bash
# 终端 1：后端
source .venv/bin/activate
make dev

# 终端 2：前端
cd frontend && PORT=3001 npm run dev
```

- 前端：http://localhost:3001
- API：http://localhost:8000
- Swagger：http://localhost:8000/docs

---

## 方式三：GitHub Actions CI

Push 到 main 或创建 PR 时自动运行：
- **Lint**：ruff check + format check
- **Test**：pytest（fake LLM，不消耗 token）
- **Frontend**：npm lint + build

---

## LLM Provider 配置

在 `.env` 中配置：

### 火山方舟（Doubao）
```env
LLM_PROVIDER=doubao
DOUBAO_API_KEY=<your-key>
DOUBAO_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
DOUBAO_MODEL=Doubao-Seed-2.0-pro
```

### DeepSeek
```env
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=<your-key>
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
```

### OpenAI 兼容接口
通过前端设置面板配置 provider/model/api_key/base_url。

### Fake（测试用）
```env
LLM_PROVIDER=fake
```

---

## 数据库

| 模式 | 说明 |
|------|------|
| SQLite | 不设 DATABASE_URL，自动使用，适合本地开发 |
| PostgreSQL | Docker 部署自动启用，或手动设置 DATABASE_URL |

---

## 常见问题

| 问题 | 解决 |
|------|------|
| Docker build 失败：无法连接 Docker Hub | 配置 daemon.json 镜像源 |
| npm install 超时 | `npm config set registry https://registry.npmmirror.com` |
| pip install 超时 | `pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/` |
| 端口被占用 | 修改 .env 中的 PORT 变量 |
| PostgreSQL 连接失败 | 不设 DATABASE_URL 则自动用 SQLite |

---

## 系统架构

```
┌─────────────┐     ┌─────────────┐     ┌──────────────┐
│   Nginx:80  │────▶│ Frontend    │     │  PostgreSQL  │
│  (反向代理)  │     │ (Next.js)   │     │  (5432)      │
│             │     │  :3001      │     │              │
│             │     └─────────────┘     └──────┬───────┘
│             │                                │
│             │     ┌─────────────┐            │
│             │────▶│ Backend     │◀───────────┘
│             │     │ (FastAPI)   │
│             │     │  :8000      │
└─────────────┘     └─────────────┘
```

## 更多文档

- 项目架构：`docs/ENGINEERING_ARCHITECTURE.md`
- 模块设计：`docs/PROJECT_MODULE_DESIGN.md`
- API 契约：`skills/50-api-contract.md`
