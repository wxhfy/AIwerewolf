import re
from pathlib import Path
from typing import Set

from backend.engine.models import Phase
from backend.engine.models import Role
from backend.engine.roles import ROLE_REGISTRY

WOLFCHA_RUNTIME_PHASES = {
    "SETUP",
    "NIGHT_START",
    "NIGHT_GUARD_ACTION",
    "NIGHT_WOLF_ACTION",
    "NIGHT_WITCH_ACTION",
    "NIGHT_SEER_ACTION",
    "NIGHT_RESOLVE",
    "DAY_START",
    "DAY_BADGE_SIGNUP",
    "DAY_BADGE_SPEECH",
    "DAY_BADGE_ELECTION",
    "DAY_PK_SPEECH",
    "DAY_SPEECH",
    "DAY_LAST_WORDS",
    "DAY_VOTE",
    "DAY_RESOLVE",
    "BADGE_TRANSFER",
    "HUNTER_SHOOT",
    "WHITE_WOLF_KING_BOOM",
    "GAME_END",
}

AIWEREWOLF_FLOW_EXTENSIONS = {
    "DAY_SHERIFF_CLOSING",
}

WOLFCHA_PLAYABLE_ROLES = {
    "Villager",
    "Werewolf",
    "Seer",
    "Witch",
    "Hunter",
    "Guard",
    "Idiot",
    "WhiteWolfKing",
}


def _extract_ts_enum_values(source: str, enum_name: str) -> Set[str]:
    match = re.search(rf"export enum {enum_name}\s*{{(?P<body>.*?)\n}}", source, re.DOTALL)
    assert match, f"Missing TypeScript enum: {enum_name}"
    return set(re.findall(r'=\s*"([^"]+)"', match.group("body")))


def test_backend_phase_set_matches_wolfcha_reference_plus_documented_extensions() -> None:
    backend_phases = {phase.value for phase in Phase}

    assert WOLFCHA_RUNTIME_PHASES <= backend_phases
    assert backend_phases - WOLFCHA_RUNTIME_PHASES == AIWEREWOLF_FLOW_EXTENSIONS


def test_frontend_phase_enum_mirrors_backend_flow_contract() -> None:
    frontend_types = Path("frontend/types/index.ts").read_text(encoding="utf-8")
    frontend_phases = _extract_ts_enum_values(frontend_types, "Phase")

    assert frontend_phases == {phase.value for phase in Phase}


def test_playable_role_set_matches_wolfcha_role_catalog() -> None:
    backend_roles = {role.value for role in Role}
    playable_roles = {role.value for role, spec in ROLE_REGISTRY.items() if spec.playable}

    assert WOLFCHA_PLAYABLE_ROLES <= backend_roles
    assert playable_roles == WOLFCHA_PLAYABLE_ROLES
