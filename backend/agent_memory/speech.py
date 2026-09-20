from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from backend.agent_memory.models import EvidenceEdge
from backend.agent_memory.models import SpeechClaim

_CLAUSE_RE = re.compile(r"[.!?;,\n\u3002\uff01\uff1f\uff1b\uff0c]+")
_SELF_CLAIM_RE = re.compile(
    r"(?:\u6211\u662f|\u6211\u8df3|\u6211\u8eab\u4efd(?:\u662f|:)|i am|i'm|claiming)",
    re.IGNORECASE,
)
_CHECK_RE = re.compile(
    r"\u67e5\u9a8c|\u9a8c\u4e86|\u9a8c\u8fc7|\u67e5\u6740|\u91d1\u6c34|divin|checked|inspect",
    re.IGNORECASE,
)
_WOLF_RESULT_RE = re.compile(r"\u67e5\u6740|\u662f\u72fc|\u72fc\u4eba|wolf", re.IGNORECASE)
_VILLAGE_RESULT_RE = re.compile(
    r"\u4e0d(?:\u662f|\u50cf)?\u72fc|\u597d\u4eba|\u91d1\u6c34|not\s+(?:a\s+)?wolf|villager",
    re.IGNORECASE,
)
_SUSPICION_RE = re.compile(
    r"\u72fc\u4eba|\u662f\u72fc|\u50cf\u72fc|\u6000\u7591|\u8e29|\u60f3\u6295|\u8981\u51fa|\u5f52\u7968|suspicious",
    re.IGNORECASE,
)
_SUPPORT_RE = re.compile(
    r"\u597d\u4eba|\u91d1\u6c34|\u76f8\u4fe1|\u8ba4\u597d|\u4fdd\u4e00\u4e0b|\u7ad9\u8fb9|\u53ef\u4fe1|\u4e0d\u662f\u72fc|villager|trust",
    re.IGNORECASE,
)
_COMMITMENT_RE = re.compile(
    r"(?:\u6211|\u4eca\u5929|\u8fd9\u8f6e).{0,10}(?:\u6295|\u7968|\u51fa|\u5f52)|will vote|vote for",
    re.IGNORECASE,
)
_RETRACTION_RE = re.compile(
    r"\u6539\u53e3|\u6536\u56de|\u64a4\u56de|\u4e4b\u524d.*\u9519|\u4e0d\u518d\u8ba4\u4e3a|retract|take back",
    re.IGNORECASE,
)

_ROLES = {
    "Seer": ("\u9884\u8a00\u5bb6", "\u9884\u8a00", "seer"),
    "Witch": ("\u5973\u5deb", "witch"),
    "Guard": ("\u5b88\u536b", "guard"),
    "Hunter": ("\u730e\u4eba", "hunter"),
    "Idiot": ("\u767d\u75f4", "idiot"),
    "Villager": ("\u6751\u6c11", "\u5e73\u6c11", "villager"),
    "Werewolf": ("\u72fc\u4eba", "werewolf"),
    "WhiteWolfKing": ("\u767d\u72fc\u738b", "white wolf king"),
}


@dataclass(frozen=True)
class SpeechInterpretation:
    claims: tuple[SpeechClaim, ...]
    edges: tuple[EvidenceEdge, ...]


class SpeechInterpreter:
    """Extract conservative claims and stances from actor-visible speech."""

    def interpret(
        self,
        *,
        event_id: str,
        event_seq: int,
        speaker_id: str,
        speech: str,
        players: list[dict[str, Any]],
        existing_claims: list[SpeechClaim],
    ) -> SpeechInterpretation:
        if not speaker_id or not speech.strip():
            return SpeechInterpretation((), ())
        claims: list[SpeechClaim] = []
        clauses = [item.strip() for item in _CLAUSE_RE.split(speech) if item.strip()]

        role = self._role_in_text(speech)
        if role and _SELF_CLAIM_RE.search(speech):
            claims.append(self._claim(event_id, event_seq, speaker_id, "role_claim", speaker_id, role, 0.0, 0.85, speech))

        for clause in clauses:
            targets = self._targets(clause, players, exclude=speaker_id)
            if not targets:
                continue
            village_result = bool(_VILLAGE_RESULT_RE.search(clause))
            if _CHECK_RE.search(clause):
                value = "village" if village_result else "wolf" if _WOLF_RESULT_RE.search(clause) else "village"
                polarity = 1.0 if value == "wolf" else -1.0
                for target_id in targets:
                    claims.append(
                        self._claim(event_id, event_seq, speaker_id, "check_claim", target_id, value, polarity, 0.82, clause)
                    )
            if _COMMITMENT_RE.search(clause):
                for target_id in targets:
                    claims.append(
                        self._claim(event_id, event_seq, speaker_id, "vote_commitment", target_id, "vote", 0.45, 0.75, clause)
                    )
            if _SUSPICION_RE.search(clause) and not _CHECK_RE.search(clause) and not village_result:
                for target_id in targets:
                    claims.append(
                        self._claim(event_id, event_seq, speaker_id, "stance", target_id, "suspicious", 0.7, 0.62, clause)
                    )
            if (_SUPPORT_RE.search(clause) or village_result) and not _CHECK_RE.search(clause):
                for target_id in targets:
                    claims.append(
                        self._claim(event_id, event_seq, speaker_id, "stance", target_id, "trusted", -0.55, 0.6, clause)
                    )
            if _RETRACTION_RE.search(clause):
                for target_id in targets:
                    claims.append(
                        self._claim(event_id, event_seq, speaker_id, "retraction", target_id, "retracted", 0.0, 0.72, clause)
                    )

        for prior, current in self._contradictions(existing_claims, claims):
            prior.contradicted = True
            current.contradicted = True
            claims.append(
                self._claim(
                    event_id,
                    event_seq,
                    speaker_id,
                    "contradiction",
                    speaker_id,
                    f"{prior.kind}:{prior.value}->{current.value}",
                    0.9,
                    min(prior.confidence, current.confidence),
                    current.evidence_text,
                )
            )

        edges = tuple(
            EvidenceEdge(
                edge_id=f"{claim.claim_id}:edge:{index}",
                event_seq=event_seq,
                source_player_id=speaker_id,
                target_player_id=claim.target_id,
                relation=claim.kind,
                weight=claim.polarity,
                confidence=claim.confidence,
                evidence_text=claim.evidence_text[:500],
            )
            for index, claim in enumerate(claims)
            if claim.target_id
        )
        return SpeechInterpretation(tuple(claims), edges)

    @staticmethod
    def _claim(
        event_id: str,
        seq: int,
        speaker_id: str,
        kind: str,
        target_id: str | None,
        value: str,
        polarity: float,
        confidence: float,
        evidence: str,
    ) -> SpeechClaim:
        suffix = f"{kind}:{target_id or speaker_id}:{value}"
        return SpeechClaim(
            claim_id=f"{event_id}:{suffix}",
            event_seq=seq,
            speaker_id=speaker_id,
            kind=kind,
            target_id=target_id,
            value=value,
            polarity=polarity,
            confidence=confidence,
            evidence_text=evidence[:500],
        )

    @staticmethod
    def _role_in_text(text: str) -> str | None:
        lowered = text.lower()
        for role, aliases in _ROLES.items():
            if any(alias.lower() in lowered for alias in aliases):
                return role
        return None

    @staticmethod
    def _targets(text: str, players: list[dict[str, Any]], *, exclude: str) -> list[str]:
        targets: list[str] = []
        lowered = text.lower()
        for player in players:
            player_id = str(player.get("id") or "")
            if not player_id or player_id == exclude:
                continue
            name = str(player.get("name") or "").strip()
            seat = player.get("seat") or player.get("seat_no")
            matched = bool(name and name.lower() in lowered)
            if seat is not None:
                matched = matched or bool(re.search(rf"(?<!\d){int(seat)}\s*(?:\u53f7|\u865f|\u5ea7|\u4f4d)", text))
            matched = matched or player_id.lower() in lowered
            if matched and player_id not in targets:
                targets.append(player_id)
        return targets

    @staticmethod
    def _contradictions(
        existing: list[SpeechClaim],
        current: list[SpeechClaim],
    ) -> list[tuple[SpeechClaim, SpeechClaim]]:
        contradictions: list[tuple[SpeechClaim, SpeechClaim]] = []
        for claim in current:
            for prior in reversed(existing):
                if prior.speaker_id != claim.speaker_id or prior.contradicted:
                    continue
                if claim.kind == prior.kind == "role_claim" and claim.value != prior.value:
                    contradictions.append((prior, claim))
                    break
                if (
                    claim.kind == prior.kind == "stance"
                    and claim.target_id == prior.target_id
                    and claim.polarity * prior.polarity < 0
                ):
                    contradictions.append((prior, claim))
                    break
        return contradictions
