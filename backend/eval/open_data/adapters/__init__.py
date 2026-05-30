"""Open dataset adapters.

Each adapter converts one external dataset format into Track B canonical
schemas (OpenGameLog → CanonicalGameEvent → SpeechQualitySample, etc.).

Adapters must:
  - Record source, license, and rule_variant.
  - Never generate final_q.
  - Reconstruct visibility where possible.
  - Tag all labels with WeakLabelSource.
"""

from backend.eval.open_data.adapters.werewolf_among_us_adapter import (
    WerewolfAmongUsAdapter,
)

__all__ = ["WerewolfAmongUsAdapter"]
