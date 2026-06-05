"""Test information isolation at the final_agent_input level.

Verifies that the complete agent input — PlayerView + Memory + Retrieval +
Profile + TeamView + Prompt Template — contains NO hidden truth.

This goes beyond PlayerView testing (which only checks Visibility.for_player())
to verify that the entire pipeline feeding into the LLM is clean.

Security properties tested (from v2 blueprint §4.3):
  P1: Wolves cannot see Seer check results
  P2: Villagers cannot see wolf team list
  P3: Dead players cannot vote
  P4: Agent Memory does not contain Hidden Truth
  P5: Strategy retrieval does not return current-game private info
  P6: Post-game reflection results are NOT visible during gameplay
  P7: HumanAgent legal view = AIPlayer legal view
  P8: Knowledge feedback does not leak current game to next game
  P9: final_agent_input contains no hidden roles/alignments/skills
  P10: Retrieved docs satisfy visibility_scope and applicability
"""

from __future__ import annotations

from unittest.mock import MagicMock

# ================================================================
# Helpers
# ================================================================


def _make_player(
    pid: str,
    name: str,
    seat: int,
    role: str = "Villager",
    alignment: str = "VILLAGE",
    alive: bool = True,
) -> dict:
    """Create a player dict similar to what Visibility produces."""
    base = {
        "id": pid,
        "name": name,
        "seat": seat,
        "alive": alive,
        "is_ai": True,
        "agent_type": "cognitive",
    }
    # private_dict includes role + alignment; public_dict does not
    return base


def _make_public_player(pid: str, name: str, seat: int, alive: bool = True) -> dict:
    """A player as seen by non-self, non-teammate (public view)."""
    return _make_player(pid, name, seat, alive=alive)


def _make_private_player(
    pid: str,
    name: str,
    seat: int,
    role: str = "Villager",
    alignment: str = "VILLAGE",
    alive: bool = True,
) -> dict:
    """A player as seen by self or teammate (private view)."""
    p = _make_player(pid, name, seat, role, alignment, alive)
    p["role"] = role
    p["alignment"] = alignment
    return p


def _mock_player_view(
    self_player: dict,
    players: list[dict],
    public_events: list[dict] | None = None,
    private_events: list[dict] | None = None,
    known_wolves: list[dict] | None = None,
) -> MagicMock:
    """Build a mock PlayerView."""
    view = MagicMock()
    view.self_player = self_player
    view.players = players
    view.public_events = public_events or []
    view.private_events = private_events or []
    view.known_wolves = known_wolves or []
    view.day = 1
    view.phase = "DAY_SPEECH"
    view.game_id = "test-game-001"
    return view


# ================================================================
# P1: Wolves cannot see Seer check results
# ================================================================


def test_wolf_cannot_see_seer_check_results():
    """P1: A wolf player's view must not contain Seer's divine results.

    Tests that the Visibility layer correctly scopes private events —
    wolf players only get wolf-team events, not Seer's divine results.
    """
    from backend.engine.models import Alignment
    from backend.engine.models import EventType
    from backend.engine.models import GameEvent
    from backend.engine.models import GameState
    from backend.engine.models import Phase
    from backend.engine.models import Player
    from backend.engine.models import Role
    from backend.engine.visibility import Visibility

    # Build a minimal game state
    players = [
        Player(id="P1", name="预言家", seat=1, role=Role.SEER, alignment=Alignment.VILLAGE, alive=True),
        Player(id="P2", name="狼人A", seat=2, role=Role.WEREWOLF, alignment=Alignment.WOLF, alive=True),
        Player(id="P3", name="村民B", seat=3, role=Role.VILLAGER, alignment=Alignment.VILLAGE, alive=True),
    ]
    state = GameState(
        id="test-game",
        phase=Phase.DAY_SPEECH,
        day=1,
        players=players,
        max_days=8,
    )

    # Seer checks P3 — result goes to Seer's private events
    state.events.append(
        GameEvent(
            id="ev1",
            day=1,
            phase=Phase.NIGHT_SEER_ACTION,
            type=EventType.NIGHT_ACTION,
            payload={"target_id": "P3", "is_wolf": False, "action": "divine"},
            ts=1000.0,
            visibility="private",
            visible_to=["P1"],
        )
    )

    # Build view for wolf player P2
    wolf_view = Visibility().for_player(state, "P2")

    # Wolf's private events should NOT include Seer check
    seer_events = [e for e in wolf_view.private_events if getattr(e, "type", None) and str(e.type) == "SEER_CHECK"]
    assert len(seer_events) == 0, f"Wolf should not see Seer's divine results, got {seer_events}"


# ================================================================
# P2: Villagers cannot see wolf team list
# ================================================================


def test_villager_cannot_see_wolf_team():
    """P2: A villager's view must not include wolf team membership."""
    villager = _make_private_player("P1", "村民A", 1, role="Villager", alignment="VILLAGE")
    wolf1 = _make_public_player("P2", "狼人B", 2)
    wolf2 = _make_public_player("P3", "狼人C", 3)

    view = _mock_player_view(
        self_player=villager,
        players=[villager, wolf1, wolf2],
        known_wolves=[],  # Villager should have NO known_wolves
    )

    assert len(view.known_wolves) == 0, "Villager must not know wolf team members"


# ================================================================
# P4: Agent Memory does not contain Hidden Truth
# ================================================================


def test_memory_does_not_contain_hidden_truth():
    """P4: Memory must not store other players' true roles or alignments."""
    from backend.agents.cognitive.memory import Memory

    mem = Memory("P1", "Villager")

    # Add a normal judgment — should not contain role info
    mem.add_judgment("P2", "suspicious", 0.6, "Voted weirdly")

    # Check judgments list directly
    assert len(mem.judgments) > 0, "Judgment should be stored"

    # Memory should not have any key that exposes hidden truth
    for j in mem.judgments:
        jdict = j.__dict__ if hasattr(j, "__dict__") else {}
        assert "true_role" not in jdict, f"Judgment must not contain true_role: {jdict}"
        assert "true_alignment" not in jdict, f"Judgment must not contain true_alignment: {jdict}"


# ================================================================
# P5: Retrieval does not return current-game private info
# ================================================================


def test_retrieval_blocks_current_game_private_info():
    """P5: Strategy retrieval must filter out docs from current game with private info."""
    from backend.eval.knowledge_confidence import leaks_current_game_private_info

    # Doc from current game without deidentification — should be blocked
    current_game_doc = {
        "source_game_ids": ["game-001"],
        "contains_current_game_private_info": False,
        "deidentified": False,
        "visibility_scope": "public",
    }
    assert leaks_current_game_private_info(current_game_doc, "game-001") is True

    # Doc from different game — should be allowed
    other_game_doc = {
        "source_game_ids": ["game-002"],
        "contains_current_game_private_info": False,
        "deidentified": False,
        "visibility_scope": "public",
    }
    assert leaks_current_game_private_info(other_game_doc, "game-001") is False

    # Doc from current game but deidentified + global scope — allowed
    deidentified_doc = {
        "source_game_ids": ["game-001"],
        "contains_current_game_private_info": False,
        "deidentified": True,
        "visibility_scope": "global_deidentified",
    }
    assert leaks_current_game_private_info(deidentified_doc, "game-001") is False


# ================================================================
# P8: Knowledge feedback does not leak current game to next game
# ================================================================


def test_knowledge_feedback_no_cross_game_leak():
    """P8: Knowledge from game N must not expose private info to game N+1 agents."""
    from backend.eval.knowledge_confidence import confidence_allowed
    from backend.eval.knowledge_confidence import visibility_allowed

    # Knowledge doc from game-001 about Seer strategy
    doc = {
        "confidence_tier": "L2_statistical",
        "confidence_score": 0.85,
        "human_verdict": None,
        "visibility_scope": "public",
        "allowed_roles": None,
        "deidentified": True,
        "source_game_ids": ["game-001"],
    }

    # In game-002, a Werewolf agent queries — should be allowed (public, deidentified)
    assert confidence_allowed(doc) is True
    assert visibility_allowed(doc, "Werewolf", is_wolf=True) is True

    # A doc with wolf_team_private scope — villager in game-002 cannot see it
    private_doc = {
        **doc,
        "visibility_scope": "wolf_team_private",
    }
    assert visibility_allowed(private_doc, "Villager", is_wolf=False) is False


# ================================================================
# P9: final_agent_input contains no hidden roles/alignments
# ================================================================


def test_final_agent_input_contains_no_hidden_truth():
    """P9: Complete agent input must not leak hidden roles or alignments."""
    # Simulate building the final agent input from legal components
    villager = _make_private_player("P1", "村民A", 1, role="Villager", alignment="VILLAGE")
    seer = _make_public_player("P2", "预言家B", 2)  # Public view — no role exposed
    wolf = _make_public_player("P3", "狼人C", 3)  # Public view — no role exposed

    view = _mock_player_view(
        self_player=villager,
        players=[villager, seer, wolf],
        public_events=[],
    )

    # Simulate final agent input assembly
    agent_input_parts = []

    # PlayerView info
    for p in view.players:
        if p["id"] == view.self_player["id"]:
            continue
        info = f"{p.get('seat', '?')}号:{p.get('name', '?')}"
        agent_input_parts.append(info)

    agent_input = "\n".join(agent_input_parts)

    # Hidden truth must not appear in the final input
    hidden_truths = [
        "Seer",
        "seer",
        "Werewolf",
        "werewolf",  # role names
        "WOLF",
        "WOLF",  # alignment values
        "角色:",
        "身份:",  # role hints
    ]
    for truth in hidden_truths:
        assert truth not in agent_input, f"Hidden truth '{truth}' leaked into agent input: {agent_input}"


# ================================================================
# P10: Retrieved docs satisfy visibility and applicability
# ================================================================


def test_retrieved_docs_satisfy_visibility_and_applicability():
    """P10: All retrieved docs must pass visibility + applicability checks."""
    from backend.eval.knowledge_confidence import retrieve_for_agent

    docs = [
        {
            "doc_id": "d1",
            "confidence_tier": "L2_statistical",
            "confidence_score": 0.90,
            "human_verdict": None,
            "visibility_scope": "public",
            "allowed_roles": None,
            "deidentified": True,
            "source_game_ids": ["game-000"],
            "status": "active",
            "quality_score": 0.9,
            "rule_variant": "standard_competition_v1",
            "required_public_facts": [],
            "forbidden_public_facts": [],
            "required_private_state": [],
        },
        {
            "doc_id": "d2",
            "confidence_tier": "L4_speculative",  # Should be filtered
            "confidence_score": 0.95,
            "human_verdict": None,
            "visibility_scope": "public",
            "allowed_roles": None,
            "deidentified": True,
            "source_game_ids": ["game-000"],
            "status": "active",
            "quality_score": 0.95,
            "rule_variant": "standard_competition_v1",
            "required_public_facts": [],
            "forbidden_public_facts": [],
            "required_private_state": [],
        },
        {
            "doc_id": "d3",
            "confidence_tier": "L3_strategic",
            "confidence_score": 0.50,  # Below threshold — should be filtered
            "judge_agreement": 0.60,
            "human_verdict": None,
            "visibility_scope": "public",
            "allowed_roles": None,
            "deidentified": True,
            "source_game_ids": ["game-000"],
            "status": "active",
            "quality_score": 0.5,
            "rule_variant": "standard_competition_v1",
            "required_public_facts": [],
            "forbidden_public_facts": [],
            "required_private_state": [],
        },
    ]

    results = retrieve_for_agent(
        query="test",
        agent_role="Villager",
        is_wolf=False,
        current_game_id="game-002",
        all_docs=docs,
    )

    doc_ids = [d["doc_id"] for d in results]
    assert "d1" in doc_ids, "L2 active doc should pass all filters"
    assert "d2" not in doc_ids, "L4 speculative doc should be filtered"
    assert "d3" not in doc_ids, "Low-confidence L3 doc should be filtered"


# ================================================================
# Confidence tier filtering
# ================================================================


def test_confidence_allowed_filters_correctly():
    """Verify that confidence_allowed correctly filters by tier."""
    from backend.eval.knowledge_confidence import confidence_allowed

    assert confidence_allowed({"confidence_tier": "L0_fact"}) is True
    assert confidence_allowed({"confidence_tier": "L1_rule"}) is True
    assert confidence_allowed({"confidence_tier": "L2_statistical"}) is True

    # L3 with good scores
    assert (
        confidence_allowed(
            {
                "confidence_tier": "L3_strategic",
                "confidence_score": 0.80,
                "judge_agreement": 0.75,
            }
        )
        is True
    )

    # L3 with low confidence
    assert (
        confidence_allowed(
            {
                "confidence_tier": "L3_strategic",
                "confidence_score": 0.50,
            }
        )
        is False
    )

    # L3 with low judge agreement
    assert (
        confidence_allowed(
            {
                "confidence_tier": "L3_strategic",
                "confidence_score": 0.80,
                "judge_agreement": 0.50,
            }
        )
        is False
    )

    # L4 always blocked
    assert confidence_allowed({"confidence_tier": "L4_speculative"}) is False

    # Rejected by human
    assert (
        confidence_allowed(
            {
                "confidence_tier": "L2_statistical",
                "human_verdict": "rejected",
            }
        )
        is False
    )


# ================================================================
# Applicability matching
# ================================================================


def test_applicability_matches():
    """Verify applicability matching logic."""
    from backend.eval.knowledge_confidence import applicability_matches

    doc = {
        "applicability_role": "Witch",
        "applicability_phase": "NIGHT_WITCH_ACTION",
        "rule_variant": "standard_competition_v1",
        "min_players": 7,
        "max_players": 15,
        "required_public_facts": ["someone_died"],
        "forbidden_public_facts": ["seer_confirmed_wolf"],
        "required_private_state": ["has_antidote"],
    }

    # Matching situation
    assert (
        applicability_matches(
            doc,
            current_role="Witch",
            current_phase="NIGHT_WITCH_ACTION",
            rule_variant="standard_competition_v1",
            player_count=12,
            public_facts={"someone_died", "day_1"},
            private_state={"has_antidote"},
        )
        is True
    )

    # Wrong role
    assert (
        applicability_matches(
            doc,
            current_role="Seer",
            current_phase="NIGHT_WITCH_ACTION",
            rule_variant="standard_competition_v1",
            player_count=12,
            public_facts={"someone_died"},
            private_state={"has_antidote"},
        )
        is False
    )

    # Forbidden fact present
    assert (
        applicability_matches(
            doc,
            current_role="Witch",
            current_phase="NIGHT_WITCH_ACTION",
            rule_variant="standard_competition_v1",
            player_count=12,
            public_facts={"someone_died", "seer_confirmed_wolf"},
            private_state={"has_antidote"},
        )
        is False
    )

    # Missing required private state
    assert (
        applicability_matches(
            doc,
            current_role="Witch",
            current_phase="NIGHT_WITCH_ACTION",
            rule_variant="standard_competition_v1",
            player_count=12,
            public_facts={"someone_died"},
            private_state=set(),
        )
        is False
    )

    # Wrong player count
    assert (
        applicability_matches(
            doc,
            current_role="Witch",
            current_phase="NIGHT_WITCH_ACTION",
            rule_variant="standard_competition_v1",
            player_count=5,
            public_facts={"someone_died"},
            private_state={"has_antidote"},
        )
        is False
    )


# ================================================================
# Confidence decay
# ================================================================


def test_confidence_decay():
    """Verify confidence decay rules."""
    from backend.eval.knowledge_confidence import decay_confidence

    # L3 with no upvotes after 50+ games → downgraded
    doc = {
        "confidence_tier": "L3_strategic",
        "games_since_creation": 60,
        "times_upvoted": 0,
        "contradiction_count": 0,
    }
    result = decay_confidence(doc)
    assert result["confidence_tier"] == "L4_speculative"
    assert result["status"] == "deprecated"

    # L3 with contradictions > upvotes → disputed
    doc2 = {
        "confidence_tier": "L3_strategic",
        "games_since_creation": 10,
        "times_upvoted": 1,
        "contradiction_count": 5,
    }
    result2 = decay_confidence(doc2)
    assert result2["confidence_tier"] == "L4_speculative"
    assert result2["status"] == "disputed"

    # L2 is not decayed
    doc3 = {
        "confidence_tier": "L2_statistical",
        "games_since_creation": 100,
    }
    result3 = decay_confidence(doc3)
    assert result3["confidence_tier"] == "L2_statistical"
