#!/usr/bin/env python3
"""
strategy_enhance_all.py — One-click orchestrator for the full strategy enhancement pipeline.

Runs four steps sequentially:
  1. crawl_general_strategies.py  — generate Chinese strategies
  2. translate_strategies.py      — translate English strategies
  3. build_strategy_graph.py      — build strategy graph
  4. promote_candidates.py        — promote candidates to active knowledge

Design goals:
  - Continue on failure so partial results are always saved.
  - Log everything to console AND a timestamped log file.
  - Print a clean summary table at the end.

Usage:
  /home/fyh0106/miniconda3/envs/werewolf-test/bin/python scripts/strategy_enhance_all.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime
from typing import Dict
from typing import List
from typing import Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PYTHON: str = "/home/fyh0106/miniconda3/envs/werewolf-test/bin/python"
SCRIPTS_DIR: str = "/home/fyh0106/AIwerewolf/scripts"
LOGS_DIR: str = "/home/fyh0106/AIwerewolf/logs"

STEPS: List[Tuple[str, str]] = [
    ("crawl_general_strategies.py", "Step 1 — Generate Chinese strategies"),
    ("translate_strategies.py", "Step 2 — Translate English strategies"),
    ("build_strategy_graph.py", "Step 3 — Build strategy graph (LLM)"),
    ("cluster_promote.py", "Step 4 — Cluster-based promotion (TF-IDF + KMeans)"),
    ("promote_candidates.py", "Step 5 — Quality-based promotion + cleaning (dedup/prune)"),
]

SEPARATOR: str = "=" * 72


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_log_dir() -> str:
    """Create the logs directory if it does not exist and return its path."""
    os.makedirs(LOGS_DIR, exist_ok=True)
    return os.path.abspath(LOGS_DIR)


def _open_log(log_path: str):
    """Open the log file for appending (unbuffered line-buffering)."""
    return open(log_path, "a", buffering=1, encoding="utf-8")


def tee(msg: str, log_file) -> None:
    """Write a message to both stdout and the log file."""
    print(msg, flush=True)
    if log_file:
        log_file.write(msg + "\n")


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------


def run_step(
    script_name: str,
    step_label: str,
    log_file,
) -> Dict:
    """
    Run a single pipeline step in a subprocess.

    Returns a dict with keys: label, script, start, end, duration, rc, status.

    If the script file is missing, rc is set to -99 and execution continues.
    """
    script_path: str = os.path.join(SCRIPTS_DIR, script_name)
    result: Dict = {
        "label": step_label,
        "script": script_name,
        "start": 0.0,
        "end": 0.0,
        "duration": 0.0,
        "rc": -999,
        "status": "SKIPPED",
    }

    # Check existence
    if not os.path.isfile(script_path):
        tee(f"\n{SEPARATOR}", log_file)
        tee(f"  {step_label}", log_file)
        tee(f"{SEPARATOR}", log_file)
        tee(f"[SKIP] Script not found: {script_path}", log_file)
        tee("       Please create it before running this step.", log_file)
        result["rc"] = -99
        result["status"] = "MISSING"
        return result

    tee(f"\n{SEPARATOR}", log_file)
    tee(f"  {step_label}", log_file)
    tee(f"{SEPARATOR}", log_file)

    start_time: float = time.time()
    result["start"] = start_time

    tee(f"Start: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", log_file)
    tee(f"Command: {PYTHON} {script_path}", log_file)

    try:
        proc = subprocess.run(
            [PYTHON, script_path],
            cwd=SCRIPTS_DIR,
            capture_output=False,
            text=True,
        )
    except FileNotFoundError:
        tee(f"[ERROR] Python interpreter not found: {PYTHON}", log_file)
        result["rc"] = -1
        result["status"] = "FAILED (interpreter missing)"
        result["end"] = time.time()
        result["duration"] = result["end"] - start_time
        return result
    except Exception as exc:
        tee(f"[ERROR] Unexpected exception: {exc}", log_file)
        result["rc"] = -1
        result["status"] = f"FAILED ({exc})"
        result["end"] = time.time()
        result["duration"] = result["end"] - start_time
        return result

    end_time: float = time.time()
    result["end"] = end_time
    result["duration"] = end_time - start_time
    result["rc"] = proc.returncode

    if proc.returncode == 0:
        result["status"] = "SUCCESS"
    else:
        result["status"] = f"FAILED (exit code {proc.returncode})"

    tee(f"\nExit code: {proc.returncode}", log_file)
    tee(f"Duration:  {result['duration']:.2f} seconds", log_file)

    if proc.returncode != 0:
        tee(f"\n[WARN]  Step failed: {script_name}", log_file)
        tee("        Continuing to next step anyway.", log_file)

    return result


def ask_continue_interactive() -> bool:
    """Prompt the user whether to continue after a failure. Returns True to continue."""
    try:
        answer = input("\nContinue with next step? [Y/n]: ").strip().lower()
        return answer in ("", "y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


def print_summary(results: List[Dict], total_start: float, log_file) -> None:
    """Print the final summary table."""
    total_duration: float = time.time() - total_start

    tee(f"\n\n{SEPARATOR}", log_file)
    tee("  Strategy Enhancement — Final Summary", log_file)
    tee(f"{SEPARATOR}", log_file)

    width_label: int = 42
    width_status: int = 32

    for r in results:
        label_col: str = r["label"].ljust(width_label)
        status_col: str = r["status"].ljust(width_status)
        dur_col: str = f"({r['duration']:.1f}s)"
        tee(f"  {label_col}  {status_col}  {dur_col}", log_file)

    tee(f"\n  Total time: {total_duration:.1f} seconds", log_file)
    tee(f"{SEPARATOR}\n", log_file)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    """Run the full strategy enhancement pipeline."""
    # -- setup logging --------------------------------------------------------
    log_dir: str = _ensure_log_dir()
    timestamp: str = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path: str = os.path.join(log_dir, f"strategy_enhance_{timestamp}.log")

    log_file = _open_log(log_path)
    tee(f"Log file: {log_path}", log_file)
    tee(f"Python:   {PYTHON}", log_file)
    tee(f"Scripts:  {SCRIPTS_DIR}", log_file)

    total_start: float = time.time()
    results: List[Dict] = []

    for script_name, step_label in STEPS:
        result = run_step(script_name, step_label, log_file)
        results.append(result)

        if result["status"] not in ("SUCCESS", "MISSING"):
            # Ask whether to continue (interactive TTY only)
            if sys.stdin.isatty():
                if not ask_continue_interactive():
                    tee(
                        f"[ABORT] User chose to stop after step failed: {script_name}",
                        log_file,
                    )
                    break
            else:
                tee(
                    "[INFO] Non-interactive mode — automatically continuing.",
                    log_file,
                )

    # -- summary --------------------------------------------------------------
    print_summary(results, total_start, log_file)

    tee(f"Log saved to: {log_path}", log_file)

    if log_file:
        log_file.close()

    # Return non-zero if any step actually failed (not just missing)
    for r in results:
        if r["status"].startswith("FAILED"):
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
