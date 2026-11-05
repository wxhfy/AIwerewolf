"""Calibrate Track B Judge against explicit human annotation JSON.

Offline demonstration (never authorizes promotion)::

    .venv/bin/python scripts/calibrate_track_b_judge.py \
      --input tests/fixtures/judge_calibration_synthetic.json \
      --provider fake --demo-small --output /tmp/calibration.json \
      --sqlite-store /tmp/calibration.sqlite

For a real run, supply a human dataset, configured provider and actual model,
omit --demo-small, and use --persist to store through the application database.
This entrypoint never loads .env: configured credentials must already be injected.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

os.environ["AIWEREWOLF_SKIP_DOTENV"] = "true"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.eval.calibration import JudgeCalibrationPolicy
from backend.eval.calibration import calibrate_judge_dataset
from backend.eval.calibration import load_judge_calibration_dataset
from backend.eval.llm_judge import LLMJudgePanel


class SyntheticCalibrationClient:
    """Deterministic fake LLM protocol for the clearly marked synthetic fixture.

    Reads only decision text, never labels. This deliberately biased scoring
    function makes the fitted transform and held-out bias reduction inspectable.
    """

    provider = "fake"
    model = "calibration-demo"

    def chat_sync(self, messages: list[dict], **_kwargs) -> dict:
        prompt = messages[-1]["content"]
        marker = re.search(r"\[synthetic_evidence:(\d+)\]", prompt)
        score = 1 + 0.8 * min(10, int(marker.group(1))) if marker else 5.0
        content = json.dumps({"T1_score": score, "T2_score": score, "evidence": [], "confidence": 0.95})
        return {"choices": [{"message": {"content": content}}]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--provider", default="fake")
    parser.add_argument("--judge-model", help="Actual configured model name; required for a non-fake provider")
    parser.add_argument("--scoring-mode", choices=("single_step", "panel_step"), default="single_step")
    parser.add_argument(
        "--demo-small", action="store_true", help="Lower sample counts only for explicit synthetic data"
    )
    storage = parser.add_mutually_exclusive_group()
    storage.add_argument("--persist", action="store_true", help="Store through the configured application database")
    storage.add_argument("--sqlite-store", type=Path, help="Store in an explicit isolated SQLite artifact database")
    args = parser.parse_args(argv)
    try:
        dataset = load_judge_calibration_dataset(args.input)
        if args.demo_small and not dataset["synthetic"]:
            raise ValueError("demo_small_requires_synthetic_dataset")
        if args.provider == "fake":
            client = SyntheticCalibrationClient()
            judge_model = "fake:calibration-demo"
        else:
            if not args.judge_model:
                raise ValueError("judge_model_required_for_configured_provider")
            from backend.llm import create_client

            client = create_client(provider=args.provider, model=args.judge_model)
            judge_model = f"{args.provider}:{args.judge_model}"
        policy = JudgeCalibrationPolicy(min_train=4, min_validation=4) if args.demo_small else JudgeCalibrationPolicy()
        profile = calibrate_judge_dataset(
            dataset,
            LLMJudgePanel(client=client),
            judge_model=judge_model,
            policy=policy,
            scoring_mode=args.scoring_mode,
        )
        if args.sqlite_store:
            from sqlalchemy import create_engine
            from sqlalchemy.orm import Session

            from backend.db.judge_calibration import JudgeCalibration
            from backend.db.judge_calibration import save_judge_calibration

            args.sqlite_store.parent.mkdir(parents=True, exist_ok=True)
            engine = create_engine(f"sqlite:///{args.sqlite_store}")
            JudgeCalibration.__table__.create(engine, checkfirst=True)
            try:
                with Session(engine) as session:
                    save_judge_calibration(profile, session)
                    session.commit()
            finally:
                engine.dispose()
        elif args.persist:
            from backend.db.database import init_db
            from backend.db.judge_calibration import save_judge_calibration

            init_db()
            save_judge_calibration(profile)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(profile, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    key: profile[key]
                    for key in ("calibration_id", "status", "synthetic", "auto_promotion_allowed", "metrics", "reasons")
                }
            )
        )
        return 0
    except (OSError, ValueError, TypeError):
        # Do not echo provider exceptions, credentials, annotation contents or URLs.
        print(
            "judge_calibration_failed: invalid input, provider configuration or artifact destination", file=sys.stderr
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
