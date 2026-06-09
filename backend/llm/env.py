from __future__ import annotations

import os
from pathlib import Path


def load_env_file(path: str = ".env") -> None:
    """Load key=value pairs from a local .env file into process env.

    This keeps the project self-contained and avoids requiring the caller to
    `source .env` before running the backend or CLI tools.
    """

    if os.getenv("AIWEREWOLF_SKIP_DOTENV", "").lower() in {"1", "true", "yes", "on"}:
        return

    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # 只在环境变量未设置或为空时设置
        if not os.environ.get(key):
            os.environ[key] = value
