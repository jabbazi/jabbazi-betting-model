import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from jabazi.domain.decision import evaluate
from jabazi.domain.models import Candidate, Quote, Recommendation
from jabazi.domain.risk import RiskPolicy
from jabazi.persistence.sqlite import Ledger


@dataclass(frozen=True)
class ScanCandidate:
    candidate: Candidate
    opposing_quotes: tuple[Quote, ...]

    @property
    def key(self) -> str:
        item = self.candidate
        return f"{item.event_id}|{item.market_key}|{item.selection_key}"


class Scanner:
    def __init__(self, ledger: Ledger, policy: RiskPolicy, timezone_name: str) -> None:
        self.ledger = ledger
        self.policy = policy
        self.timezone = ZoneInfo(timezone_name)

    def run(self, candidates: tuple[ScanCandidate, ...], now: datetime) -> list[Recommendation]:
        if os.getenv("JABAZI_ENV") == "production":
            raise RuntimeError(
                "Legacy research scanner is unavailable in production; use AutomaticScanner"
            )
        canonical = [
            {"key": item.key, "quotes": sorted(q.provider_quote_id for q in item.candidate.quotes)}
            for item in sorted(candidates, key=lambda candidate: candidate.key)
        ]
        payload = json.dumps(canonical, sort_keys=True).encode()
        scan_id = str(uuid.uuid4())
        betting_date = now.astimezone(self.timezone).date().isoformat()
        if not self.ledger.start_scan(scan_id, betting_date, payload):
            return []
        exposure = self.ledger.open_exposure()
        output: list[Recommendation] = []
        for item in sorted(candidates, key=lambda candidate: candidate.key):
            result = evaluate(item.candidate, item.opposing_quotes, self.policy, exposure, now)
            self.ledger.save_recommendation(scan_id, item.key, result)
            if result.decision.value == "BET_NOW":
                # Recommendations do not become bets automatically, but reserve sequential scan capacity.
                exposure += result.stake
            output.append(result)
        self.ledger.finish_scan(scan_id)
        return output
