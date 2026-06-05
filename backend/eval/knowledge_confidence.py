"""Knowledge confidence, access control, and applicability filtering.

Implements the v2 blueprint G15 security architecture:
  ConfidenceAllowed + VisibilityAllowed + NoLeakCurrent + ApplicabilityMatches

Core principle: Not all review conclusions are correct.
  → L0-L4 five-tier confidence hierarchy
  → KnowledgeAccessControl: visibility scope + role/phase restrictions
  → KnowledgeApplicability: when knowledge can be applied
  → 4-filter retrieval pipeline
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


# ================================================================
# L0-L4 Knowledge Confidence
# ================================================================

@dataclass
class KnowledgeConfidence:
    """Five-tier confidence hierarchy for strategy knowledge.

    L0: Verifiable facts — confirmed by engine log directly
    L1: Rule-based conclusions — L0 + rule deduction
    L2: Statistical insights — multi-game stats with sample size
    L3: Strategic judgments — LLM Judge / Reflector single-game evaluation
    L4: Speculative — low consensus or missing evidence
    """

    tier: Literal["L0_fact", "L1_rule", "L2_statistical", "L3_strategic", "L4_speculative"]

    # Confidence metadata
    confidence_score: float | None = None       # 0.0-1.0
    judge_agreement: float | None = None        # inter-judge agreement (L3)
    sample_size: int | None = None              # number of games (L2)
    human_verdict: str | None = None            # "verified" | "rejected" | None
    contradiction_count: int = 0
    times_upvoted: int = 0
    games_since_creation: int = 0

    def is_retrievable(self) -> bool:
        """Check if this confidence level allows retrieval for decision-making."""
        if self.tier == "L4_speculative":
            return False
        if self.human_verdict == "rejected":
            return False
        if self.tier == "L3_strategic":
            if self.judge_agreement is not None and self.judge_agreement < 0.67:
                return False
            if self.confidence_score is not None and self.confidence_score < 0.70:
                return False
        return True


# ================================================================
# Knowledge Access Control
# ================================================================

@dataclass
class KnowledgeAccessControl:
    """Who can see this knowledge during gameplay.

    CRITICAL: L0/L1 facts may still be private (e.g., Seer check results).
    Confidence != Visibility. Both must be satisfied independently.
    """

    visibility_scope: Literal[
        "public",                  # Anyone can see
        "self_private",            # Only the role owner
        "wolf_team_private",       # Only wolf team
        "postgame_only",           # Only after game ends
        "global_deidentified",     # Anyone, with IDs removed
    ]

    source_game_ids: list[str] = field(default_factory=list)
    allowed_roles: list[str] | None = None       # None = all roles
    allowed_phases: list[str] | None = None      # None = all phases
    deidentified: bool = False                    # Player IDs removed
    contains_current_game_private_info: bool = False

    def allows_agent(self, agent_role: str, is_wolf: bool, is_postgame: bool) -> bool:
        """Check if agent with given role/wolf status can access this knowledge."""
        if self.visibility_scope == "public":
            return True
        if self.visibility_scope == "global_deidentified":
            return self.deidentified
        if self.visibility_scope == "postgame_only":
            return is_postgame
        if self.visibility_scope == "self_private":
            return agent_role in (self.allowed_roles or [])
        if self.visibility_scope == "wolf_team_private":
            return is_wolf
        return False


# ================================================================
# Knowledge Applicability
# ================================================================

@dataclass
class KnowledgeApplicability:
    """When does this knowledge apply?

    Strategy knowledge must know when it's applicable to prevent over-generalization.
    Example: "Witch should save first night" only applies when:
      - Current role is Witch
      - Witch has antidote available
      - Someone was killed
      - Rules allow first-night self-save
    """

    role: str | None = None                    # Required role, None = any
    phase: str | None = None                   # Required phase, None = any
    rule_variant: str = "standard_competition_v1"
    min_players: int | None = None
    max_players: int | None = None
    required_public_facts: list[str] = field(default_factory=list)
    forbidden_public_facts: list[str] = field(default_factory=list)
    required_private_state: list[str] = field(default_factory=list)
    strategy_context: list[str] = field(default_factory=list)

    def matches(
        self,
        current_role: str,
        current_phase: str,
        rule_variant: str,
        player_count: int,
        public_facts: set[str],
        private_state: set[str],
    ) -> bool:
        """Check if this knowledge is applicable to the current situation."""
        if self.role is not None and self.role.lower() != current_role.lower():
            return False
        if self.phase is not None and self.phase.upper() != current_phase.upper():
            return False
        if self.rule_variant != rule_variant:
            return False
        if self.min_players is not None and player_count < self.min_players:
            return False
        if self.max_players is not None and player_count > self.max_players:
            return False

        # Required facts must all be present
        for fact in self.required_public_facts:
            if fact not in public_facts:
                return False

        # Forbidden facts must not be present
        for fact in self.forbidden_public_facts:
            if fact in public_facts:
                return False

        # Required private state must be satisfied
        for state in self.required_private_state:
            if state not in private_state:
                return False

        return True


# ================================================================
# Retrieval Filter Pipeline
# ================================================================

def confidence_allowed(doc: dict[str, Any]) -> bool:
    """Check if document's confidence tier allows retrieval for decision-making.

    L4_speculative: never allowed
    Rejected by human: never allowed
    L3_strategic with low agreement/confidence: blocked
    """
    tier = doc.get("confidence_tier", "L3_strategic")
    if tier == "L4_speculative":
        return False
    if doc.get("human_verdict") == "rejected":
        return False
    if tier == "L3_strategic":
        judge_agreement = doc.get("judge_agreement")
        if judge_agreement is not None and judge_agreement < 0.67:
            return False
        confidence = doc.get("confidence_score")
        if confidence is not None and confidence < 0.70:
            return False
    return True


def visibility_allowed(
    doc: dict[str, Any],
    agent_role: str,
    is_wolf: bool,
    is_postgame: bool = False,
) -> bool:
    """Check if agent can see this knowledge based on access control."""
    scope = doc.get("visibility_scope", "public")
    allowed_roles = doc.get("allowed_roles")
    deidentified = doc.get("deidentified", False)

    if scope == "public":
        return True
    if scope == "global_deidentified":
        return deidentified
    if scope == "postgame_only":
        return is_postgame
    if scope == "self_private":
        if allowed_roles is None:
            return True
        return agent_role.lower() in [r.lower() for r in allowed_roles]
    if scope == "wolf_team_private":
        return is_wolf
    return False


def leaks_current_game_private_info(
    doc: dict[str, Any],
    current_game_id: str,
) -> bool:
    """Check if knowledge contains private info from the current game.

    Knowledge generated from the current game must not be retrievable
    by agents still playing that game (prevents information leak via
    knowledge feedback loop).
    """
    if doc.get("contains_current_game_private_info", False):
        return True

    source_game_ids = doc.get("source_game_ids", [])
    if current_game_id in source_game_ids:
        # Knowledge from current game — only safe if deidentified AND
        # visibility scope allows it
        if doc.get("deidentified") and doc.get("visibility_scope") == "global_deidentified":
            return False
        return True

    return False


def applicability_matches(
    doc: dict[str, Any],
    current_role: str,
    current_phase: str,
    rule_variant: str,
    player_count: int,
    public_facts: set[str],
    private_state: set[str],
) -> bool:
    """Check if knowledge applicability conditions match current situation."""
    doc_role = doc.get("applicability_role")
    if doc_role is not None and doc_role.lower() != current_role.lower():
        return False

    doc_phase = doc.get("applicability_phase")
    if doc_phase is not None and doc_phase.upper() != current_phase.upper():
        return False

    doc_rule = doc.get("rule_variant", "standard_competition_v1")
    if doc_rule != rule_variant:
        return False

    min_p = doc.get("min_players")
    if min_p is not None and player_count < min_p:
        return False

    max_p = doc.get("max_players")
    if max_p is not None and player_count > max_p:
        return False

    required_facts = doc.get("required_public_facts", [])
    for fact in required_facts:
        if fact not in public_facts:
            return False

    forbidden_facts = doc.get("forbidden_public_facts", [])
    for fact in forbidden_facts:
        if fact in public_facts:
            return False

    required_state = doc.get("required_private_state", [])
    for state in required_state:
        if state not in private_state:
            return False

    return True


def retrieve_for_agent(
    query: str,
    agent_role: str,
    is_wolf: bool,
    current_game_id: str,
    current_phase: str = "",
    rule_variant: str = "standard_competition_v1",
    player_count: int = 0,
    public_facts: set[str] | None = None,
    private_state: set[str] | None = None,
    is_postgame: bool = False,
    top_k: int = 5,
    all_docs: list[dict[str, Any]] | None = None,
    search_fn: Any = None,
) -> list[dict[str, Any]]:
    """Retrieve strategy knowledge with 4-filter safety pipeline.

    Filters (all must pass):
      1. confidence_allowed — L0-L3 only, no rejected, L3 with high agreement
      2. visibility_allowed — agent role/wolf status can see this
      3. leaks_current_game_private_info — no current-game info leak
      4. applicability_matches — knowledge applies to current situation

    Args:
        query: Search query string.
        agent_role: Current agent's role.
        is_wolf: Whether agent is wolf-aligned.
        current_game_id: Current game ID for leak prevention.
        current_phase: Current game phase.
        rule_variant: Active rule variant name.
        player_count: Number of players in current game.
        public_facts: Set of public facts in current game.
        private_state: Set of private state tags available to agent.
        is_postgame: Whether this is post-game (not live gameplay).
        top_k: Number of results to return.
        all_docs: Pre-loaded document list (avoids DB call).
        search_fn: Function(query, top_k) -> list of scored docs.

    Returns:
        Filtered and reranked list of knowledge documents.
    """
    if public_facts is None:
        public_facts = set()
    if private_state is None:
        private_state = set()

    # Step 1: Get candidates (from search or full list)
    if search_fn is not None:
        candidates = search_fn(query, top_k * 5)
    elif all_docs is not None:
        candidates = all_docs[:top_k * 5]
    else:
        return []

    # Step 2: Apply 4-filter pipeline
    filtered: list[dict[str, Any]] = []
    for doc in candidates:
        if not confidence_allowed(doc):
            continue
        if not visibility_allowed(doc, agent_role, is_wolf, is_postgame):
            continue
        if leaks_current_game_private_info(doc, current_game_id):
            continue
        if not applicability_matches(
            doc, agent_role, current_phase, rule_variant,
            player_count, public_facts, private_state,
        ):
            continue
        if doc.get("status") in ("disputed", "deprecated"):
            continue
        filtered.append(doc)

    # Step 3: Rerank by quality_score then return top_k
    filtered.sort(key=lambda d: d.get("quality_score", 0.0), reverse=True)
    return filtered[:top_k]


# NOTE: decay_confidence() is kept for future use but is NOT currently wired
# into any pipeline (retrieval, evolution, or post-game).  When confidence
# decay is re-enabled, callers should invoke it through a scheduled task or
# as part of the post-game promotion pipeline.
def decay_confidence(doc: dict[str, Any]) -> dict[str, Any]:
    """Apply confidence decay to a knowledge document.

    L3 knowledge degrades if:
      - Not upvoted after 50+ games -> downgrade to L4
      - 3+ contradictions, fewer upvotes than contradictions -> disputed
    """
    tier = doc.get("confidence_tier", "L3_strategic")

    if tier == "L3_strategic":
        games_since = doc.get("games_since_creation", 0)
        times_upvoted = doc.get("times_upvoted", 0)
        contradiction_count = doc.get("contradiction_count", 0)

        if games_since > 50 and times_upvoted == 0:
            doc["confidence_tier"] = "L4_speculative"
            doc["status"] = "deprecated"

        if contradiction_count >= 3 and times_upvoted < contradiction_count:
            doc["confidence_tier"] = "L4_speculative"
            doc["status"] = "disputed"

    return doc
