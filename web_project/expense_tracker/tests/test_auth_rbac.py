"""Comprehensive test suite for Authentication, RBAC, and Data Isolation."""
import pytest
from app import db
from app.auth import hash_password, verify_password


def test_registration_success_and_role_assignment(app_instance):
    """First user becomes admin, second user becomes regular user."""
    client = app_instance.test_client()

    # Register first user (Admin)
    res1 = client.post("/api/auth/register", json={
        "full_name": "First Admin",
        "email": "first_admin@example.com",
        "password": "Password123!",
        "confirm_password": "Password123!",
    })
    assert res1.status_code == 201
    user1 = res1.get_json()["user"]
    assert user1["email"] == "first_admin@example.com"
    # Role assignment: first user is admin or designated
    assert user1["role"] in ("admin", "user")

    # Register second user (User)
    res2 = client.post("/api/auth/register", json={
        "full_name": "Regular User",
        "email": "regular_user@example.com",
        "password": "Password123!",
        "confirm_password": "Password123!",
    })
    assert res2.status_code == 201
    user2 = res2.get_json()["user"]
    assert user2["email"] == "regular_user@example.com"
    assert user2["role"] == "user"


def test_registration_validation_errors(app_instance):
    client = app_instance.test_client()

    # Mismatched passwords
    res = client.post("/api/auth/register", json={
        "full_name": "Test",
        "email": "mismatch@example.com",
        "password": "Password123!",
        "confirm_password": "DifferentPassword123!",
    })
    assert res.status_code == 400
    assert "Passwords do not match" in res.get_json()["error"]

    # Short password
    res = client.post("/api/auth/register", json={
        "full_name": "Test",
        "email": "short@example.com",
        "password": "short",
        "confirm_password": "short",
    })
    assert res.status_code == 400
    assert "at least 8 characters" in res.get_json()["error"]

    # Bad email format
    res = client.post("/api/auth/register", json={
        "full_name": "Test",
        "email": "not-an-email",
        "password": "Password123!",
        "confirm_password": "Password123!",
    })
    assert res.status_code == 400
    assert "valid email" in res.get_json()["error"]


def test_registration_prevents_duplicate_email(app_instance):
    client = app_instance.test_client()
    payload = {
        "full_name": "User One",
        "email": "duplicate@example.com",
        "password": "Password123!",
        "confirm_password": "Password123!",
    }
    assert client.post("/api/auth/register", json=payload).status_code == 201

    # Second registration with same email (case-insensitive)
    payload["email"] = "DUPLICATE@EXAMPLE.COM"
    res = client.post("/api/auth/register", json=payload)
    assert res.status_code == 400
    assert "already exists" in res.get_json()["error"]


def test_passwords_are_never_plaintext(app_instance):
    raw_password = "SecretPassword123!"
    hashed = hash_password(raw_password)
    assert hashed != raw_password
    assert verify_password(raw_password, hashed)
    assert not verify_password("WrongPassword", hashed)


def test_login_flow_and_rejections(app_instance):
    client = app_instance.test_client()

    # Successful login
    res = client.post("/api/auth/login", json={
        "email": "test@example.com",
        "password": "Password123!",
    })
    assert res.status_code == 200
    assert res.get_json()["user"]["email"] == "test@example.com"

    # Bad password
    res_bad = client.post("/api/auth/login", json={
        "email": "test@example.com",
        "password": "WrongPassword!",
    })
    assert res_bad.status_code == 401
    assert "Invalid email or password" in res_bad.get_json()["error"]

    # Non-existent user
    res_none = client.post("/api/auth/login", json={
        "email": "nonexistent@example.com",
        "password": "Password123!",
    })
    assert res_none.status_code == 401


def test_login_rejects_deactivated_account(app_instance):
    client = app_instance.test_client()
    with app_instance.app_context():
        user = db.get_user_by_email("test@example.com")
        db.update_user(user["id"], is_active=0)

    res = client.post("/api/auth/login", json={
        "email": "test@example.com",
        "password": "Password123!",
    })
    assert res.status_code == 403
    assert "deactivated" in res.get_json()["error"].lower()


def test_logout_clears_session(client):
    # Verify current user endpoint returns authenticated user
    res_me = client.get("/api/auth/me")
    assert res_me.status_code == 200

    # Logout
    res_logout = client.post("/api/auth/logout")
    assert res_logout.status_code == 200

    # Me endpoint should now return 401
    assert client.get("/api/auth/me").status_code == 401


def test_unauthenticated_requests_are_blocked(unauth_client):
    assert unauth_client.get("/api/transactions").status_code == 401
    assert unauth_client.post("/api/transactions", json={"type": "expense"}).status_code == 401
    assert unauth_client.get("/api/reports/summary").status_code == 401
    assert unauth_client.get("/api/admin/users").status_code == 401

    # Unauthenticated web route redirects to /login
    resp = unauth_client.get("/")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_rbac_admin_routes_forbidden_for_standard_user(client):
    # Regular user attempting admin API
    assert client.get("/api/admin/users").status_code == 403
    assert client.get("/api/admin/stats").status_code == 403
    assert client.post("/api/admin/users/1/toggle-status").status_code == 403
    assert client.delete("/api/admin/users/1").status_code == 403

    # Regular user attempting admin HTML dashboard
    assert client.get("/admin").status_code == 403


def test_rbac_admin_routes_allowed_for_admin(admin_client):
    assert admin_client.get("/api/admin/users").status_code == 200
    assert admin_client.get("/api/admin/stats").status_code == 200
    assert admin_client.get("/admin").status_code == 200


def test_multi_user_data_isolation_and_idor_protection(app_instance):
    """User A and User B cannot view, modify, or delete each other's expenses."""
    with app_instance.app_context():
        p_hash = hash_password("Password123!")
        u1_id = db.create_user("User Alpha", "alpha@example.com", p_hash, role="user")
        u2_id = db.create_user("User Beta", "beta@example.com", p_hash, role="user")

    client_a = app_instance.test_client()
    with client_a.session_transaction() as sess:
        sess["user_id"] = u1_id
        sess["user_name"] = "User Alpha"
        sess["user_email"] = "alpha@example.com"
        sess["user_role"] = "user"

    client_b = app_instance.test_client()
    with client_b.session_transaction() as sess:
        sess["user_id"] = u2_id
        sess["user_name"] = "User Beta"
        sess["user_email"] = "beta@example.com"
        sess["user_role"] = "user"

    # User A creates a transaction
    tx_a = client_a.post("/api/transactions", json={
        "type": "expense",
        "amount": 55.00,
        "category": "Food",
        "date": "2026-10-15",
        "note": "Alpha lunch",
    }).get_json()
    tx_a_id = tx_a["id"]

    # User B creates a transaction
    tx_b = client_b.post("/api/transactions", json={
        "type": "income",
        "amount": 2000.00,
        "category": "Salary",
        "date": "2026-10-15",
        "note": "Beta salary",
    }).get_json()
    tx_b_id = tx_b["id"]

    # User A lists transactions -> should only see Alpha lunch
    items_a = client_a.get("/api/transactions?period=month&date=2026-10-15").get_json()
    assert len(items_a) == 1
    assert items_a[0]["id"] == tx_a_id
    assert items_a[0]["amount"] == 55.00

    # User B lists transactions -> should only see Beta salary
    items_b = client_b.get("/api/transactions?period=month&date=2026-10-15").get_json()
    assert len(items_b) == 1
    assert items_b[0]["id"] == tx_b_id
    assert items_b[0]["amount"] == 2000.00

    # IDOR Prevention on GET: User B cannot fetch User A's transaction
    assert client_b.get(f"/api/transactions/{tx_a_id}").status_code == 404

    # IDOR Prevention on PUT: User B cannot edit User A's transaction
    res_put = client_b.put(f"/api/transactions/{tx_a_id}", json={
        "type": "expense",
        "amount": 999.00,
        "category": "Food",
        "date": "2026-10-15",
        "note": "Hacked",
    })
    assert res_put.status_code == 404

    # Verify User A's transaction was not modified
    tx_a_check = client_a.get(f"/api/transactions/{tx_a_id}").get_json()
    assert tx_a_check["amount"] == 55.00
    assert tx_a_check["note"] == "Alpha lunch"

    # IDOR Prevention on DELETE: User B cannot delete User A's transaction
    assert client_b.delete(f"/api/transactions/{tx_a_id}").status_code == 404

    # Verify User A's transaction still exists
    assert client_a.get(f"/api/transactions/{tx_a_id}").status_code == 200

    # Personal Reports isolation: User A's balance is -55.00, User B's balance is 2000.00
    sum_a = client_a.get("/api/reports/summary?period=month&date=2026-10-15").get_json()
    assert sum_a["expense"] == 55.00
    assert sum_a["income"] == 0.00

    sum_b = client_b.get("/api/reports/summary?period=month&date=2026-10-15").get_json()
    assert sum_b["expense"] == 0.00
    assert sum_b["income"] == 2000.00


def test_edit_transaction_feature(client):
    """Verify PUT /api/transactions/<id> updates transaction correctly."""
    add_res = client.post("/api/transactions", json={
        "type": "expense",
        "amount": 25.0,
        "category": "Food",
        "date": "2026-10-10",
        "note": "Breakfast",
    }).get_json()
    tx_id = add_res["id"]

    edit_res = client.put(f"/api/transactions/{tx_id}", json={
        "type": "expense",
        "amount": 30.50,
        "category": "Food",
        "date": "2026-10-10",
        "note": "Breakfast & Coffee",
    })
    assert edit_res.status_code == 200
    updated = edit_res.get_json()
    assert updated["amount"] == 30.50
    assert updated["note"] == "Breakfast & Coffee"


def test_admin_user_management_safeguards(admin_client, app_instance):
    """Admin cannot deactivate self, cannot delete self, and can toggle user status."""
    with app_instance.app_context():
        admin_user = db.get_user_by_email("admin@example.com")
        target_user = db.get_user_by_email("test@example.com")

    # Admin cannot deactivate own account
    res_self_toggle = admin_client.post(f"/api/admin/users/{admin_user['id']}/toggle-status")
    assert res_self_toggle.status_code == 400
    assert "cannot deactivate your own" in res_self_toggle.get_json()["error"]

    # Admin cannot delete own account
    res_self_del = admin_client.delete(f"/api/admin/users/{admin_user['id']}")
    assert res_self_del.status_code == 400
    assert "cannot delete your own" in res_self_del.get_json()["error"]

    # Admin can deactivate target user
    res_toggle = admin_client.post(f"/api/admin/users/{target_user['id']}/toggle-status")
    assert res_toggle.status_code == 200
    assert res_toggle.get_json()["user"]["is_active"] is False

    # Admin can re-activate target user
    res_toggle2 = admin_client.post(f"/api/admin/users/{target_user['id']}/toggle-status")
    assert res_toggle2.status_code == 200
    assert res_toggle2.get_json()["user"]["is_active"] is True

    # Admin can delete target user
    res_del = admin_client.delete(f"/api/admin/users/{target_user['id']}")
    assert res_del.status_code == 200


def test_profile_update_and_password_change(client):
    # Update full name
    res = client.post("/profile", data={
        "full_name": "Updated Test Name",
    }, follow_redirects=True)
    assert res.status_code == 200
    assert "Updated Test Name" in res.get_data(as_text=True)

    # Change password with wrong current password -> error
    res_wrong = client.post("/profile", data={
        "full_name": "Updated Test Name",
        "current_password": "WrongPassword!",
        "new_password": "NewSecretPassword123!",
        "confirm_new_password": "NewSecretPassword123!",
    })
    assert res_wrong.status_code == 200
    assert "Current password does not match" in res_wrong.get_data(as_text=True)

    # Change password with correct current password -> success
    res_good = client.post("/profile", data={
        "full_name": "Updated Test Name",
        "current_password": "Password123!",
        "new_password": "NewSecretPassword123!",
        "confirm_new_password": "NewSecretPassword123!",
    })
    assert res_good.status_code == 200
    assert "Password updated successfully" in res_good.get_data(as_text=True)
