# 角色注册表扩展指南

`backend/engine/roles/` 是狼人杀角色元数据的唯一事实来源。游戏规则、角色适配器和前端国际化都应通过注册表读取角色定义。

## 目录结构

```text
roles/
├── __init__.py        统一导出并触发角色注册
├── registry.py        RoleSpec、ROLE_REGISTRY 和 register_role
├── basic.py           村民
├── gods.py            预言家、女巫、猎人、守卫
├── wolves.py          狼人、白狼王
├── wolfcha.py         白痴及部分模板角色
└── extensions.py      扩展模板角色
```

每个角色包在导入时调用 `register_role(RoleSpec(...))`。

## 可玩角色和模板角色

- `playable=True`：引擎已经实现完整阶段和行动，可以进入 7～12 人配置。
- `playable=False`：只存在角色元数据，不得进入正式人数配置。

模板角色转为可玩角色时，必须先实现阶段推进、动作空间、信息可见性、结算和测试，然后再修改 `playable`。

## 新增角色步骤

1. 在 `backend/engine/models.py` 的 `Role` 中增加枚举。
2. 在对应角色包注册 `RoleSpec`。
3. 在狼人杀决策适配器中增加角色需要的动作类型和合法动作空间。
4. 增加角色目标、人格和记忆行为所需的领域元数据。
5. 在 `frontend/types/index.ts` 和国际化文件中同步角色名称。
6. 若角色可玩，在 `WOLFCHA_ROLE_CONFIGS` 中增加目标人数配置。
7. 增加阶段、信息隔离、决策和胜负条件测试。

示例：

```python
register_role(
    RoleSpec(
        role=Role.CUPID,
        alignment=Alignment.VILLAGE,
        display_zh="丘比特",
        display_en="Cupid",
        description_zh="首夜指定两名情侣。",
        description_en="Selects two lovers on the first night.",
        wakes_up_at_night=True,
        pack="wolfcha",
        playable=False,
        tags=("lovers", "night-zero"),
    )
)
```

## 验证

`tests/test_role_registry.py` 检查：

- 每个 `Role` 都有对应 `RoleSpec`。
- 正式人数配置只包含可玩角色。
- 重复角色注册会失败。
- 可玩角色具备必要的领域和前端映射。

```bash
pytest tests/test_role_registry.py -v
```
