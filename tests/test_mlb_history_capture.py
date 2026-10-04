"""Synthetic imports do not imply a trained model or live source coverage."""

import csv
import importlib.util
import io
import zipfile
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "capture_mlb", Path(__file__).parents[1] / "tools/capture_mlb_history.py"
)
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


def row(**updates):
    return {
        "gid": "ABC202504010",
        "id": "pitcher01",
        "team": "ABC",
        "p_seq": "1",
        "p_ipouts": "17",
        "p_bfp": "24",
        "p_k": "6",
        "p_w": "2",
        "p_h": "5",
        "p_hr": "1",
        "p_er": "2",
        "date": "20250401",
        "number": "0",
        "gametype": "regular",
        "stattype": "value",
        **updates,
    }


def archive(tmp_path, rows):
    text = io.StringIO()
    writer = csv.DictWriter(text, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    path = tmp_path / "season.zip"
    with zipfile.ZipFile(path, "w") as out:
        out.writestr("pitching.csv", text.getvalue())
    return path


def test_values_not_alternative_estimates_and_missing_counts_not_zero(tmp_path):
    rows, report = capture.season_rows(
        archive(tmp_path, [row(p_er=""), row(stattype="upper")]), 2025
    )
    assert len(rows) == 1 and rows[0]["p_er"] is None and rows[0]["observed_at"] is None
    assert report["excluded"] == {"non_value_statistics": 1}
    assert report["actual_starts"] == 1 and report["missing_counts"] == {"p_er": 1}


@pytest.mark.parametrize("rows", [[row(), row()], [row(date="20240401")], [row(p_k="-1")]])
def test_duplicate_wrong_year_or_negative_stats_are_rejected(tmp_path, rows):
    with pytest.raises(ValueError):
        capture.season_rows(archive(tmp_path, rows), 2025)


def test_game_ids_keep_doubleheader_appearances_separate(tmp_path):
    rows, report = capture.season_rows(
        archive(
            tmp_path, [row(gid="ABC202504011", number="1"), row(gid="ABC202504012", number="2")]
        ),
        2025,
    )
    assert len(rows) == 2 and report["games"] == 2 and report["pitchers"] == 1
