"""Bounded application rate limits and security headers; no request bodies logged."""
import threading
import time
from collections import deque

from fastapi.responses import JSONResponse

_buckets = {}
_lock = threading.Lock()


async def guard(request, call_next):
    path = request.url.path
    if not (path.startswith('/v1/member/') or path.startswith('/v1/vip/') or path.startswith('/vip')):
        return await call_next(request)
    if path.startswith('/v1/'):
        key = (request.client.host if request.client else 'unknown', 'session' if path.endswith('/session') else 'member')
        now = time.monotonic()
        with _lock:
            if len(_buckets) > 10000:
                _buckets.clear()
            hits = _buckets.setdefault(key, deque())
            while hits and now-hits[0] >= 60:
                hits.popleft()
            if len(hits) >= (60 if key[1] == 'session' else 300):
                return JSONResponse({'detail': 'Too many requests. Try again in a minute.'}, status_code=429, headers={'Retry-After': '60', 'Cache-Control': 'no-store'})
            hits.append(now)
    try:
        response = await call_next(request)
    except Exception as exc:
        print('VIP_REQUEST_FAILED_' + type(exc).__name__, flush=True)
        response = JSONResponse({'detail': 'Research is temporarily unavailable. Please try again.'}, status_code=503)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response
