"""Protocol phases of one peer, in book order: handshake → turns → audit.

Each module is a set of free functions over the ``PeerRuntime`` instance — the
runtime stays the single stateful object; the phases stay small and testable.
"""
