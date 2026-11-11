"""Tests for Guest Mode Trial and One-Time Trial Restriction.

Verifies:
1. Visitor can start guest mode without registration.
2. Isolated temporary session and realistic sample data seeding.
3. Access to demo dashboard, summaries, charts, and transaction operations.
4. One-time guest trial restriction enforced via signed cookie.
5. Inability to restart trial once concluded or exited on the same browser.
6. Expiration after 30 minutes of inactivity.
7. Data isolation: guests cannot access registered users' data or admin routes.
"""
import time
from datetime import date

import pytest
from app import db


def test_guest_mode_start_and_sample_data(unauth_client, app_instance):
    """Visitor can start guest trial; receives signed cookie and sample records."""
    res = unauth_client.post("/guest/start", follow_redirects=True)
    assert res.status_code == 200
    assert b"Guest Mode" in res.data
    assert b"Create Free Account" in res.data

    # Verify guest session
    with unauth_client.session_transaction() as sess:
        assert sess.get("is_guest") is True
        assert sess.get("guest_role") == "guest"
        assert "user_id" not in sess
        guest_id = sess.get("guest_id")
        assert guest_id.startswith("gst_")

    # Verify sample records were seeded into guest_transactions
    with app_instance.app_context():
        rows = db.list_guest_transactions(guest_id)
        assert len(rows) >= 6
        categories = [r["category"] for r in rows]
        assert "Salary" in categories
        assert "Rent" in categories

        # Registered user transactions table should remain empty for this guest
        reg_rows = db.get_db().execute("SELECT COUNT(*) FROM transactions WHERE user_id IS NULL").fetchone()[0]
        assert reg_rows == 0


def test_guest_api_transactions_and_reports(unauth_client):
    """Guest can query transactions, view monthly summary, and get chart PNG."""
    unauth_client.post("/guest/start", follow_redirects=True)

    today_str = date.today().strftime("%Y-%m-%d")

    # List guest transactions
    res_list = unauth_client.get(f"/api/guest/transactions?period=month&date={today_str}")
    assert res_list.status_code == 200
    items = res_list.get_json()
    assert isinstance(items, list)
    assert len(items) > 0

    # Summary
    res_sum = unauth_client.get(f"/api/guest/reports/summary?period=month&date={today_str}")
    assert res_sum.status_code == 200
    summary = res_sum.get_json()
    assert "income" in summary
    assert "expense" in summary
    assert "balance" in summary
    assert summary["income"] > 0
    assert summary["expense"] > 0

    # Chart
    res_chart = unauth_client.get(f"/api/guest/reports/chart.png?period=month&date={today_str}")
    assert res_chart.status_code == 200
    assert res_chart.mimetype == "image/png"


def test_guest_transaction_crud(unauth_client):
    """Guest can add, update, and delete temporary transactions on their demo dashboard."""
    unauth_client.post("/guest/start", follow_redirects=True)
    today_str = date.today().strftime("%Y-%m-%d")

    # Add transaction
    new_tx = {
        "type": "expense",
        "amount": "45.50",
        "category": "Food",
        "note": "Coffee and Bagel",
        "date": today_str,
    }
    res_add = unauth_client.post("/api/guest/transactions", json=new_tx)
    assert res_add.status_code == 201
    created = res_add.get_json()
    assert created["note"] == "Coffee and Bagel"
    tx_id = created["id"]

    # Retrieve single
    res_get = unauth_client.get(f"/api/guest/transactions/{tx_id}")
    assert res_get.status_code == 200
    assert res_get.get_json()["amount"] == 45.50

    # Update
    updated_payload = {
        "type": "expense",
        "amount": "50.00",
        "category": "Food",
        "note": "Coffee, Bagel and Muffin",
        "date": today_str,
    }
    res_put = unauth_client.put(f"/api/guest/transactions/{tx_id}", json=updated_payload)
    assert res_put.status_code == 200
    assert res_put.get_json()["amount"] == 50.00

    # Delete
    res_del = unauth_client.delete(f"/api/guest/transactions/{tx_id}")
    assert res_del.status_code == 204

    # Verify deleted
    assert unauth_client.get(f"/api/guest/transactions/{tx_id}").status_code == 404


def test_one_time_guest_trial_restriction(unauth_client):
    """Guest trial can only be used once per browser; repeated start attempts are blocked."""
    # 1. First trial: allowed
    res1 = unauth_client.post("/guest/start", follow_redirects=True)
    assert res1.status_code == 200
    assert b"Guest Mode" in res1.data

    # Exit guest mode
    res_exit = unauth_client.get("/guest/exit", follow_redirects=True)
    assert res_exit.status_code == 200
    assert b"exited Guest Mode" in res_exit.data

    # 2. Attempt to start a second guest trial from the same browser client
    res2 = unauth_client.post("/guest/start", follow_redirects=True)
    assert res2.status_code == 200
    # Must redirect to login and show trial used message
    assert b"already experienced your one-time Guest Trial" in res2.data
    assert b"One-Time Trial Used" in res2.data

    # Session must NOT have is_guest
    with unauth_client.session_transaction() as sess:
        assert sess.get("is_guest") is None


def test_guest_inactivity_timeout_expiration(unauth_client, app_instance):
    """Guest session expires after 30 minutes of inactivity."""
    unauth_client.post("/guest/start", follow_redirects=True)

    with unauth_client.session_transaction() as sess:
        guest_id = sess.get("guest_id")
        # Simulate 31 minutes ago
        sess["guest_last_active"] = time.time() - 1860

    # Next request should detect expiration
    res = unauth_client.get("/api/guest/transactions")
    assert res.status_code == 401
    assert "expired" in res.get_json()["error"].lower()

    # Verify guest data was cleaned up
    with app_instance.app_context():
        rows = db.list_guest_transactions(guest_id)
        assert len(rows) == 0


def test_guest_cannot_access_admin_routes(unauth_client):
    """Guests are strictly blocked from admin dashboard and admin APIs."""
    unauth_client.post("/guest/start", follow_redirects=True)

    # Admin HTML dashboard
    res_admin_view = unauth_client.get("/admin", follow_redirects=True)
    assert res_admin_view.status_code == 200
    # Must redirect to login because guest has no admin user account
    assert b"Welcome Back" in res_admin_view.data

    # Admin APIs
    assert unauth_client.get("/api/admin/users").status_code == 401
    assert unauth_client.get("/api/admin/stats").status_code == 401


def test_guest_cannot_access_registered_user_api(unauth_client, client):
    """Guests cannot access registered-user routes (/api/transactions)."""
    # Registered user has an account
    client.post("/api/transactions", json={
        "type": "expense",
        "amount": "120.00",
        "category": "Shopping",
        "note": "Private Registered User Purchase",
        "date": date.today().strftime("%Y-%m-%d"),
    })

    # Guest arrives
    unauth_client.post("/guest/start", follow_redirects=True)

    # Calling registered-user transaction endpoint fails with 401
    res_blocked = unauth_client.get("/api/transactions")
    assert res_blocked.status_code == 401

    # Guest API returns only guest demo items, never the registered user's note
    res_guest = unauth_client.get(f"/api/guest/transactions?period=month&date={date.today().strftime('%Y-%m-%d')}")
    assert res_guest.status_code == 200
    notes = [item["note"] for item in res_guest.get_json()]
    assert "Private Registered User Purchase" not in notes
