# Track B Judge 人工校准

本实现沿用 `calibration.py`、`human_label_validator.py` 和 `LLMJudgePanel`，补齐标注加载、Judge 运行、独立留出集一致性检验、参数落库/导出和运行时回退。`tests/fixtures/judge_calibration_synthetic.json` 是明确标记的合成演示，不能代表真实人工标注质量，也永远不能批准策略自动晋升。

## 标注契约

入口接受一个 JSON 对象：

- `dataset_id`：标注集版本。
- `synthetic`：必须显式为布尔值；真实人工数据为 `false`。
- `annotation_source`：`human` 或 `synthetic`，与来源一致。
- `samples`：非空数组，每项包含 `sample_id`、`game_id`、`annotator_id`、`split`、`confidence`、`human_score`、`decision`、`visible_context`。
- `split`：`train` 或 `validation`。同一个 `game_id` 不得跨集合，避免同局决策污染留出集。
- `confidence`：`high`、`medium`、`low`；低置信人工标签不参与拟合/验证。
- `human_score`：有限的 `[0,1]` 分数。
- `decision`：现有 Per-Step Judge 的决策结构，至少包含 `action_type`、`raw_text`。
- `visible_context.visible_info`：该角色在该决策时真实可见的文本，不能包含事后隐藏真相。

人工标签和标注者元数据不会传给 Judge，只发送决策和角色可见上下文。来源元数据由数据集提供者负责真实声明；代码做结构和来源校验，无法证明一个人实际进行了标注。采集真实标注时仍须保留可审计的标注来源。

## 离线合成演示

从仓库根目录运行（输出写入临时目录）：

```bash
AIWEREWOLF_SKIP_DOTENV=true .venv/bin/python scripts/calibrate_track_b_judge.py \
  --input tests/fixtures/judge_calibration_synthetic.json \
  --provider fake --demo-small --scoring-mode single_step \
  --output /tmp/track-b-calibration-single.json \
  --sqlite-store /tmp/track-b-calibration-demo.sqlite

AIWEREWOLF_SKIP_DOTENV=true .venv/bin/python scripts/calibrate_track_b_judge.py \
  --input tests/fixtures/judge_calibration_synthetic.json \
  --provider fake --demo-small --scoring-mode panel_step \
  --output /tmp/track-b-calibration-panel.json \
  --sqlite-store /tmp/track-b-calibration-demo.sqlite
```

Fake 客户端只读取合成决策中的证据标记，不读取人工标签，并通过现有 `LLMJudgePanel` 的 JSON 协议评分。演示导出包含原始/校准后的 kappa、Pearson/Spearman、偏差和 MAE、固定 Ridge 参数、样本处理状态及内容地址 ID。状态为 `demonstration`，`auto_promotion_allowed=false`。`--demo-small` 只能用于 `synthetic=true` 的数据。

## 真实校准

先通过部署环境注入现有 provider 配置和数据库配置。脚本强制跳过 dotenv，不打印 provider 异常内容。以下路径及模型名均为待替换参数：

```bash
AIWEREWOLF_SKIP_DOTENV=true .venv/bin/python scripts/calibrate_track_b_judge.py \
  --input /path/to/reviewed-human-labels.json \
  --provider bigmodel --judge-model YOUR_CONFIGURED_MODEL \
  --scoring-mode single_step \
  --output /path/to/calibration-single.json --persist

AIWEREWOLF_SKIP_DOTENV=true .venv/bin/python scripts/calibrate_track_b_judge.py \
  --input /path/to/reviewed-human-labels.json \
  --provider bigmodel --judge-model YOUR_CONFIGURED_MODEL \
  --scoring-mode panel_step \
  --output /path/to/calibration-panel.json --persist
```

实际 provider/model 必须与赛后评分使用的客户端一致。单 Judge 和三 Judge 聚合分数分开拟合，不能交换参数。参数是固定的 Ridge 线性映射，单条推断不会按当前批次重新分位数排序。

自动批准要求全部满足：真实人工来源、非 fake Judge、至少 30 条训练样本与 20 条独立留出样本、所有高/中置信标签均完成评分、校准斜率为正、留出集加权 Cohen kappa ≥ 0.60、Pearson/Spearman ≥ 0.70、绝对偏差 ≤ 0.10、MAE ≤ 0.15。Judge 自身置信度低于 0.70 的样本不参与拟合和验证。常量分数的相关性和 kappa 标记为不可计算，不能通过门槛。评分每样本最多尝试 2 次；失败只记录异常类型。

`--persist` 写入现有应用数据库的新表 `judge_calibrations`；`--sqlite-store` 用于显式指定隔离的实验存储，两者互斥。相同内容地址的重试不重复写入，已有 artifact 不允许原地覆盖。没有通过要求的真实标注只能得到 `pending_review`，不批准自动晋升。

## 运行时与 Track C

`post_game.run_post_game_scoring` 以实际客户端的 `provider:model`、当前 `RUBRIC_HASH` 和 `single_step/panel_step` 分别读取通过的校准，注入 `PerStepScorer`。评估版本为 `per-step-v2-calibrated`，决策元数据保留 `judge_calibration`：校准 ID、原始分数、回退原因和待审标记。

以下情况保留确定性规则分：缺校准、校准未通过、模型/量规/模式不匹配、Judge 低置信、返回结构不完整、分数越界或超出训练分数支持区间。三 Judge 的置信度同时考虑有效 Judge 数量、Judge 声明置信度和分数标准差；缺失的 Judge 不会被补成中立分数。

Track C 使用相同的 `latest_approved_calibration` 查询。`TRACK_B_JUDGE_MODEL` 应为实际 `provider:model`，`TRACK_B_JUDGE_SCORING_MODE` 应为 `single_step` 或 `panel_step`。没有匹配的真实人工校准时，策略进入 `pending_review`。这些开关不替代信息隔离、合法动作、角色任务、配对 Seed 和 Bootstrap 安全门槛。

未来仍需采集真实、多角色/场景覆盖的人工标注和定期漂移检测。当前实现支持独立的标注集版本、模型版本、模式及量规身份，未声称已有生产人工校准结果。
