# Track B/C 离线分析与晋升

本轮实现沿用现有复盘、知识文档、Patch、Tournament 与 AcceptancePolicy；实时 Match Worker 与 `/api/rooms/{id}/action` 的异步命令契约不变。

## 人工校准闭环

`scripts/calibrate_track_b_judge.py` 加载显式标注集，调用现有 Judge，按对局隔离训练集和验证集，导出加权 Cohen kappa、Pearson/Spearman 相关、偏差和 MAE，以及固定的评分变换参数。标注格式及小型示例在 `tests/fixtures/`，示例明确为合成数据。完整命令和配置见 [`TRACK_B_JUDGE_CALIBRATION.md`](TRACK_B_JUDGE_CALIBRATION.md)。

校准记录持久化在 `judge_calibrations`，按 Judge 模型、rubric 和评分模式匹配。真实人工来源、足量独立留出样本及一致性门槛同时满足才允许自动晋升；合成标注和 fake Judge 只能演示，不能授权生产晋升。缺少批准记录、Judge 低置信、模型或 rubric 不匹配、评分超出校准支持区间时，使用规则评分并标记待审。

默认生产样本下限为 30 条训练、20 条验证；kappa ≥ 0.60，Pearson/Spearman ≥ 0.70，绝对偏差 ≤ 0.10，MAE ≤ 0.15。CLI 的小样本演示模式不能降低生产晋升下限。

## Track C DAG

`TrackCCoordinator.execute(game_id, reports=None, request_id=None)` 消费已批准复盘，依次保存证据、候选 Patch、红队检查、配对 Tournament 和晋升门槛的结构化 Artifact。任务和节点有持久幂等键，完成的节点可在失败恢复时复用；租约 token 阻止过期执行者继续写入。

Tournament Worker 使用独立游戏与 Harness，baseline/candidate 使用相同 Seed、座位、角色、人格及模型配置。Worker 返回结构化数据，不写活动策略或对局 Outbox。`TRACK_C_CONCURRENCY` 配置并发度（默认 2）；`TRACK_C_SEEDS` 可设逗号分隔 Seed，生产默认 20 个配对 Seed；fake 默认只跑 3 个 smoke Seed。fake provider 可执行完整 DAG，但结果只能待审。

`TRACK_C_PLAYER_COUNT` 可指定人数，默认选择包含目标角色的最小 7–12 人配置；`TRACK_C_MAX_DAYS` 默认 20。Judge 身份使用 `TRACK_B_JUDGE_MODEL=provider:model` 和 `TRACK_B_JUDGE_SCORING_MODE=single_step|panel_step`，并匹配当前 rubric hash。

晋升由 Coordinator 串行执行：先验证信息泄漏、非法动作、Fallback、角色任务等安全门槛，再应用现有 Bootstrap 区间、平均提升及非退化比例判定，最后要求匹配的人工 Judge 校准。活动角色版本使用比较并交换，基线已变化时须重新实验。旧 evolution cycle 只返回候选及对比结果，不能成为第二个自动晋升写入者。未通过晋升的新策略知识进入 `pending_review`，不进入实时检索。

## 重试与运维

- 终局事务始终保存分析任务与 Outbox 事实。`ANALYSIS_ENABLED` 控制消费，不删除待分析事实。
- Analysis Worker 执行 Track B、保存阶段 checkpoint，再接入 Coordinator。失败采用可观察的重试与退避，耗尽预算进入死信；已完成阶段避免重跑。
- `GET /api/v1/matches/{id}/analysis` 查看任务、阶段和演化结果。持久任务的兼容状态仍为 `completed`；公开 `lifecycle_status` 使用 `pending/running/published/failed`。
- `POST /api/v1/matches/{id}/analysis/retry` 支持 `Idempotency-Key`。不存在的对局、未结束对局和正在运行的任务使用不同错误码。
- `GET /api/games/{id}/reviews/status` 保留前端 `ready/pending` 字段，并增加明确生命周期和重试信息。报告未就绪返回 `425 analysis_not_ready` 和 `Retry-After`，失败返回 `409 analysis_failed`，不存在返回 `404 match_not_found`。
- `GET /api/v1/health/workers` 返回跨进程持久心跳及过期状态；Match/Analysis Worker 在长任务期间也刷新心跳。
- `GET /api/v1/system/metrics` 返回进程内计数器及数据库分析/Outbox 队列状态。计数器作用域明确为单进程，不作为跨实例总量。
- 请求和任务日志携带 `match_id/room_id/request_id`，不包含请求体、查询参数、认证头或任意异常内容。API 错误统一为 `application/problem+json`。

新表沿用项目当前 `init_db()` 建表；复用数据库的兼容字段使用加法迁移。尚未替代为统一 Alembic 迁移链，也未引入 Prometheus/OpenTelemetry 或分布式 Tournament 消息队列。

验证时设置 `AIWEREWOLF_SKIP_DOTENV=true` 并使用 fake provider 和测试数据库。不要以测试中的合成数据或 fake 胜率声称生产校准、策略提升或模型质量。
