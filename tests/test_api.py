import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from jabazi.api import app


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_is_public(self):
        self.assertEqual(self.client.get("/healthz").json()["status"], "ok")

    @patch.dict(os.environ, {"JABBAZI_MODEL_TOKEN": "x" * 32}, clear=False)
    def test_scan_requires_token(self):
        response = self.client.post("/v1/scans/run", json={})
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
