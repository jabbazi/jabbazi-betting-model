import importlib.util
from pathlib import Path
import sys

import pytest
from jabazi.persistence.store import Store

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
spec = importlib.util.spec_from_file_location(
    "discord_learning", Path(__file__).resolve().parents[1] / "tools/discord_learning.py"
)
learning = importlib.util.module_from_spec(spec)
spec.loader.exec_module(learning)


class FakeDiscord:
    def __init__(self):
        self.mutations = []

    def request(self, method, path, payload=None):
        if method == "GET":
            return (
                {"owner_id": "2"}
                if path == "/guilds/1"
                else [
                    {"id": "3", "type": 0, "name": "📘｜betting-basics"},
                    {"id": "4", "type": 0, "name": "💜｜jabbazi-picks"},
                ]
            )
        self.mutations.append((method, path, payload))
        return {"id": str(100 + len(self.mutations))}


def test_learning_publish_is_owner_checked_no_pings_no_permission_changes_and_no_duplicates(
    tmp_path,
):
    client = FakeDiscord()
    with pytest.raises(ValueError, match="owner"):
        learning.run(client, "1", "9", None)
    assert client.mutations == []
    assert learning.run(client, "1", "2", None)["lessons"] == 20
    assert client.mutations == []
    store = Store("sqlite:///" + str(tmp_path / "learning.db"), initialize=True)
    try:
        first = learning.run(client, "1", "2", store, apply=True)
        second = learning.run(client, "1", "2", store, apply=True)
        assert first["published"] == 20 and second["published"] == 0
        assert second["already_delivered"] == 20
        posts = [p for m, _, p in client.mutations if m == "POST"]
        assert "<#4>" in posts[0]["content"]
        assert all(
            len(p["content"]) < 2000 and p["allowed_mentions"] == {"parse": []} for p in posts
        )
        assert all("permission_overwrites" not in p for _, _, p in client.mutations)
    finally:
        store.close()
