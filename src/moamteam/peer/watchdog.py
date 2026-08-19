"""Watchdog (book §8.4.2, rule #7): an independent background monitor of the main
game loop. On a frozen heartbeat it persists state and shuts down cleanly instead of
letting the process die silently mid-league.
"""

import logging
import threading
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)


class Watchdog:
    """Background heartbeat monitor.

    The main loop calls ``beat()`` every iteration; ``check()`` compares the age of
    the last beat to the configured threshold. When frozen, the persist and shutdown
    callbacks run exactly once and the watchdog stops itself.
    """

    def __init__(self, *, timeout_seconds: float,
                 persist: Callable[[], None], shutdown: Callable[[], None],
                 poll_seconds: float = 1.0, clock: Callable[[], float] = time.monotonic):
        self._timeout = timeout_seconds
        self._persist = persist
        self._shutdown = shutdown
        self._poll = poll_seconds
        self._clock = clock
        self._last_beat = clock()
        self._stop = threading.Event()
        self._fired = False
        self._thread: threading.Thread | None = None

    def beat(self) -> None:
        self._last_beat = self._clock()

    def check(self) -> str:
        """One inspection: 'ALIVE', or 'SHUTDOWN' after firing the callbacks."""
        if self._fired:
            return "SHUTDOWN"
        if self._clock() - self._last_beat <= self._timeout:
            return "ALIVE"
        self._fired = True
        logger.error("watchdog: main loop frozen > %.0fs — persisting state and shutting down",
                     self._timeout)
        try:
            self._persist()
        finally:
            self._shutdown()
        return "SHUTDOWN"

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True, name="watchdog")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            if self.check() == "SHUTDOWN":
                return
            self._stop.wait(self._poll)
