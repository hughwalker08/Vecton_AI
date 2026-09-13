"""
Shared pytest fixtures for the backend test suite.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client() -> TestClient:
    """A FastAPI test client wired to the real app, no network/DB calls made."""
    return TestClient(app)
