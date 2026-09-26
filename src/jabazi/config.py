import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path


def load_dotenv(path: str | Path = ".env") -> None:
    file = Path(path)
    if not file.exists():
        return
    for line in file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


@dataclass(frozen=True)
class Settings:
    bankroll: Decimal
    unit_size: Decimal
    daily_exposure_limit: Decimal
    minimum_edge: Decimal
    timezone: str
    api_key: str
    database_path: str
    service_token: str
    sportsdataio_api_key: str
    model_artifact_path: str
    jurisdiction: str = "LA"

    def portfolio_limits(self):
        from .domain.portfolio import Limits

        values = {
            name: Decimal(os.getenv("JABBAZI_RISK_" + name.upper(), str(default)))
            for name, default in [
                ("per_bet", ".02"),
                ("thesis", ".04"),
                ("parlays", ".03"),
                ("sport", ".10"),
                ("event", ".05"),
                ("player", ".03"),
                ("kelly_fraction", ".10"),
                ("drawdown_stop", ".20"),
            ]
        }
        return Limits(self.bankroll, self.unit_size, self.daily_exposure_limit, **values)

    @classmethod
    def from_environment(cls) -> "Settings":
        load_dotenv()
        return cls(
            bankroll=Decimal(os.getenv("JABAZI_BANKROLL", "1000")),
            unit_size=Decimal(os.getenv("JABAZI_UNIT_SIZE", "30")),
            daily_exposure_limit=Decimal(os.getenv("JABAZI_DAILY_EXPOSURE_LIMIT", "0.20")),
            minimum_edge=Decimal(os.getenv("JABAZI_MIN_EDGE", "0.02")),
            timezone=os.getenv("JABAZI_OPERATIONAL_TIMEZONE", "America/Chicago"),
            api_key=os.getenv("JABAZI_ODDS_API_KEY", ""),
            database_path=os.getenv("JABAZI_DATABASE_PATH", "jabazi-local.db"),
            service_token=os.getenv("JABBAZI_MODEL_TOKEN", ""),
            sportsdataio_api_key=os.getenv("JABBAZI_SPORTSDATAIO_API_KEY", ""),
            model_artifact_path=os.getenv(
                "JABBAZI_MLB_MODEL_ARTIFACT", "models/mlb_moneyline.json"
            ),
            jurisdiction=os.getenv("JABBAZI_JURISDICTION", "LA").upper(),
        )
