import pytest

from app import create_app


@pytest.fixture
def client(tmp_path):
    """A test client backed by a throwaway database file."""
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.db")})
    return app.test_client()
