import io

import pytest
from PIL import Image

from jabazi.discord_daily import render_slate, render_text


def sheet(count):
    return {"payload": {"date": "2026-10-13", "timezone": "America/Chicago", "row_count": count,
                        "rows": [{"event": f"Fixture {i}: Away at Home", "sport_label": "NHL",
                                  "projected_winner": "Unavailable", "projection_source": "UNAVAILABLE"}
                                 for i in range(count)]}}


def test_large_slate_is_one_complete_readable_image():
    record = sheet(30)
    rendered = render_slate(record)
    image = Image.open(io.BytesIO(rendered))
    assert image.format == "PNG"
    assert image.width == 1200 and image.height > 4000
    assert len(rendered) < 7_000_000
    assert len(render_text(record)) < 1900
    assert "30 eligible games" in render_text(record)
    assert "one complete slate sheet" in render_text(record)


def test_empty_slate_is_renderable():
    image = Image.open(io.BytesIO(render_slate(sheet(0))))
    assert image.height > 400


def test_incomplete_slate_is_rejected_before_sending():
    record = sheet(30)
    record["payload"]["rows"].pop()
    with pytest.raises(ValueError, match="count mismatch"):
        render_slate(record)
