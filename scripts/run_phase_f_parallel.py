"""Phase F — Parallel 5×role launcher.

Spawns 5 independent ``score_discrimination_experiment.py`` processes (one
per role: Seer / Witch / Hunter / Guard / Werewolf) so the 100-game sweep
(5 roles × 2 variants × 10 seeds) can finish in ~5 hours instead of ~27
serially. Each child process is fully isolated — separate Python process,
separate LLM client, separate output filenames.

Output files: ``data/experiment/role_<R>_<V>_seed_<N>.json`` are addressed
by role so child processes never collide.

Default seeds = 1..10. Use ``--seeds`` to override.
Default catalog = ``configs/discrimination_strategies.yaml`` (iter2). Use
``--catalog-file configs/discrimination_strategies_iter3.yaml`` for iter3.
Default placement = ``user`` (env var unset). Pass ``--bias-placement system``
to enable iter3 system-prompt injection.

The launcher waits for all children, then runs
``analyze_score_distributions.py`` and prints the Cohen's d table.

Usage:
    # Full Phase F with iter2 bias (back-compat)
    python scripts/run_phase_f_parallel.py

    # Full Phase F with iter3 bias + system placement
    python scripts/run_phase_f_parallel.py \
        --catalog-file configs/discrimination_strategies_iter3.yaml \
        --bias-placement system

    # Dry-run with 2 seeds
    python scripts/run_phase_f_parallel.py --seeds 1 2
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT / "scripts" / "score_discrimination_experiment.py"
ANALYZER = ROOT / "scripts" / "analyze_score_distributions.py"
LOG_DIR = ROOT / "data" / "experiment"
LOG_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_ROLES = ["Seer", "Witch", "Hunter", "Guard", "Werewolf"]


def utc_label() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--roles", nargs="+", default=DEFAULT_ROLES,
                    help=f"Roles to parallelize (default: {DEFAULT_ROLES})")
    ap.add_argument("--seeds", nargs="+", type=int, default=list(range(1, 11)),
                    help="Seeds per (role, variant) — default 1..10")
    ap.add_argument("--variants", nargs="+", default=["good", "bad"])
    ap.add_argument("--catalog-file", default=None,
                    help="Path to strategy YAML; defaults to configs/discrimination_strategies.yaml")
    ap.add_argument("--bias-placement", choices=["user", "system"], default="user",
                    help="Pass-through to STRATEGY_BIAS_PLACEMENT env var (iter3 = system)")
    ap.add_argument("--strict-fallback", default="true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-analyze", action="store_true", help="Skip analyze_score_distributions on completion")
    args = ap.parse_args()

    label = utc_label()
    print(f"[{utc_label()}] Phase F parallel launch:")
    print(f"  roles={args.roles}  seeds={args.seeds}  variants={args.variants}")
    print(f"  catalog={args.catalog_file or 'default'} bias_placement={args.bias_placement}")
    print(f"  total games = {len(args.roles) * len(args.variants) * len(args.seeds)}")
    print()

    child_env = os.environ.copy()
    child_env["STRATEGY_BIAS_PLACEMENT"] = args.bias_placement

    procs: list[tuple[str, subprocess.Popen, Path]] = []
    for role in args.roles:
        log_path = LOG_DIR / f"phase_f_{role}_{label}.log"
        cmd = [
            sys.executable, str(HARNESS),
            "--roles", role,
            "--variants", *args.variants,
            "--seeds", *(str(s) for s in args.seeds),
            "--strict-fallback", args.strict_fallback,
        ]
        if args.force:
            cmd.append("--force")
        if args.catalog_file:
            cmd.extend(["--catalog-file", args.catalog_file])
        log_fh = open(log_path, "w", encoding="utf-8")
        proc = subprocess.Popen(
            cmd,
            cwd=ROOT,
            env=child_env,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
        )
        procs.append((role, proc, log_path))
        print(f"  [{role}] PID={proc.pid} log={log_path.name}")
        print(f"          cmd = {' '.join(shlex.quote(p) for p in cmd)}")

    print()
    print(f"[{utc_label()}] All {len(procs)} child processes launched. Waiting…")
    print(f"  Watch progress: tail -f {LOG_DIR}/phase_f_*_{label}.log")

    # Wait for all children
    start = time.time()
    for role, proc, log_path in procs:
        rc = proc.wait()
        elapsed = round(time.time() - start, 1)
        print(f"[{utc_label()}] {role:10s} exited rc={rc} (elapsed {elapsed}s) log={log_path.name}")

    failures = [(role, p.returncode) for role, p, _ in procs if p.returncode != 0]
    if failures:
        print()
        print(f"[{utc_label()}] {len(failures)} role(s) failed:")
        for role, rc in failures:
            print(f"  {role}: rc={rc}")

    if args.no_analyze:
        return 0 if not failures else 2

    print()
    print(f"[{utc_label()}] Running analyzer…")
    rc = subprocess.call(
        [sys.executable, str(ANALYZER), "--roles", *args.roles],
        cwd=ROOT,
    )
    print(f"[{utc_label()}] analyzer rc={rc}")
    return 0 if (rc == 0 and not failures) else 2


if __name__ == "__main__":
    raise SystemExit(main())
