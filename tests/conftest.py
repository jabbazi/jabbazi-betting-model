"""Set the test calendar before collection, so date-scoped fixtures stay reproducible."""
from time_machine import travel

_clock = None


def pytest_configure(config):
    global _clock
    # One process-wide clock avoids swapping datetime classes under cached API schemas.
    # Elapsed time still advances; rollover tests supply their own explicit timestamps.
    _clock = travel('2026-10-13T17:00:00Z', tick=True)
    _clock.start()


def pytest_unconfigure(config):
    if _clock is not None:
        _clock.stop()
