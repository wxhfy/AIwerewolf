# CI/CD 工程说明

本文档描述仓库当前可执行的 GitHub Actions 流程。CI/CD 的目标不是替代业务测试，而是把“可安装、可测试、可构建、可发布、可回滚”固化为仓库契约。

## 流水线

### CI：每次提交和 Pull Request

.github/workflows/ci.yml 执行四类检查：

1. Python lint 和格式检查。
2. 完整后端测试、依赖一致性检查，以及信息隔离测试所覆盖的契约。
3. 前端依赖安装、ESLint 和生产构建。
4. Docker Compose 语法检查，以及后端和前端生产镜像构建验证。

任何一个 job 失败都不能进入主分支的可发布状态。concurrency 会取消同一分支上已经失去意义的旧 CI，避免浪费 runner。

### Release Images：主分支和版本标签

.github/workflows/release.yml 使用内置 GITHUB_TOKEN 登录 GHCR，并发布两个镜像：

- ghcr.io/<owner>/aiwerewolf-backend:sha-<commit>
- ghcr.io/<owner>/aiwerewolf-frontend:sha-<commit>

主分支额外生成 latest，版本标签（例如 v1.0.0）生成对应版本标签。生产部署应优先使用不可变的 sha-<commit>，回滚只需要重新选择旧 SHA，不会受 latest 漂移影响。

### Deploy Production：显式手动发布

.github/workflows/deploy.yml 仅允许 workflow_dispatch 触发，并绑定 GitHub Environment production。它通过 SSH 在目标机执行 scripts/deploy_remote.sh：

1. 登录 GHCR。
2. 拉取指定 SHA 镜像。
3. 使用 Compose 替换 backend、worker、frontend，不重新构建生产代码。
4. 重启 nginx 并检查 /api/v1/health/ready。

需要配置以下 GitHub Environment secrets/variables：

- Secrets：DEPLOY_HOST、DEPLOY_USER、DEPLOY_SSH_KEY。
- Variable：DEPLOY_PATH，目标机上包含 docker-compose.yml 和生产 .env 的目录。

生产环境应在 GitHub Environment 中配置保护规则。各负责人仍可独立提交和合并，但生产发布必须显式操作。

## 生产机前置条件

目标机需要 Docker Engine、Docker Compose v2、可访问 GHCR 的网络，以及已经准备好的生产 .env。生产 .env 不提交仓库。数据库和 Redis 使用 Compose 持久化卷，PostgreSQL 是持久化事实源，Redis 只承担协调和缓存。

## 回滚

在 Deploy Production 中重新运行 workflow，输入上一个成功发布的 sha-<commit>。部署脚本使用同一套健康检查，检查失败时 workflow 失败。

## 当前边界

这套流程覆盖仓库级 CI、镜像发布和 SSH 生产部署；它不假设某个云厂商或 Kubernetes 集群。后续切换 Kubernetes 时，只需保留 sha-<commit> 镜像契约，把 Deploy job 的最后一步替换为 kubectl set image 或 Helm，并继续复用同一套健康检查和不可变版本策略。
