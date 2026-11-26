"""Tests for Release 2 features: Budgets, Recurring Transactions, Goals, Subscriptions, Forecasting, Notifications."""
import pytest
from datetime import date, timedelta
from decimal import Decimal


class TestBudgets:
    """Test budget management functionality."""

    def test_create_budget(self, client):
        """Test creating a budget."""
        response = client.post("/api/budgets", json={
            "name": "Monthly Food Budget",
            "period": "monthly",
            "category": "Food",
            "amount": "500.00",
            "warning_threshold": 80,
            "start_date": date.today().isoformat()
        })
        assert response.status_code == 201
        data = response.get_json()
        assert data["name"] == "Monthly Food Budget"
        assert data["period"] == "monthly"
        assert data["category"] == "Food"
        assert data["amount_cents"] == 50000

    def test_create_overall_budget(self, client):
        """Test creating an overall budget (no category)."""
        response = client.post("/api/budgets", json={
            "name": "Overall Monthly Budget",
            "period": "monthly",
            "amount": "2000.00",
            "start_date": date.today().isoformat()
        })
        assert response.status_code == 201
        data = response.get_json()
        assert data["category"] is None

    def test_list_budgets(self, client):
        """Test listing budgets."""
        client.post("/api/budgets", json={
            "name": "Budget 1", "period": "monthly", "amount": "100.00", "start_date": date.today().isoformat()
        })
        client.post("/api/budgets", json={
            "name": "Budget 2", "period": "weekly", "amount": "50.00", "start_date": date.today().isoformat()
        })

        response = client.get("/api/budgets")
        assert response.status_code == 200
        data = response.get_json()
        assert len(data["budgets"]) == 2

    def test_get_budget(self, client):
        """Test getting a single budget."""
        create_resp = client.post("/api/budgets", json={
            "name": "Test Budget", "period": "monthly", "amount": "100.00", "start_date": date.today().isoformat()
        })
        budget_id = create_resp.get_json()["id"]

        response = client.get(f"/api/budgets/{budget_id}")
        assert response.status_code == 200
        data = response.get_json()
        assert data["id"] == budget_id

    def test_update_budget(self, client):
        """Test updating a budget."""
        create_resp = client.post("/api/budgets", json={
            "name": "Old Name", "period": "monthly", "amount": "100.00", "start_date": date.today().isoformat()
        })
        budget_id = create_resp.get_json()["id"]

        response = client.put(f"/api/budgets/{budget_id}", json={
            "name": "New Name", "period": "monthly", "amount": "200.00", "start_date": date.today().isoformat()
        })
        assert response.status_code == 200
        data = response.get_json()
        assert data["name"] == "New Name"
        assert data["amount_cents"] == 20000

    def test_delete_budget(self, client):
        """Test deleting a budget."""
        create_resp = client.post("/api/budgets", json={
            "name": "To Delete", "period": "monthly", "amount": "100.00", "start_date": date.today().isoformat()
        })
        budget_id = create_resp.get_json()["id"]

        response = client.delete(f"/api/budgets/{budget_id}")
        assert response.status_code == 204

        # Verify deleted
        response = client.get(f"/api/budgets/{budget_id}")
        assert response.status_code == 404

    def test_budget_utilization(self, client):
        """Test budget utilization calculation."""
        # Create budget for current month
        today = date.today()
        start = today.replace(day=1)
        end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)

        client.post("/api/budgets", json={
            "name": "Food Budget", "period": "monthly", "category": "Food",
            "amount": "500.00", "start_date": start.isoformat()
        })

        # Add some food expenses
        client.post("/api/transactions", json={
            "type": "expense", "amount": "100.00", "category": "Food",
            "date": today.isoformat()
        })
        client.post("/api/transactions", json={
            "type": "expense", "amount": "200.00", "category": "Food",
            "date": today.isoformat()
        })

        response = client.get("/api/budgets/utilization")
        assert response.status_code == 200
        data = response.get_json()
        assert len(data["budgets"]) == 1
        budget = data["budgets"][0]
        assert budget["spent"] == 300.00
        assert budget["remaining"] == 200.00
        assert budget["utilization_pct"] == 60.0
        assert budget["is_warning"] == False
        assert budget["is_exceeded"] == False

    def test_budget_warning_threshold(self, client):
        """Test budget warning at threshold."""
        today = date.today()
        start = today.replace(day=1)

        client.post("/api/budgets", json={
            "name": "Warning Budget", "period": "monthly", "category": "Food",
            "amount": "500.00", "warning_threshold": 80, "start_date": start.isoformat()
        })

        # Add expenses to hit 80% (400.00)
        client.post("/api/transactions", json={
            "type": "expense", "amount": "400.00", "category": "Food",
            "date": today.isoformat()
        })

        response = client.get("/api/budgets/utilization")
        assert response.status_code == 200
        data = response.get_json()
        budget = data["budgets"][0]
        assert budget["is_warning"] == True
        assert budget["is_exceeded"] == False

    def test_budget_exceeded(self, client):
        """Test budget exceeded notification."""
        today = date.today()
        start = today.replace(day=1)

        client.post("/api/budgets", json={
            "name": "Exceeded Budget", "period": "monthly", "category": "Food",
            "amount": "500.00", "start_date": start.isoformat()
        })

        # Add expenses exceeding budget
        client.post("/api/transactions", json={
            "type": "expense", "amount": "600.00", "category": "Food",
            "date": today.isoformat()
        })

        response = client.get("/api/budgets/utilization")
        assert response.status_code == 200
        data = response.get_json()
        budget = data["budgets"][0]
        assert budget["is_exceeded"] == True
        assert budget["is_warning"] == True

    def test_budget_validation(self, client):
        """Test budget input validation."""
        # Missing required fields
        response = client.post("/api/budgets", json={
            "name": "Test", "period": "monthly"
        })
        assert response.status_code == 400

        # Invalid period
        response = client.post("/api/budgets", json={
            "name": "Test", "period": "yearly", "amount": "100", "start_date": date.today().isoformat()
        })
        assert response.status_code == 400

        # Invalid amount
        response = client.post("/api/budgets", json={
            "name": "Test", "period": "monthly", "amount": "-100", "start_date": date.today().isoformat()
        })
        assert response.status_code == 400

    def test_budget_isolation(self, client, other_client):
        """Test that budgets are isolated per user."""
        # User 1 creates budget
        create_resp = client.post("/api/budgets", json={
            "name": "User 1 Budget", "period": "monthly", "amount": "100.00", "start_date": date.today().isoformat()
        })
        budget_id = create_resp.get_json()["id"]

        # User 2 tries to access
        other_client.post(f"/api/budgets/{budget_id}")
        assert other_client.get(f"/api/budgets/{budget_id}").status_code == 404

        # User 2 lists budgets - should not see user 1's budget
        response = other_client.get("/api/budgets")
        budgets = response.get_json()["budgets"]
        assert not any(b["id"] == budget_id for b in budgets)


class TestRecurringTransactions:
    """Test recurring transaction functionality."""

    def test_create_recurring(self, client):
        """Test creating a recurring transaction."""
        response = client.post("/api/recurring", json={
            "type": "expense",
            "amount": "50.00",
            "category": "Transport",
            "frequency": "monthly",
            "start_date": date.today().isoformat(),
            "next_due_date": date.today().isoformat()
        })
        assert response.status_code == 201
        data = response.get_json()
        assert data["frequency"] == "monthly"
        assert data["amount_cents"] == 5000

    def test_list_recurring(self, client):
        """Test listing recurring transactions."""
        client.post("/api/recurring", json={
            "type": "expense", "amount": "50.00", "category": "Transport",
            "frequency": "monthly", "start_date": date.today().isoformat(),
            "next_due_date": date.today().isoformat()
        })
        client.post("/api/recurring", json={
            "type": "income", "amount": "5000.00", "category": "Salary",
            "frequency": "monthly", "start_date": date.today().isoformat(),
            "next_due_date": date.today().isoformat()
        })

        response = client.get("/api/recurring")
        assert response.status_code == 200
        data = response.get_json()
        assert len(data["recurring"]) == 2

    def test_pause_resume_recurring(self, client):
        """Test pausing and resuming recurring transactions."""
        create_resp = client.post("/api/recurring", json={
            "type": "expense", "amount": "50.00", "category": "Transport",
            "frequency": "monthly", "start_date": date.today().isoformat(),
            "next_due_date": date.today().isoformat()
        })
        rt_id = create_resp.get_json()["id"]

        # Pause
        response = client.post(f"/api/recurring/{rt_id}/pause")
        assert response.status_code == 200
        assert response.get_json()["is_paused"] == 1

        # Resume
        response = client.post(f"/api/recurring/{rt_id}/resume")
        assert response.status_code == 200
        assert response.get_json()["is_paused"] == 0

    def test_process_recurring(self, client):
        """Test processing due recurring transactions."""
        today = date.today()

        # Create recurring due today
        client.post("/api/recurring", json={
            "type": "expense", "amount": "50.00", "category": "Transport",
            "frequency": "monthly", "start_date": today.isoformat(),
            "next_due_date": today.isoformat()
        })

        # Process
        response = client.post("/api/recurring/process")
        assert response.status_code == 200
        data = response.get_json()
        assert data["count"] == 1
        assert len(data["generated"]) == 1

        # Verify transaction was created
        tx = data["generated"][0]
        response = client.get(f"/api/transactions/{tx['transaction_id']}")
        assert response.status_code == 200
        tx_data = response.get_json()
        assert tx_data["amount"] == 50.00
        assert tx_data["category"] == "Transport"

    def test_recurring_next_due_calculation(self, client):
        """Test that next_due_date is correctly advanced."""
        today = date.today()

        # Monthly recurring
        create_resp = client.post("/api/recurring", json={
            "type": "expense", "amount": "50.00", "category": "Transport",
            "frequency": "monthly", "start_date": today.isoformat(),
            "next_due_date": today.isoformat()
        })
        rt_id = create_resp.get_json()["id"]

        # Process
        client.post("/api/recurring/process")

        # Check next due date
        response = client.get(f"/api/recurring/{rt_id}")
        rt = response.get_json()
        next_due = date.fromisoformat(rt["next_due_date"])

        # Should be next month
        if today.month == 12:
            expected = today.replace(year=today.year + 1, month=1)
        else:
            expected = today.replace(month=today.month + 1)
        assert next_due == expected

    def test_recurring_end_date(self, client):
        """Test recurring transaction with end date."""
        today = date.today()
        end_date = today + timedelta(days=15)

        create_resp = client.post("/api/recurring", json={
            "type": "expense", "amount": "50.00", "category": "Transport",
            "frequency": "daily", "start_date": today.isoformat(),
            "next_due_date": today.isoformat(),
            "end_date": end_date.isoformat()
        })
        rt_id = create_resp.get_json()["id"]

        # Process multiple times
        for _ in range(5):
            client.post("/api/recurring/process")

        # Check it's still active (within end date)
        response = client.get(f"/api/recurring/{rt_id}")
        rt = response.get_json()
        assert rt["is_active"] == 1

    def test_recurring_isolation(self, client, other_client):
        """Test that recurring transactions are isolated per user."""
        create_resp = client.post("/api/recurring", json={
            "type": "expense", "amount": "50.00", "category": "Transport",
            "frequency": "monthly", "start_date": date.today().isoformat(),
            "next_due_date": date.today().isoformat()
        })
        rt_id = create_resp.get_json()["id"]

        # Other user cannot access
        assert other_client.get(f"/api/recurring/{rt_id}").status_code == 404

    def test_recurring_validation(self, client):
        """Test recurring transaction validation."""
        # Invalid frequency
        response = client.post("/api/recurring", json={
            "type": "expense", "amount": "50.00", "category": "Transport",
            "frequency": "hourly", "start_date": date.today().isoformat(),
            "next_due_date": date.today().isoformat()
        })
        assert response.status_code == 400


class TestFinancialGoals:
    """Test financial goals functionality."""

    def test_create_goal(self, client):
        """Test creating a financial goal."""
        response = client.post("/api/goals", json={
            "name": "Emergency Fund",
            "target_amount": "10000.00",
            "current_amount": "1000.00",
            "target_date": (date.today() + timedelta(days=365)).isoformat(),
            "description": "Build emergency fund"
        })
        assert response.status_code == 201
        data = response.get_json()
        assert data["name"] == "Emergency Fund"
        assert data["target_amount_cents"] == 1000000

    def test_list_goals(self, client):
        """Test listing financial goals."""
        client.post("/api/goals", json={
            "name": "Goal 1", "target_amount": "1000.00", "current_amount": "100.00"
        })
        client.post("/api/goals", json={
            "name": "Goal 2", "target_amount": "5000.00", "current_amount": "0.00"
        })

        response = client.get("/api/goals")
        assert response.status_code == 200
        data = response.get_json()
        assert len(data["goals"]) == 2

    def test_get_goal_with_progress(self, client):
        """Test getting goal with progress calculation."""
        create_resp = client.post("/api/goals", json={
            "name": "Test Goal", "target_amount": "1000.00", "current_amount": "250.00"
        })
        goal_id = create_resp.get_json()["id"]

        response = client.get(f"/api/goals/{goal_id}")
        assert response.status_code == 200
        data = response.get_json()
        assert data["progress_pct"] == 25.0
        assert data["remaining_amount"] == 750.0
        assert data["is_completed"] == False

    def test_add_contribution(self, client):
        """Test adding contribution to a goal."""
        create_resp = client.post("/api/goals", json={
            "name": "Test Goal", "target_amount": "1000.00", "current_amount": "0.00"
        })
        goal_id = create_resp.get_json()["id"]

        # Add contribution
        response = client.post(f"/api/goals/{goal_id}/contributions", json={
            "amount": "250.00",
            "note": "First contribution",
            "date": date.today().isoformat()
        })
        assert response.status_code == 201
        data = response.get_json()
        assert data["progress"]["current_amount"] == 250.0
        assert data["progress"]["progress_pct"] == 25.0

    def test_goal_completion(self, client):
        """Test goal completion when target reached."""
        create_resp = client.post("/api/goals", json={
            "name": "Test Goal", "target_amount": "1000.00", "current_amount": "900.00"
        })
        goal_id = create_resp.get_json()["id"]

        # Add contribution that completes the goal
        response = client.post(f"/api/goals/{goal_id}/contributions", json={
            "amount": "150.00",
            "note": "Final contribution",
            "date": date.today().isoformat()
        })
        assert response.status_code == 201
        data = response.get_json()
        assert data["progress"]["is_completed"] == True
        assert data["progress"]["current_amount"] == 1050.0

    def test_list_contributions(self, client):
        """Test listing goal contributions."""
        create_resp = client.post("/api/goals", json={
            "name": "Test Goal", "target_amount": "1000.00"
        })
        goal_id = create_resp.get_json()["id"]

        client.post(f"/api/goals/{goal_id}/contributions", json={
            "amount": "100.00", "date": date.today().isoformat()
        })
        client.post(f"/api/goals/{goal_id}/contributions", json={
            "amount": "200.00", "date": date.today().isoformat()
        })

        response = client.get(f"/api/goals/{goal_id}/contributions")
        assert response.status_code == 200
        data = response.get_json()
        assert len(data["contributions"]) == 2

    def test_goal_validation(self, client):
        """Test goal input validation."""
        # Negative target
        response = client.post("/api/goals", json={
            "name": "Test", "target_amount": "-100.00"
        })
        assert response.status_code == 400

        # Invalid target date format
        response = client.post("/api/goals", json={
            "name": "Test", "target_amount": "100.00", "target_date": "invalid"
        })
        assert response.status_code == 400


class TestSubscriptions:
    """Test subscription management functionality."""

    def test_create_subscription(self, client):
        """Test creating a subscription."""
        response = client.post("/api/subscriptions", json={
            "name": "Netflix",
            "amount": "15.99",
            "currency": "USD",
            "billing_cycle": "monthly",
            "renewal_date": (date.today() + timedelta(days=15)).isoformat(),
            "category": "Entertainment"
        })
        assert response.status_code == 201
        data = response.get_json()
        assert data["name"] == "Netflix"
        assert data["billing_cycle"] == "monthly"
        assert data["amount_cents"] == 1599

    def test_list_subscriptions(self, client):
        """Test listing subscriptions."""
        client.post("/api/subscriptions", json={
            "name": "Sub 1", "amount": "10.00", "billing_cycle": "monthly",
            "renewal_date": (date.today() + timedelta(days=10)).isoformat()
        })
        client.post("/api/subscriptions", json={
            "name": "Sub 2", "amount": "100.00", "billing_cycle": "yearly",
            "renewal_date": (date.today() + timedelta(days=30)).isoformat()
        })

        response = client.get("/api/subscriptions")
        assert response.status_code == 200
        data = response.get_json()
        assert len(data["subscriptions"]) == 2

    def test_upcoming_renewals(self, client):
        """Test getting upcoming subscription renewals."""
        today = date.today()

        # Renewal in 5 days
        client.post("/api/subscriptions", json={
            "name": "Soon", "amount": "10.00", "billing_cycle": "monthly",
            "renewal_date": (today + timedelta(days=5)).isoformat()
        })

        # Renewal in 45 days (beyond default 30)
        client.post("/api/subscriptions", json={
            "name": "Later", "amount": "100.00", "billing_cycle": "yearly",
            "renewal_date": (today + timedelta(days=45)).isoformat()
        })

        response = client.get("/api/subscriptions/upcoming")
        assert response.status_code == 200
        data = response.get_json()
        assert len(data["subscriptions"]) == 1
        assert data["subscriptions"][0]["name"] == "Soon"

    def test_subscription_totals(self, client):
        """Test subscription totals calculation."""
        client.post("/api/subscriptions", json={
            "name": "Monthly", "amount": "10.00", "billing_cycle": "monthly",
            "renewal_date": (date.today() + timedelta(days=10)).isoformat()
        })
        client.post("/api/subscriptions", json={
            "name": "Yearly", "amount": "120.00", "billing_cycle": "yearly",
            "renewal_date": (date.today() + timedelta(days=30)).isoformat()
        })

        response = client.get("/api/subscriptions/totals")
        assert response.status_code == 200
        data = response.get_json()
        assert data["monthly_total"] == 20.0  # 10 + 120/12
        assert data["yearly_total"] == 240.0  # 10*12 + 120
        assert data["subscription_count"] == 2

    def test_custom_billing_cycle(self, client):
        """Test subscription with custom billing cycle."""
        response = client.post("/api/subscriptions", json={
            "name": "Custom", "amount": "30.00", "billing_cycle": "custom",
            "custom_cycle_days": 45,
            "renewal_date": (date.today() + timedelta(days=10)).isoformat()
        })
        assert response.status_code == 201
        data = response.get_json()
        assert data["custom_cycle_days"] == 45

    def test_subscription_validation(self, client):
        """Test subscription input validation."""
        # Missing custom_cycle_days for custom cycle
        response = client.post("/api/subscriptions", json={
            "name": "Test", "amount": "10.00", "billing_cycle": "custom",
            "renewal_date": (date.today() + timedelta(days=10)).isoformat()
        })
        assert response.status_code == 400


class TestNotifications:
    """Test notification system."""

    def test_list_notifications(self, client):
        """Test listing notifications."""
        # Create a budget that will trigger notification
        today = date.today()
        start = today.replace(day=1)

        client.post("/api/budgets", json={
            "name": "Test Budget", "period": "monthly", "category": "Food",
            "amount": "100.00", "start_date": start.isoformat()
        })

        # Add expense to exceed budget
        client.post("/api/transactions", json={
            "type": "expense", "amount": "150.00", "category": "Food",
            "date": today.isoformat()
        })

        # Run notification checks
        client.post("/api/notifications/check")

        # List notifications
        response = client.get("/api/notifications")
        assert response.status_code == 200
        data = response.get_json()
        assert len(data["notifications"]) > 0

    def test_unread_count(self, client):
        """Test getting unread notification count."""
        response = client.get("/api/notifications/unread-count")
        assert response.status_code == 200
        data = response.get_json()
        assert "unread_count" in data

    def test_mark_read(self, client):
        """Test marking notification as read."""
        # Create notification via budget exceed
        today = date.today()
        start = today.replace(day=1)

        client.post("/api/budgets", json={
            "name": "Test Budget", "period": "monthly", "category": "Food",
            "amount": "100.00", "start_date": start.isoformat()
        })
        client.post("/api/transactions", json={
            "type": "expense", "amount": "150.00", "category": "Food",
            "date": today.isoformat()
        })
        client.post("/api/notifications/check")

        # Get notification
        response = client.get("/api/notifications")
        notif = response.get_json()["notifications"][0]
        notif_id = notif["id"]

        # Mark as read
        response = client.post(f"/api/notifications/{notif_id}/read")
        assert response.status_code == 200

        # Verify it's read
        response = client.get(f"/api/notifications/{notif_id}")
        assert response.get_json()["is_read"] == 1

    def test_mark_all_read(self, client):
        """Test marking all notifications as read."""
        # Create multiple notifications
        for i in range(3):
            today = date.today()
            start = today.replace(day=1)
            client.post("/api/budgets", json={
                "name": f"Budget {i}", "period": "monthly", "category": "Food",
                "amount": "100.00", "start_date": start.isoformat()
            })
            client.post("/api/transactions", json={
                "type": "expense", "amount": "150.00", "category": "Food",
                "date": today.isoformat()
            })
        client.post("/api/notifications/check")

        response = client.post("/api/notifications/read-all")
        assert response.status_code == 200
        data = response.get_json()
        assert data["marked"] >= 3

        # Verify unread count is 0
        response = client.get("/api/notifications/unread-count")
        assert response.get_json()["unread_count"] == 0

    def test_delete_notification(self, client):
        """Test deleting a notification."""
        today = date.today()
        start = today.replace(day=1)

        client.post("/api/budgets", json={
            "name": "Test Budget", "period": "monthly", "category": "Food",
            "amount": "100.00", "start_date": start.isoformat()
        })
        client.post("/api/transactions", json={
            "type": "expense", "amount": "150.00", "category": "Food",
            "date": today.isoformat()
        })
        client.post("/api/notifications/check")

        response = client.get("/api/notifications")
        notif_id = response.get_json()["notifications"][0]["id"]

        response = client.delete(f"/api/notifications/{notif_id}")
        assert response.status_code == 204

        response = client.get(f"/api/notifications/{notif_id}")
        assert response.status_code == 404


class TestForecasting:
    """Test financial forecasting."""

    def test_forecast_insufficient_data(self, client):
        """Test forecast with insufficient data."""
        # No transactions
        response = client.get("/api/forecast")
        assert response.status_code == 200
        data = response.get_json()
        assert data["forecast"] is None
        assert "Insufficient" in data["message"]

    def test_forecast_with_data(self, client):
        """Test forecast with sufficient historical data."""
        today = date.today()

        # Add 6 months of data
        for i in range(6):
            month_date = (today.replace(day=1) - timedelta(days=i*30)).replace(day=15)
            client.post("/api/transactions", json={
                "type": "income", "amount": "5000.00", "category": "Salary",
                "date": month_date.isoformat()
            })
            client.post("/api/transactions", json={
                "type": "expense", "amount": "2000.00", "category": "Rent",
                "date": month_date.isoformat()
            })
            client.post("/api/transactions", json={
                "type": "expense", "amount": "500.00", "category": "Food",
                "date": month_date.isoformat()
            })

        response = client.get("/api/forecast?months=6")
        assert response.status_code == 200
        data = response.get_json()
        assert data["forecast"] is not None
        forecast = data["forecast"]
        assert "predicted_income" in forecast
        assert "predicted_expense" in forecast
        assert "predicted_savings" in forecast
        assert "category_forecasts" in forecast
        assert "confidence" in forecast
        assert "disclaimer" in forecast
        assert forecast["confidence"] in ["high", "medium", "low"]

    def test_forecast_validation(self, client):
        """Test forecast parameter validation."""
        response = client.get("/api/forecast?months=0")
        assert response.status_code == 400

        response = client.get("/api/forecast?months=37")
        assert response.status_code == 400


class TestRelease2Integration:
    """Integration tests for Release 2 features working together."""

    def test_budget_notification_on_exceed(self, client):
        """Test that budget exceed triggers notification."""
        today = date.today()
        start = today.replace(day=1)

        client.post("/api/budgets", json={
            "name": "Food Budget", "period": "monthly", "category": "Food",
            "amount": "100.00", "start_date": start.isoformat()
        })

        # Add transaction exceeding budget
        client.post("/api/transactions", json={
            "type": "expense", "amount": "150.00", "category": "Food",
            "date": today.isoformat()
        })

        # Run notification check
        response = client.post("/api/notifications/check")
        assert response.status_code == 200
        results = response.get_json()
        assert len(results["budget_notifications"]) > 0

    def test_recurring_generates_notification(self, client):
        """Test that due recurring transactions trigger notifications."""
        today = date.today()

        client.post("/api/recurring", json={
            "type": "expense", "amount": "50.00", "category": "Transport",
            "frequency": "monthly", "start_date": today.isoformat(),
            "next_due_date": today.isoformat()
        })

        # Run notification check
        response = client.post("/api/notifications/check")
        assert response.status_code == 200
        results = response.get_json()
        assert len(results["recurring_notifications"]) > 0

    def test_subscription_renewal_notification(self, client):
        """Test subscription renewal notification."""
        today = date.today()

        # Subscription renewing in 3 days
        client.post("/api/subscriptions", json={
            "name": "Netflix", "amount": "15.99", "billing_cycle": "monthly",
            "renewal_date": (today + timedelta(days=3)).isoformat()
        })

        response = client.post("/api/notifications/check")
        assert response.status_code == 200
        results = response.get_json()
        assert len(results["subscription_notifications"]) > 0

    def test_goal_milestone_notification(self, client):
        """Test goal milestone notification."""
        # Create goal at 40%
        create_resp = client.post("/api/goals", json={
            "name": "Savings Goal", "target_amount": "1000.00", "current_amount": "400.00"
        })
        goal_id = create_resp.get_json()["id"]

        # Add contribution to reach 50%
        client.post(f"/api/goals/{goal_id}/contributions", json={
            "amount": "100.00", "date": date.today().isoformat()
        })

        response = client.post("/api/notifications/check")
        assert response.status_code == 200
        results = response.get_json()
        assert len(results["goal_notifications"]) > 0

    def test_goal_completion_notification(self, client):
        """Test goal completion notification."""
        create_resp = client.post("/api/goals", json={
            "name": "Savings Goal", "target_amount": "1000.00", "current_amount": "900.00"
        })
        goal_id = create_resp.get_json()["id"]

        # Add contribution to complete
        client.post(f"/api/goals/{goal_id}/contributions", json={
            "amount": "150.00", "date": date.today().isoformat()
        })

        response = client.post("/api/notifications/check")
        assert response.status_code == 200
        results = response.get_json()
        assert len(results["goal_notifications"]) > 0

    def test_user_isolation_all_features(self, client, other_client):
        """Test that all Release 2 features maintain user isolation."""
        # User 1 creates data for all features
        today = date.today()
        start = today.replace(day=1)

        # Budget
        budget_resp = client.post("/api/budgets", json={
            "name": "User 1 Budget", "period": "monthly", "amount": "100.00", "start_date": start.isoformat()
        })
        budget_id = budget_resp.get_json()["id"]

        # Recurring
        recurring_resp = client.post("/api/recurring", json={
            "type": "expense", "amount": "50.00", "category": "Transport",
            "frequency": "monthly", "start_date": today.isoformat(),
            "next_due_date": today.isoformat()
        })
        recurring_id = recurring_resp.get_json()["id"]

        # Goal
        goal_resp = client.post("/api/goals", json={
            "name": "User 1 Goal", "target_amount": "1000.00"
        })
        goal_id = goal_resp.get_json()["id"]

        # Subscription
        sub_resp = client.post("/api/subscriptions", json={
            "name": "User 1 Sub", "amount": "10.00", "billing_cycle": "monthly",
            "renewal_date": (today + timedelta(days=10)).isoformat()
        })
        sub_id = sub_resp.get_json()["id"]

        # User 2 should not see any of these
        test_cases = [
            ("/api/budgets", budget_id),
            ("/api/recurring", recurring_id),
            ("/api/goals", goal_id),
            ("/api/subscriptions", sub_id),
        ]
        for endpoint, item_id in test_cases:
            list_resp = other_client.get(endpoint)
            key = endpoint.split('/')[-1]  # budgets, recurring, goals, subscriptions
            items = list_resp.get_json()[key]
            assert not any(item["id"] == item_id for item in items)

            # Direct access should 404
            assert other_client.get(f"{endpoint}/{item_id}").status_code == 404