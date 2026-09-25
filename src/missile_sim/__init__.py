"""简化模型导弹弹道仿真器（2D 纵向平面，瞬时燃烧 + 高抛 + 比例导引）。

快速开始：
    python -m missile_sim --help
    python -m missile_sim --vm0 300 --vt -300 --alt 10000 --range 50000 --loft 22
"""

from .config import MissileConfig, load_config  # noqa: F401
from .sim import Case, SimResult, simulate_one  # noqa: F401

__all__ = [
    "MissileConfig",
    "load_config",
    "Case",
    "SimResult",
    "simulate_one",
    "config",
    "atmosphere",
    "ballistics",
    "sim",
    "sweep",
    "plot",
    "cli",
]
