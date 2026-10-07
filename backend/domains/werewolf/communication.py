from __future__ import annotations

import re
from dataclasses import dataclass

from backend.agent_harness.contracts import DecisionRequest


@dataclass(frozen=True)
class SpeechAudit:
    speech: str
    violations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def accepted(self) -> bool:
        return not self.violations


_INTERNAL_SCORE_PATTERNS = (
    re.compile(
        r"(?:wolf\s+probability|狼人概率|狼概率|suspicion[_\s-]*score|confidence|置信度)"
        r"\s*(?:为|是|[:=])?\s*(?:0(?:\.\d+)?|1(?:\.0+)?|\d{1,3}\s*%)",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:0\.\d{2,}|1\.0{2,})\b"),
)

_WOLF_PERSPECTIVE_PATTERNS = (
    re.compile(r"我们(?:的)?狼队|我(?:们)?(?:作为|是)狼人|狼队友|狼人队友"),
    re.compile(r"(?:作为|身为)狼人"),
    re.compile(r"(?:保护|维护).{0,12}(?:我们|狼队).{0,8}(?:团队|阵营|身份)"),
    re.compile(r"(?:相信|支持|希望).{0,6}狼队.{0,20}(?:找到|带领|获胜|成功|真相)"),
    re.compile(r"(?:保护|帮助|配合).{0,8}狼队"),
    re.compile(r"(?:引导|转移|将).{0,16}(?:公众|大家|好人).{0,12}(?:怀疑|注意).{0,12}(?:非狼人|好人|村民)"),
    re.compile(r"不要.{0,12}(?:暴露|泄露).{0,12}(?:我们|自己).{0,8}(?:身份|阵营)"),
    re.compile(r"\b(?:our|my)\s+(?:wolf\s+)?team(?:mate)?\b", re.IGNORECASE),
    re.compile(r"\bwe\s+(?:wolves|werewolves)\b", re.IGNORECASE),
    re.compile(r"\bas\s+(?:a\s+)?werewolf\b", re.IGNORECASE),
    re.compile(
        r"\b(?:attacked|killed|targeted)\b.{0,20}\bby\s+us\b.{0,20}\b(?:last\s+night|at\s+night)\b",
        re.IGNORECASE,
    ),
    re.compile(r"(?:狼队|狼人).{0,24}(?:昨晚|夜里|夜间).{0,24}(?:讨论|决定|刀|击杀|攻击)"),
    re.compile(r"(?:昨晚|夜里|夜间).{0,24}(?:我们|狼队).{0,24}(?:讨论|决定|刀|击杀|攻击)"),
    re.compile(r"(?:昨晚|夜里|夜间).{0,20}(?:狼队|狼人).{0,20}(?:目标|刀口|击杀|攻击|成功)"),
    re.compile(r"(?:我们|狼队).{0,20}(?:目标|昨晚|夜里).{0,20}(?:成功|击杀|攻击|刀)"),
    re.compile(r"(?:我们|狼队|团队|队伍).{0,10}(?:讨论|决定).{0,24}(?:目标|攻击|击杀|刀)"),
)

_WOLF_PRIVATE_HARD_PATTERNS = (
    _WOLF_PERSPECTIVE_PATTERNS[0],
    _WOLF_PERSPECTIVE_PATTERNS[1],
    _WOLF_PERSPECTIVE_PATTERNS[7],
    _WOLF_PERSPECTIVE_PATTERNS[8],
    _WOLF_PERSPECTIVE_PATTERNS[9],
    _WOLF_PERSPECTIVE_PATTERNS[10],
    _WOLF_PERSPECTIVE_PATTERNS[11],
    _WOLF_PERSPECTIVE_PATTERNS[12],
    _WOLF_PERSPECTIVE_PATTERNS[13],
    _WOLF_PERSPECTIVE_PATTERNS[14],
    _WOLF_PERSPECTIVE_PATTERNS[15],
)

_WOLF_STRATEGIC_CLAIM_PATTERNS = tuple(
    pattern for pattern in _WOLF_PERSPECTIVE_PATTERNS if pattern not in _WOLF_PRIVATE_HARD_PATTERNS
)
_WITCH_PRIVATE_PATTERNS = (
    re.compile(r"(?:我|本人).{0,16}(?:昨晚|夜里|夜间).{0,24}(?:解药|毒药|药水|救|毒|保留)"),
    re.compile(r"(?:昨晚|夜里|夜间).{0,24}(?:我|本人).{0,24}(?:解药|毒药|药水|救|毒|保留)"),
    re.compile(r"(?:我|本人).{0,16}(?:不使用|没有使用|保留|用掉|使用).{0,8}(?:解药|毒药|药水)"),
    re.compile(r"\bI\b.{0,24}\b(?:saved|poisoned|kept|used)\b.{0,16}\b(?:potion|antidote|poison)?\b", re.IGNORECASE),
)

_GUARD_PRIVATE_PATTERNS = (
    re.compile(r"(?:我|本人).{0,16}(?:昨晚|夜里|夜间).{0,20}(?:守|守护|保护)"),
    re.compile(r"(?:昨晚|夜里|夜间).{0,20}(?:我|本人).{0,20}(?:守|守护|保护)"),
    re.compile(r"\bI\b.{0,20}\bguarded\b", re.IGNORECASE),
)

_FIRST_PERSON_CHECK_PATTERNS = (
    re.compile(r"(?:我|本人).{0,12}(?:昨晚|夜里|夜间)?.{0,8}(?:查验|验了|验人|查了)"),
    re.compile(r"我的.{0,6}(?:查验|验人)(?:结果|信息)?"),
    re.compile(r"\b(?:I\s+checked|my\s+check|my\s+inspection)\b", re.IGNORECASE),
)

_FIRST_PERSON_GUARD_PATTERNS = (
    re.compile(r"(?:我|本人).{0,12}(?:昨晚|晚上|夜里|夜间).{0,12}(?:守了|守护了|保护了|守护|保护)"),
    re.compile(r"(?:昨晚|晚上|夜里|夜间).{0,12}(?:我|本人).{0,12}(?:守了|守护了|保护了|守护|保护)"),
    re.compile(r"\bI\b.{0,20}\b(?:guarded|protected)\b.{0,20}\b(?:last night|at night)\b", re.IGNORECASE),
)

_FIRST_PERSON_WITCH_PATTERNS = (
    re.compile(r"(?:我|本人).{0,12}(?:昨晚|晚上|夜里|夜间).{0,16}(?:用了解药|用了毒药|救了|毒了)"),
    re.compile(r"(?:昨晚|晚上|夜里|夜间).{0,12}(?:我|本人).{0,16}(?:用了解药|用了毒药|救了|毒了)"),
    re.compile(r"\bI\b.{0,20}\b(?:saved|poisoned)\b.{0,20}\b(?:last night|at night)\b", re.IGNORECASE),
)


def public_communication_policy(request: DecisionRequest) -> dict[str, object]:
    role = str(request.domain_metadata.get("role") or "")
    return {
        "channel": "public_speech",
        "role": role,
        "rules": [
            "Keep private reasoning separate from the public speech field.",
            "Do not reveal wolf-team membership, wolf chat, or private internal state as a fact.",
            "Never print internal probabilities, confidence values, scores, raw player IDs, or system terminology.",
            "Ground accusations in public speeches, public votes, public deaths, and observable contradictions.",
            "You may claim a role, bluff a night action, hedge, or deliberately mislead; other players judge the claim from public evidence.",
            "If you disclose a true private fact, do so only as an intentional strategic claim, not as hidden system reasoning.",
        ],
        "strategic_latitude": [
            "role_claims",
            "fake_checks",
            "fake_guard_claims",
            "fake_potion_claims",
            "conditional_accusations",
            "vote_commitments",
        ],
    }


def audit_public_speech(request: DecisionRequest, speech: str) -> SpeechAudit:
    normalized = _replace_internal_player_ids(request, str(speech or "").strip())
    violations: list[str] = []
    warnings: list[str] = []
    if not normalized:
        violations.append("empty_speech")
        return SpeechAudit(normalized, tuple(violations), tuple(warnings))

    if any(pattern.search(normalized) for pattern in _INTERNAL_SCORE_PATTERNS):
        violations.append("internal_score_disclosure")

    role = str(request.domain_metadata.get("role") or "").lower()
    if role in {"werewolf", "whitewolfking"} and any(
        pattern.search(normalized) for pattern in _WOLF_PRIVATE_HARD_PATTERNS
    ):
        violations.append("wolf_private_perspective")
    if role in {"werewolf", "whitewolfking"} and any(
        pattern.search(normalized) for pattern in _WOLF_STRATEGIC_CLAIM_PATTERNS
    ):
        warnings.append("wolf_strategic_claim")
    if any(pattern.search(normalized) for pattern in _WITCH_PRIVATE_PATTERNS):
        warnings.append("witch_night_action_claim")
    if any(pattern.search(normalized) for pattern in _GUARD_PRIVATE_PATTERNS):
        warnings.append("guard_night_action_claim")
    if role != "seer" and any(pattern.search(normalized) for pattern in _FIRST_PERSON_CHECK_PATTERNS):
        warnings.append("role_capability_claim")
    if role != "guard" and any(pattern.search(normalized) for pattern in _FIRST_PERSON_GUARD_PATTERNS):
        warnings.append("role_capability_claim")
    if role != "witch" and any(pattern.search(normalized) for pattern in _FIRST_PERSON_WITCH_PATTERNS):
        warnings.append("role_capability_claim")

    return SpeechAudit(normalized, tuple(dict.fromkeys(violations)), tuple(dict.fromkeys(warnings)))


def _replace_internal_player_ids(request: DecisionRequest, speech: str) -> str:
    observation = request.information_state.observation
    players = list(observation.get("players") or [])
    self_player = observation.get("self_player") or {}
    if self_player:
        players.append(self_player)
    result = speech
    for player in players:
        player_id = str(player.get("id") or "").strip()
        name = str(player.get("name") or "").strip()
        if player_id and name and player_id != name:
            result = result.replace(player_id, name)
    return result
