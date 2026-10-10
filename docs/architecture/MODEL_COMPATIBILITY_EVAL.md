# 跨模型兼容性评测

## 目的

这套评测先验证模型替换不会破坏 Agent 系统契约，不直接比较谁的狼人杀策略更强。

同一个 DecisionRequest 必须在不同模型之间保持一致：

- 角色可见信息一致。
- 合法动作空间一致。
- 输出进入同一个 ActionSpace 校验。
- 模型失败进入同一个安全降级路径。
- 结果拥有统一的错误、延迟和 Harness 事件字段。

## 使用方式

核心 API 位于 backend.eval.model_compatibility：

- evaluate_model(request, client)：运行一个模型。
- summarize_results(results)：聚合多个模型结果。

示例：

    from backend.eval.model_compatibility import evaluate_model
    from backend.eval.model_compatibility import summarize_results

    results = [
        evaluate_model(request, glm_client),
        evaluate_model(request, qwen_client),
        evaluate_model(request, local_client),
    ]
    report = summarize_results(results)

## 指标含义

- action_valid：是否返回了领域可以接受的合法动作。
- fallback_used：是否经过了模型结果修复或降级。
- safe_degradation_used：是否使用了经过环境 ActionSpace 校验的安全动作。
- failure_kind：统一错误类别，如 timeout、rate_limit、authentication、transport、provider_error。
- latency_ms：模型返回中提供的请求延迟。
- harness_event_types：该次请求经历的 Harness 事件，可用于定位失败阶段。

## 评测顺序

1. 使用同一个短 DecisionRequest 验证所有模型都能返回结构化动作。
2. 使用相同角色、相同事件、相同合法选项测试信息隔离。
3. 注入超时、非法 JSON、空响应，确认都能安全降级。
4. 再运行完整多局对局，比较策略质量和观赏性。

兼容性通过不等于策略质量通过。一个模型可以合法完成所有动作，但仍然可能判断浅、发言重复或策略不一致；这些属于后续行为质量评测，而不是模型适配层职责。
