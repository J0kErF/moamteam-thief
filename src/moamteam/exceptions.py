"""Typed error hierarchy. Every rule rejection carries a human-readable reason so the
opponent's audit (and our own logs) can state exactly which book rule fired.
"""


class MoamteamError(Exception):
    """Base class for every project error."""


class ConfigError(MoamteamError):
    """The shared/private configuration violates the Appendix-F binding table."""


class IllegalMoveError(MoamteamError):
    """A move violates the physics contract (book ch.3). The acting peer loses the
    attempt; repeated violations escalate to a technical loss at the protocol layer."""


class GameOverError(MoamteamError):
    """An action was attempted after the sub-game already reached a terminal outcome."""


class HandshakeMismatchError(MoamteamError):
    """The opponent's agreement does not match ours — refuse to play (rule #11)."""
