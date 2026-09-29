"""Render a clearly marked synthetic layout sample. Never accesses live data."""

import argparse
import io
from datetime import UTC, datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw

from jabazi.sheet_images import font, render_card


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    now = datetime(2026, 9, 24, 17, tzinfo=UTC)
    examples = [
        ("Demo Bears @ Demo Tigers", "Demo Tigers", "h2h", None),
        ("Demo Jays @ Demo Eagles", "Demo Jays", "spreads", 1.5),
        ("Demo Foxes @ Demo Wolves", "Under", "totals", 8.5),
        ("Demo Hawks @ Demo Lions", "Demo Lions", "spreads", -1.5),
        ("Demo Sharks @ Demo Owls", "Over", "alternate_totals", 7.5),
        ("Demo Jays @ Demo Eagles", "Demo Jays", "h2h", None),
    ]
    rows = [
        {
            "sport": "baseball_mlb",
            "event_id": f"synthetic-{i}",
            "event": event,
            "selection": selection,
            "market": market,
            "line": line,
            "book": "DEMO ONLY",
            "decimal_odds": "2.0",
            "research_probability": "0.60",
            "market_no_vig_probability": "0.50",
            "uncertainty": "0.08",
            "model_version": "SYNTHETIC_LAYOUT_ONLY",
            "executable": True,
            "book_count": 3,
            "price_time_utc": now.isoformat(),
            "starts_at_utc": (now + timedelta(hours=i + 2)).isoformat(),
        }
        for i, (event, selection, market, line) in enumerate(examples)
    ]
    record = {"payload": {"healthy": True, "completed_at": now.isoformat(), "rows": rows}}
    rendered = Image.open(io.BytesIO(render_card(record, "mlb", 0, now=now)))
    sample = Image.new("RGB", (rendered.width, rendered.height + 70), "#d7bd88")
    sample.paste(rendered, (0, 70))
    ImageDraw.Draw(sample).text(
        (52, 20),
        "LAYOUT SAMPLE · FICTIONAL TEAMS · NOT LIVE PICKS",
        font=font(23, True),
        fill="#111113",
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sample.save(args.output)


if __name__ == "__main__":
    main()
