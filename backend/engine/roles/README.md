# Role Registry — extension guide

The role registry under `backend/engine/roles/` is the single source of truth
for werewolf role metadata. Every other layer (engine rules, LLM prompts,
agent profiles, frontend i18n) reads through it.

## Layout

```
backend/engine/roles/
├── __init__.py        # re-exports + imports each pack module (triggers registration)
├── registry.py        # RoleSpec dataclass + ROLE_REGISTRY + register_role()
├── basic.py           # VILLAGER
├── gods.py            # SEER, WITCH, HUNTER, GUARD (神职)
├── wolves.py          # WEREWOLF, WHITE_WOLF_KING
├── wolfcha.py         # IDIOT (playable), CUPID + BIG_BAD_WOLF + WOLF_CUB (templates)
└── extensions.py      # WOLF_KING, KNIGHT, ELDER (templates)
```

Each pack module calls `register_role(RoleSpec(...))` at import time.
`__init__.py` imports them all so `from backend.engine.roles import
ROLE_REGISTRY` works without manual wiring.

## Playable vs template

- `playable=True` — the engine has full phase routing for this role and it
  can appear in `WOLFCHA_ROLE_CONFIGS` (the locked 7-12P seat configs).
- `playable=False` — the role exists in the registry and has LLM strategy
  text + i18n, but the engine doesn't yet route its abilities. The role is
  excluded from `get_playable_roles()` and `WOLFCHA_ROLE_CONFIGS` MUST NOT
  contain it (validated at import time in `engine/rules.py`).

This split lets us ship role *templates* (Cupid, Wolf King, Knight, Elder,
Big Bad Wolf, Wolf Cub) without breaking the locked 7-12P configs. Promoting
a template to playable is a follow-up PR that wires the engine logic, then
flips the flag.

## Adding a new role

1. **Add the enum member** in `backend/engine/models.py`:
   ```python
   class Role(str, Enum):
       ...
       CUPID = "Cupid"
   ```

2. **Register the spec.** Either add to an existing pack file or create a
   new one and import it from `roles/__init__.py`:
   ```python
   register_role(RoleSpec(
       role=Role.CUPID,
       alignment=Alignment.VILLAGE,
       display_zh="丘比特",
       display_en="Cupid",
       description_zh="第 0 夜指定两名情侣...",
       description_en="Night 0 picks two lovers...",
       wakes_up_at_night=True,
       pack="wolfcha",
       playable=False,  # template only — engine wiring is TODO
       tags=("lovers", "night-zero"),
   ))
   ```

3. **Add LLM strategy.** Three layers in `backend/agents/`:
   - `playbooks.py` — `ACTION_PLAYBOOKS[Role.CUPID] = ActionPlaybook(...)`
   - `profiles.py` — `ROLE_PROFILES[Role.CUPID] = RoleProfile(...)`
   - `prompts.py` — entry in `ROLE_SYSTEM_PROMPTS`; per-action entries in
     `ACTION_STRATEGIES` are optional (VILLAGER fallback exists).

4. **Mirror on frontend.** `frontend/types/index.ts` adds the enum value and
   `frontend/lib/i18n.ts` adds zh + en translations.

5. **If promoting to `playable=True`:** wire the engine phases in
   `backend/engine/game.py` and add the role to `WOLFCHA_ROLE_CONFIGS`
   entries that want it. New action types go in
   `backend/engine/models.py` (`ActionType` enum) and
   `backend/engine/actions.py` (`ACTION_RULES`).

## Tests

`tests/test_role_registry.py` enforces the contract:
- Every `Role` enum member has a `RoleSpec` (no half-added roles)
- Every `Role` has profile / prompt / playbook entries (no KeyErrors)
- `WOLFCHA_ROLE_CONFIGS` contains only playable roles
- `register_role()` rejects duplicate registration

Run with: `pytest tests/test_role_registry.py -v`
