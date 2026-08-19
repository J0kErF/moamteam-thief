"""Config-driven brain selection (book App. F table 22): the private TOML's
``[strategy]`` section points at ``package.module:Class``; absent keys fall back to
our shipped brains. Private per-peer choice — never shared, never signed.
"""

import importlib

from moamteam.constants import Role
from moamteam.exceptions import ConfigError
from moamteam.strategy.brains import BrainBase
from moamteam.strategy.funnel import FunnelPoliceBrain, TerritoryThiefBrain

# The competitive brains are the defaults; earlier brains remain available via
# [strategy] (e.g. "moamteam.strategy.funnel:SafeThiefBrain") for experiments —
# the lab table in docs/STRATEGY.md is measured by swapping exactly these.
_DEFAULTS: dict[Role, type[BrainBase]] = {
    Role.POLICE: FunnelPoliceBrain,
    Role.THIEF: TerritoryThiefBrain,
}
_KEYS = {Role.POLICE: "police_class", Role.THIEF: "thief_class"}


def load_brain(private_config: dict, role: Role) -> BrainBase:
    spec = private_config.get("strategy", {}).get(_KEYS[role])
    cls = _DEFAULTS[role] if spec is None else _import_class(spec)
    brain = cls()
    if not isinstance(brain, BrainBase):
        raise ConfigError(f"strategy class {spec!r} must subclass BrainBase")
    return brain


def _import_class(spec: str) -> type:
    module_name, _, class_name = spec.partition(":")
    if not module_name or not class_name:
        raise ConfigError(f"strategy spec {spec!r} must look like 'package.module:Class'")
    try:
        module = importlib.import_module(module_name)
        return getattr(module, class_name)
    except (ImportError, AttributeError) as exc:
        raise ConfigError(f"cannot load strategy class {spec!r}: {exc}") from exc
