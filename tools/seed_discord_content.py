"""Back up, seed and pin canonical channel introductions; dry-run by default."""
import argparse
import json
import os

import httpx

from jabazi.discord_onboarding import seed
from jabazi.discord_community import ensure_review_thread
from jabazi.persistence.store import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    token = os.getenv('JABBAZI_DISCORD_BOT_TOKEN', '')
    guild = os.getenv('JABBAZI_DISCORD_GUILD_ID', '')
    owner = os.getenv('JABBAZI_DISCORD_OWNER_ID', '')
    url = os.getenv('JABBAZI_PLATFORM_DATABASE_URL', '')
    if not token or not guild.isdigit() or not owner.isdigit() or not url:
        raise SystemExit('Discord configuration and durable backup database required')
    store = Store(url)
    try:
        if not store.ready():
            raise SystemExit('Backup database is not ready')
        with httpx.Client(base_url='https://discord.com/api/v10', headers={'Authorization': 'Bot ' + token}, timeout=20) as http:
            result = seed(http, store, guild=guild, owner=owner, apply=args.apply)
            if args.apply:
                try:
                    result['member_reviews'] = ensure_review_thread(http, store, guild=guild, owner=owner)
                except Exception as exc:
                    result['member_reviews'] = {'status': 'UNAVAILABLE', 'error': type(exc).__name__}
        print('DISCORD_ONBOARDING_VERIFICATION ' + json.dumps(result, ensure_ascii=False), flush=True)
        if args.apply and any(r['status'] != 'PINNED' for r in result['plan']):
            raise SystemExit(1)
    finally:
        store.close()


if __name__ == '__main__':
    main()
