from __future__ import annotations

import signal
import threading
from contextlib import contextmanager
from typing import Iterator


class OperationTimeout(TimeoutError):
    pass


@contextmanager
def operation_timeout(seconds: float) -> Iterator[None]:
    if seconds <= 0 or threading.current_thread() is not threading.main_thread():
        yield
        return

    previous_handler = signal.getsignal(signal.SIGALRM)

    def raise_timeout(signum, frame):  # type: ignore[no-untyped-def]
        raise OperationTimeout(f"operation timed out after {seconds:g}s")

    signal.signal(signal.SIGALRM, raise_timeout)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
