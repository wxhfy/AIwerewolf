"""VoteQualityFeatures and KillTargetValueFeatures tests."""

from __future__ import annotations

import pytest


def _get_registry():
    from backend.eval.features import register_default_extractors

    return register_default_extractors()


def _get_badcase_vote_opps():
    from backend.eval.opportunity import OpportunityExtractor
    from backend.eval.track_b import ReplayBundleBuilder
    from tests.test_track_b_badcase_wolf_regression import build_badcase_002_fixture

    state = build_badcase_002_fixture()
    bundle = ReplayBundleBuilder().build(state)
    return [op.to_dict() for op in OpportunityExtractor().extract(bundle) if op.opportunity_type == "vote"]


def _get_cleancase_vote_opps():
    from backend.eval.opportunity import OpportunityExtractor
    from backend.eval.track_b import ReplayBundleBuilder
    from tests.test_track_b_cleancase_wolf_regression import build_cleancase_001_fixture

    state = build_cleancase_001_fixture()
    bundle = ReplayBundleBuilder().build(state)
    return [op.to_dict() for op in OpportunityExtractor().extract(bundle) if op.opportunity_type == "vote"]


def test_vote_quality_features_produce_delta():
    """Good vs bad wolf vote should have non-zero feature delta."""
    reg = _get_registry()
    bad_votes = [op for op in _get_badcase_vote_opps() if op["player_id"] == "P2"]
    good_votes = [op for op in _get_cleancase_vote_opps() if op["player_id"] == "P2"]

    assert bad_votes and good_votes, "Need both bad and good vote opportunities"
    bf = reg.extract(bad_votes[0]).features
    gf = reg.extract(good_votes[0]).features

    all_keys = set(list(bf.keys()) + list(gf.keys()))
    deltas = 0
    for k in all_keys:
        bv = bf.get(k, 0)
        gv = gf.get(k, 0)
        if isinstance(bv, (int, float)) and isinstance(gv, (int, float)):
            if abs(float(bv) - float(gv)) > 0.001:
                deltas += 1
    print(f"\n  Vote feature deltas: {deltas}")
    assert deltas >= 5, f"Expected >=5 non-zero deltas, got {deltas}"


def test_kill_target_features_produce_delta():
    """Killing Villager vs Witch should produce different feature values."""
    reg = _get_registry()

    from backend.eval.opportunity import OpportunityExtractor
    from backend.eval.track_b import ReplayBundleBuilder
    from tests.test_track_b_badcase_wolf_regression import build_badcase_002_fixture
    from tests.test_track_b_cleancase_wolf_regression import build_cleancase_001_fixture

    for build_fn in [build_badcase_002_fixture, build_cleancase_001_fixture]:
        state = build_fn()
        bundle = ReplayBundleBuilder().build(state)
        opps = [
            op.to_dict()
            for op in OpportunityExtractor().extract(bundle)
            if op.opportunity_type == "werewolf_kill" and op.day == 2
        ]
        if opps:
            feats = reg.extract(opps[0]).features
            tv = feats.get("kill_target_role_value", 0)
            gap = feats.get("kill_target_value_gap", 0)
            is_high = feats.get("kill_is_high_value", 0)
            print(f"\n  Kill target: role_value={tv:.3f} gap={gap:.3f} is_high={is_high}")

    # Now actually test the delta
    bad_state = build_badcase_002_fixture()
    cc_state = build_cleancase_001_fixture()
    bb = ReplayBundleBuilder().build(bad_state)
    cb = ReplayBundleBuilder().build(cc_state)
    b_opps = [
        op.to_dict()
        for op in OpportunityExtractor().extract(bb)
        if op.opportunity_type == "werewolf_kill" and op.day == 2
    ]
    c_opps = [
        op.to_dict()
        for op in OpportunityExtractor().extract(cb)
        if op.opportunity_type == "werewolf_kill" and op.day == 2
    ]

    assert b_opps and c_opps
    bf = reg.extract(b_opps[0]).features
    gf = reg.extract(c_opps[0]).features
    all_keys = set(list(bf.keys()) + list(gf.keys()))
    deltas = 0
    for k in all_keys:
        bv = bf.get(k, 0)
        gv = gf.get(k, 0)
        if isinstance(bv, (int, float)) and isinstance(gv, (int, float)):
            if abs(float(bv) - float(gv)) > 0.001:
                deltas += 1
    assert deltas >= 5, f"Expected >=5 kill feature deltas, got {deltas}"


def test_vote_features_no_player_id_shortcut():
    """Vote features must not encode fixed player_id values."""
    reg = _get_registry()
    votes = _get_badcase_vote_opps()
    assert votes
    feats = reg.extract(votes[0]).features
    for k, v in feats.items():
        # String values like target_id="P3" are fine — that's data, not a shortcut
        if isinstance(v, str) and v in ("P1", "P2", "P3", "P4", "P5", "P6", "P7"):
            if k == "action_target_id":
                continue  # OK: this is the actual target, not a shortcut
            pytest.fail(f"Feature {k} has hardcoded player_id: {v}")
    # Also check no P1/P2/etc in feature names
    for k in feats:
        assert not k.startswith("P1_"), f"Feature name contains player_id: {k}"


def test_kill_features_preaction_safe():
    """Kill features must not use post-hoc outcome information."""
    reg = _get_registry()
    from backend.eval.opportunity import OpportunityExtractor
    from backend.eval.track_b import ReplayBundleBuilder
    from tests.test_track_b_badcase_wolf_regression import build_badcase_002_fixture

    state = build_badcase_002_fixture()
    bundle = ReplayBundleBuilder().build(state)
    opps = [op.to_dict() for op in OpportunityExtractor().extract(bundle) if op.opportunity_type == "werewolf_kill"]
    assert opps
    feats = reg.extract(opps[0]).features

    # No features should reference post-hoc winner or future game state
    forbidden = ["winner", "future", "post_hoc", "game_result", "after_game"]
    for k in feats:
        for fb in forbidden:
            assert fb not in k.lower(), f"Feature {k} may leak post-hoc info"


def test_extractors_registered():
    """All 4 extractors should be registered by default."""
    reg = _get_registry()
    names = [e["name"] for e in reg.list_extractors()]
    assert "base_action" in names
    assert "private_context" in names
    assert "vote_quality" in names
    assert "kill_target_value" in names
