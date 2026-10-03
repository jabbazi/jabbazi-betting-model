from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from jabazi.domain.models import Quote


@dataclass(frozen=True)
class ProviderBatch:
    provider: str
    fetched_at: datetime
    raw_payload: bytes
    quotes: tuple[Quote, ...]
    requests_used: int | None = None
    requests_remaining: int | None = None


class OddsProvider(ABC):
    """Adapters must label provenance; they may not silently invent missing fields."""

    @abstractmethod
    def fetch(self) -> ProviderBatch:
        raise NotImplementedError
