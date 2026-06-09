"""Pinpoint test: can ReviewRepairLoop turn an evidence-stripped report
back into publishable state when ALL other inputs (markdown, scoreboard) are
intact? This isolates the 'fallback shortcut' question — i.e. whether the
repair loop is a real fix or just a soft-pass.
"""

from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("AIWEREWOLF_DB_URL", "sqlite:///:memory:")

from backend.engine.game import WerewolfGame
from backend.eval.review import generate_review_report
from backend.eval.track_b import ReplayBundleBuilder
from backend.eval.track_b import ReviewRepairLoop
from backend.eval.track_b import SpeechActAnalyzer
from backend.eval.track_b import SuspicionMatrixBuilder
from backend.eval.track_b import TrackBValidator


def run_one(seed: int) -> dict:
    g = WerewolfGame(seed=seed)
    g.play()
    state = g.state

    # Full pipeline first: this is the published doc shape (markdown that
    # actually contains scoreboard, MVP, etc.).
    bundle = ReplayBundleBuilder().build(state)
    generated = generate_review_report(state)
    report = dict(generated["report"])
    markdown = generated["final_markdown"]

    sa = SpeechActAnalyzer().analyze(state)
    sm = SuspicionMatrixBuilder().build(state, sa)
    validator = TrackBValidator()

    # Pre-repair validation
    pre = validator.validate(
        report_id="pre",
        game_id=state.id,
        replay_bundle=bundle,
        review_report=report,
        markdown=markdown,
        speech_acts=sa,
        suspicion_matrix=sm,
        view_scope="moderator_view",
    )

    repaired_report, repaired_markdown, post, history = ReviewRepairLoop().run(
        replay_bundle=bundle,
        review_report=report,
        markdown=markdown,
        speech_acts=sa,
        suspicion_matrix=sm,
        validator=validator,
        view_scope="moderator_view",
    )

    return {
        "seed": seed,
        "pre_publish_allowed": pre.publish_allowed,
        "pre_issue_count": len(pre.issues),
        "pre_critical_count": sum(1 for i in pre.issues if i.severity == "critical"),
        "post_publish_allowed": post.publish_allowed,
        "post_issue_count": len(post.issues),
        "post_critical_count": sum(1 for i in post.issues if i.severity == "critical"),
        "repair_rounds": len(history),
    }


def main() -> None:
    seeds = [7, 11, 13, 17, 23, 31, 37, 41, 43, 47]
    rows = [run_one(s) for s in seeds]
    success = sum(1 for r in rows if r.get("post_publish_allowed"))
    print(f"repair_loop_publish_recovery success = {success}/{len(rows)}  ({success / len(rows) * 100:.1f}%)")
    print()
    for r in rows:
        print(json.dumps(r, ensure_ascii=False))
    with open(os.path.join(ROOT, "bc_repair_loop_evidence.json"), "w", encoding="utf-8") as f:
        json.dump({"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "rows": rows}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
