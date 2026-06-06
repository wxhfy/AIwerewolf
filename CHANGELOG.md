# Changelog

All notable changes to AI Werewolf.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versioning follows [Semantic Versioning](https://semver.org/).

## [0.1.0] — 2025-06-05

### Added

- **CognitiveAgent** — Observe-Think-Act architecture with LLM reasoning, BeliefTracker, and Strategy Bias
- **AgentLoop** — native function-calling with 6 tools (search_strategies, check_rules, query_game_state, query_player, query_role, record_note) and max 3 iterations
- **6 role strategies** — Villager, Werewolf, Seer, Witch, Hunter, Guard with independent strategy cards
- **32 named characters** with MBTI-based persona system
- **WolfTeamView** — secure wolf coordination with private team communication
- **4-Filter safety pipeline** — confidence_allowed → visibility_allowed → no_current_game_leak → applicability_matches
- **Three-tier scoring cascade** — Tier 1 (heuristic) → Tier 2 (heuristic fallback) → Tier 3 (LLM Judge Panel)
- **CounterfactualAnalyzer** — replay-based counterfactual analysis for post-game review
- **Knowledge lifecycle** — L0-L4 confidence levels with candidate → active → deprecated states
- **Replay Viewer** — structured post-game replay with decision traces
- **HumanAgent** — real-person participation in AI games
- **WebSocket API** — real-time game state streaming to frontend
- **Frontend** — Next.js 15 observer UI with Tailwind CSS
- **21 PostgreSQL tables** — games, players, decisions, events, strategies, and audit trails

### Engine

- Complete Werewolf game loop with 15+ phase transitions
- Strict information isolation (92 boundary checks verified)
- Rule variant system (standard / custom / demo)
- Game state snapshots with full audit history
- Resume support from any phase

### Evaluation & Evolution

- LLM Judge Panel (3 judges + critic round)
- Track B publishing pipeline with structured reports
- Knowledge abstraction from post-game reviews
- A/B leaderboard for strategy comparison
- MBTI × Role win-rate analysis

### Developer Experience

- Preflight check (7 items: imports, DB, LLM, strategies, pool)
- Strict mode flags for deterministic testing
- Multi-tier experiment framework
- Retrieval policy ablation scripts
