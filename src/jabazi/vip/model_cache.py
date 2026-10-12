"""Bounded, nonblocking refresh for VIP model status."""
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
import time

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vip-model-status")
_lock = Lock()
_future = None
_cache = None
_cached_at = 0.0
_error_at = 0.0


def status(loader):
    global _future, _cache, _cached_at, _error_at
    now = time.monotonic()
    with _lock:
        if _future is not None and _future.done():
            try:
                _cache = _future.result()
                _cached_at = now
                _error_at = 0.0
            except Exception:
                _error_at = now
            _future = None
        if _cache is not None and now - _cached_at < 300:
            return {"state": "READY", "data": _cache}
        if _future is None and now - _error_at >= 30:
            _future = _executor.submit(loader)
        return {"state": "REFRESHING" if _future is not None else "UNAVAILABLE", "data": None}
