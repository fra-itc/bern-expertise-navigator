"""Shared test setup: the default suite always runs on the file backend, whatever DATABASE_URL the
developer's .env carries. Postgres tests opt in explicitly (test_pg_backend.py, TEST_DATABASE_URL)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from navigator import config  # noqa: E402


@pytest.fixture(autouse=True)
def _file_backend_by_default(monkeypatch):
    monkeypatch.setattr(config.settings, "database_url", "")
