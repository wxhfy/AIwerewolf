"""Test counterfactual analysis coverage on real game data.

Evaluates:
  1. Hit rate per counterfactual type across N games
  2. Distribution of severities and confidence scores
  3. Coverage gaps — which types never fire and why
  4. Whether current coverage is sufficient for werewolf

Usage:
  python scripts/test_counterfactual_coverage.py --games 20
"""

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.llm.env import load_env_file
load_env_file()


def load_game_state(db, game_id: str):
    """Reconstruct a GameState from database for a finished game."""
    from backend.db.models import Game as DbGame, GameEvent as DbEvent, Player as DbPlayer
    from backend.engine.models import (
        GameState, GameEvent, EventType, Phase, Player,
        Role, Alignment, NightActions,
    )

    game_row = db.query(DbGame).filter(DbGame.id == game_id).first()
    if game_row is None:
        return None

    player_rows = db.query(DbPlayer).filter(DbPlayer.game_id == game_id).all()

    players = []
    for pr in player_rows:
        role = Role(pr.role) if pr.role in Role._value2member_map_ else Role.VILLAGER
        alignment = Alignment.WOLF if role in {Role.WEREWOLF, Role.WHITE_WOLF_KING} else Alignment.VILLAGE
        players.append(Player(
            id=pr.id, name=pr.name, seat=pr.seat_no,
            role=role, alignment=alignment,
            alive=pr.is_alive, is_ai=pr.is_ai,
            agent_type=pr.agent_type or "heuristic",
            model_name=pr.model_name or "",
            death_day=pr.death_day, death_reason=pr.death_reason,
        ))

    state = GameState(
        id=game_id,
        phase=Phase.DAY_SPEECH,
        day=game_row.current_day or 0,
        players=players,
        max_days=8,
    )

    # Load events
    event_rows = (
        db.query(DbEvent)
        .filter(DbEvent.game_id == game_id)
        .order_by(DbEvent.seq)
        .all()
    )
    for er in event_rows:
        try:
            etype = EventType(er.event_type)
        except ValueError:
            continue
        try:
            phase = Phase(er.phase) if er.phase else Phase.DAY_SPEECH
        except ValueError:
            phase = Phase.DAY_SPEECH
        state.events.append(GameEvent(
            id=er.id,
            day=er.day or 0,
            phase=phase,
            type=etype,
            payload=er.content or {},
            ts=float(er.ts or 0),
            visibility=er.visibility or "public",
        ))

    # Set winner (the engine uses winner as a string attribute, or None)
    # GameState.winner is typed as str | None
    state._winner = game_row.winner

    # Set badge holder if available
    for pr in player_rows:
        if hasattr(pr, 'is_badge') and pr.is_badge:
            state.abilities.badge_holder_id = pr.id

    return state


def analyze_game(db, game_id: str, analyzer):
    """Run counterfactual analysis on one game."""
    state = load_game_state(db, game_id)
    if state is None:
        return []

    from backend.eval.review import GameMetrics
    metrics = GameMetrics(
        game_id=game_id, winner=state._winner or "unknown",
        total_days=state.day, total_events=len(state.events),
        wolf_elimination_rate=0.0, village_survival_rate=0.0, info_efficiency=0.0,
    )

    try:
        cases = analyzer.analyze(
            state, metrics,
            bad_cases=[], turning_points=[], review_bonuses=[],
            llm_only=True,
        )
        return cases
    except Exception as e:
        print(f"  WARN: analysis failed for {game_id[:12]}: {e}")
        return []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, default=20, help="Number of games to analyze")
    args = parser.parse_args()

    from backend.db.database import SessionLocal, init_db
    from backend.db.models import Game as DbGame, Player as DbPlayer
    from backend.eval.review import CounterfactualAnalyzer, COUNTERFACTUAL_TYPE_LABELS

    init_db()
    db = SessionLocal()

    try:
        # Sample finished games with LLM players only (avoid heuristic pollution)
        llm_game_ids = set(
            row[0] for row in
            db.query(DbPlayer.game_id)
            .filter(DbPlayer.agent_type.in_(['llm', 'cognitive']))
            .distinct()
            .all()
        )
        game_rows = (
            db.query(DbGame)
            .filter(
                DbGame.status == "finished",
                DbGame.id.in_(llm_game_ids),
            )
            .order_by(DbGame.finished_at.desc())
            .limit(args.games)
            .all()
        )

        if not game_rows:
            print("ERROR: No finished games found")
            return

        print(f"Analyzing {len(game_rows)} games...")
        analyzer = CounterfactualAnalyzer()

        type_counts: Counter = Counter()
        severity_counts: Counter = Counter()
        confidence_scores: dict[str, list[float]] = defaultdict(list)
        total_cases = 0
        games_with_cases = 0

        for i, game_row in enumerate(game_rows):
            cases = analyze_game(db, game_row.id, analyzer)
            if cases:
                games_with_cases += 1

            for case in cases:
                type_counts[case.counterfactual_type] += 1
                severity_counts[case.severity] += 1
                confidence_scores[case.counterfactual_type].append(case.confidence)
                total_cases += 1

            if (i + 1) % 10 == 0:
                print(f"  Progress: {i + 1}/{len(game_rows)} games, {total_cases} cases found")

        # Report
        print(f"\n{'='*70}")
        print(f"COUNTERFACTUAL COVERAGE REPORT ({len(game_rows)} games)")
        print(f"{'='*70}")
        print(f"  Games analyzed: {len(game_rows)}")
        print(f"  Games with cases: {games_with_cases} ({games_with_cases/len(game_rows)*100:.0f}%)")
        print(f"  Total cases: {total_cases}")
        print(f"  Avg cases/game: {total_cases/len(game_rows):.1f}")

        # Per-type breakdown
        print(f"\n{'Type':<20} {'Label':<16} {'Hits':>6} {'Hit%':>7} {'AvgConf':>8} {'Status'}")
        print("-" * 70)

        all_types = set(COUNTERFACTUAL_TYPE_LABELS.keys())
        implemented_types = {
            "vote", "skill", "info_release",     # existing
            "witch_poison", "witch_save", "hunter_shot",  # split
            "guard_target", "seer_target",                # new core
            "speech_strategy", "stance_flip",             # new analysis
            "badge_election",                              # new
        }
        reserved_types = {"claim_timing", "coordination"}

        for ctype in sorted(all_types):
            label = COUNTERFACTUAL_TYPE_LABELS[ctype]
            hits = type_counts.get(ctype, 0)
            hit_rate = hits / len(game_rows) * 100 if len(game_rows) > 0 else 0
            scores = confidence_scores.get(ctype, [])
            avg_conf = sum(scores) / len(scores) if scores else 0

            if hits > 0:
                status = "✅ ACTIVE"
            elif ctype in reserved_types:
                status = "📋 RESERVED"
            elif ctype in implemented_types:
                status = "⚠️  NO HITS"
            else:
                status = "❓ UNKNOWN"

            print(f"  {ctype:<20} {label:<16} {hits:>6} {hit_rate:>6.1f}% {avg_conf:>7.3f}  {status}")

        # Severity distribution
        print(f"\n{'Severity':<15} {'Count':>6} {'Pct':>7}")
        print("-" * 30)
        for sev in ["critical", "major", "moderate", "minor"]:
            count = severity_counts.get(sev, 0)
            pct = count / total_cases * 100 if total_cases else 0
            print(f"  {sev:<15} {count:>6} {pct:>6.1f}%")

        # Coverage assessment
        print(f"\n{'='*70}")
        print("COVERAGE ASSESSMENT")
        print(f"{'='*70}")

        covered = sum(1 for t in implemented_types if type_counts.get(t, 0) > 0)
        total_implemented = len(implemented_types)
        print(f"  Implemented types with hits: {covered}/{total_implemented}")
        print(f"  Coverage rate: {covered/total_implemented*100:.0f}%")

        # Domain coverage analysis
        domains = {
            "投票决策": ["vote"],
            "夜晚技能": ["skill", "witch_poison", "witch_save", "hunter_shot", "guard_target", "seer_target"],
            "信息管理": ["info_release"],
            "发言策略": ["speech_strategy"],
            "立场一致性": ["stance_flip"],
            "警徽/领导力": ["badge_election"],
        }
        print(f"\n  Domain coverage:")
        for domain, types in domains.items():
            hits = sum(type_counts.get(t, 0) for t in types)
            active = sum(1 for t in types if type_counts.get(t, 0) > 0)
            print(f"    {domain}: {active}/{len(types)} types active, {hits} total cases")

        # Gaps
        print(f"\n  Known gaps (need deeper analysis):")
        print(f"    claim_timing: requires speech NLP to detect when role was claimed vs when optimal")
        print(f"    coordination: requires multi-agent simulation of wolf team alternatives")

        # Werewolf-specific assessment
        print(f"\n  Werewolf coverage sufficiency:")
        werewolf_dimensions = {
            "投票反事实 (投票错误)": type_counts.get("vote", 0) > 0,
            "技能反事实 (技能误用)": type_counts.get("skill", 0) > 0 or type_counts.get("witch_poison", 0) > 0,
            "信息反事实 (信息未释放)": type_counts.get("info_release", 0) > 0,
            "守护反事实 (守护失误)": type_counts.get("guard_target", 0) > 0,
            "查验反事实 (查验失误)": type_counts.get("seer_target", 0) > 0,
            "发言反事实 (发言策略问题)": type_counts.get("speech_strategy", 0) > 0,
            "立场反事实 (立场摇摆)": type_counts.get("stance_flip", 0) > 0,
            "警徽反事实 (警徽分配错误)": type_counts.get("badge_election", 0) > 0,
        }
        covered_dims = sum(1 for v in werewolf_dimensions.values() if v)
        total_dims = len(werewolf_dimensions)
        for dim, ok in werewolf_dimensions.items():
            print(f"    {'[OK]' if ok else '[  ]'} {dim}")
        print(f"  Werewolf coverage: {covered_dims}/{total_dims} dimensions covered")

    finally:
        db.close()


if __name__ == "__main__":
    main()
