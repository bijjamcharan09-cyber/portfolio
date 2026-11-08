import pytest

from app import create_app, db
from app.auth import hash_password


@pytest.fixture
def app_instance(tmp_path):
    """Create a configured testing application instance with standard and admin accounts."""
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.db")})
    with app.app_context():
        p_hash = hash_password("Password123!")
        db.create_user("Test User", "test@example.com", p_hash, role="user", is_active=1)
        db.create_user("Admin User", "admin@example.com", p_hash, role="admin", is_active=1)
    return app


@pytest.fixture
def client(app_instance):
    """A test client authenticated as a standard user (preserves existing test suite compatibility)."""
    test_client = app_instance.test_client()
    with app_instance.app_context():
        user = db.get_user_by_email("test@example.com")
    with test_client.session_transaction() as sess:
        sess["user_id"] = user["id"]
        sess["user_name"] = user["full_name"]
        sess["user_email"] = user["email"]
        sess["user_role"] = user["role"]
    return test_client


@pytest.fixture
def admin_client(app_instance):
    """A test client authenticated as an administrator."""
    test_client = app_instance.test_client()
    with app_instance.app_context():
        admin = db.get_user_by_email("admin@example.com")
    with test_client.session_transaction() as sess:
        sess["user_id"] = admin["id"]
        sess["user_name"] = admin["full_name"]
        sess["user_email"] = admin["email"]
        sess["user_role"] = admin["role"]
    return test_client


@pytest.fixture
def unauth_client(app_instance):
    """An unauthenticated test client with no active session."""
    return app_instance.test_client()
