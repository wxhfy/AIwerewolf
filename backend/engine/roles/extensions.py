"""Extension role templates from other werewolf frameworks (lykos /
werewolf-brain / common CN variants).

All ship `playable=False` — registry / LLM / i18n entries exist but the engine
has no phase routing for them yet. Each gets its own follow-up PR to wire up.

  - WOLF_KING — wolf; on any death, shoots one player (like Hunter)
  - KNIGHT — village; daytime duel — point at a player. If wolf, the wolf
    dies; otherwise the knight dies. One-shot.
  - ELDER — village; the first wolf attack on them fails (hard to kill the
    first night).
"""

from __future__ import annotations

from backend.engine.models import Alignment
from backend.engine.models import Role
from backend.engine.roles.registry import RoleSpec
from backend.engine.roles.registry import register_role

register_role(
    RoleSpec(
        role=Role.WOLF_KING,
        alignment=Alignment.WOLF,
        display_zh="狼王",
        display_en="Wolf King",
        description_zh="死亡时可开枪带走一名玩家（被毒杀除外）。",
        description_en="When eliminated (except by poison), shoots one player.",
        wakes_up_at_night=True,
        pack="extensions",
        playable=False,
        tags=("wolf-family", "shoot-on-death"),
    )
)


register_role(
    RoleSpec(
        role=Role.KNIGHT,
        alignment=Alignment.VILLAGE,
        display_zh="骑士",
        display_en="Knight",
        description_zh="白天可发动一次决斗：指认一人，是狼则狼死，是好人则骑士自尽。",
        description_en="Daytime duel (one-shot): point at a player; if wolf, the wolf dies, else the knight dies.",
        pack="extensions",
        playable=False,
        tags=("duel", "one-shot-day"),
    )
)


register_role(
    RoleSpec(
        role=Role.ELDER,
        alignment=Alignment.VILLAGE,
        display_zh="长老",
        display_en="Elder",
        description_zh="第一次被狼人杀害时存活，第二次起会真正死亡。",
        description_en="Survives the first wolf attack; dies normally on subsequent attacks.",
        pack="extensions",
        playable=False,
        tags=("survives-first-attack",),
    )
)
