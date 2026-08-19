"""A trivial brain used by the loader tests (spec: 'dummy_brains:AlwaysStayBrain')."""

from moamteam.strategy.brains import BrainBase


class AlwaysStayBrain(BrainBase):
    def _pick_move(self, directions, view):
        return None  # always STAY


class NotABrain:
    """Deliberately not a BrainBase subclass — the loader must reject it."""
