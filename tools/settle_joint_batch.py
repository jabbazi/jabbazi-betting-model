"""Explicit bounded result polling; dry run by default, never a scheduler."""
import argparse
from datetime import UTC, datetime
import json
import os
import time

import httpx
from sqlalchemy import select

from jabazi.boost_prospective import FORECAST, RESULT, _at
from jabazi.persistence.store import Store, events
from tools.settle_joint_research import settle_one


def settle_batch(store, http, *, execute=False, limit=100, after='',
                 max_seconds=60, now=None):
    if not 1 <= limit <= 200 or not 1 <= max_seconds <= 120:
        raise ValueError('Bounded batch limits required')
    if after and (len(after) != 64 or any(c not in '0123456789abcdef' for c in after)):
        raise ValueError('Invalid continuation cursor')
    observed = now or datetime.now(UTC)
    deadline = time.monotonic() + max_seconds
    outcomes = events.alias('outcomes')
    resolved = select(outcomes.c.id).where(
        outcomes.c.kind == RESULT,
        outcomes.c.payload['forecast_id'].as_string() == events.c.id,
    ).exists()
    query = select(events.c.id, events.c.payload).where(
        events.c.kind == FORECAST, events.c.id > after, ~resolved,
    ).order_by(events.c.id).limit(limit + 1)
    with store.engine.connect() as conn:
        rows = conn.execute(query).all()
    cache, results = {}, []
    cursor = after
    for forecast_id, frozen in rows[:limit]:
        if time.monotonic() >= deadline:
            break
        try:
            if _at(frozen['starts_at'], 'frozen start') > observed:
                result = {'status': 'PENDING'}
            else:
                result = settle_one(store, http, forecast_id, execute=execute, source_cache=cache)
        except Exception as exc:
            # A broken source/player must not prevent independent results, or leak secrets.
            result = {'status': 'BLOCKED', 'error_type': type(exc).__name__}
        results.append(dict(result, forecast_id=forecast_id))
        cursor = forecast_id
    more = len(results) < len(rows)
    return {'research_only': True, 'approved_for_betting': False,
            'execute': execute, 'processed': len(results), 'results': results,
            'source_documents': len(cache), 'has_more': more,
            'next_cursor': cursor if more else None}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--limit', type=int, default=100)
    parser.add_argument('--after', default='')
    parser.add_argument('--max-seconds', type=int, default=60)
    args = parser.parse_args(argv)
    store = None
    try:
        store = Store(os.environ['JABBAZI_PLATFORM_DATABASE_URL'])
        with httpx.Client(timeout=15) as http:
            result = settle_batch(store, http, **vars(args))
    except Exception as exc:
        result = {'status': 'BLOCKED', 'error_type': type(exc).__name__,
                  'research_only': True, 'approved_for_betting': False}
    finally:
        if store is not None:
            store.close()
    print(json.dumps(result, sort_keys=True))
    return 2 if result.get('status') == 'BLOCKED' or any(
        r['status'] == 'BLOCKED' for r in result.get('results', [])) else 0


if __name__ == '__main__':
    raise SystemExit(main())
