from datetime import date

from app.services.exchange import ExchangeError
from app.services.reports import date_range


def add(client, **overrides):
    body = {"type": "expense", "amount": 12.5, "category": "Food", "date": "2026-09-10", "note": "lunch"}
    body.update(overrides)
    return client.post("/api/transactions", json=body)


def test_create_and_list(client):
    assert add(client).status_code == 201
    rows = client.get("/api/transactions?period=month&date=2026-09-15").get_json()
    assert len(rows) == 1 and rows[0]["amount"] == 12.5


def test_rejects_bad_input(client):
    for bad in ({"amount": -5}, {"amount": "abc"}, {"category": "Salary"}, {"date": "10/09/2026"}, {"type": "gift"}):
        assert add(client, **bad).status_code == 400


def test_delete(client):
    tx_id = add(client).get_json()["id"]
    assert client.delete(f"/api/transactions/{tx_id}").status_code == 204
    assert client.delete(f"/api/transactions/{tx_id}").status_code == 404


def test_summary_totals(client):
    add(client, type="income", category="Salary", amount=1000)
    add(client, amount=250.25)
    add(client, date="2025-01-01", amount=999)  # outside the month, must be ignored
    data = client.get("/api/reports/summary?period=month&date=2026-09-15").get_json()
    assert (data["income"], data["expense"], data["balance"]) == (1000, 250.25, 749.75)


def test_chart_is_png(client):
    add(client)
    for period in ("day", "month", "year", "days"):
        resp = client.get(f"/api/reports/chart.png?period={period}&date=2026-09-15")
        assert resp.status_code == 200 and resp.data.startswith(b"\x89PNG")


def test_bad_period_is_400(client):
    assert client.get("/api/reports/summary?period=decade").status_code == 400


def test_date_ranges():
    assert date_range("month", date(2026, 2, 10)) == (date(2026, 2, 1), date(2026, 2, 28))
    assert date_range("year", date(2026, 6, 1)) == (date(2026, 1, 1), date(2026, 12, 31))
    assert date_range("days", date(2026, 9, 23), days=7)[0] == date(2026, 9, 17)


def test_convert_uses_rate(client, monkeypatch):
    monkeypatch.setattr("app.api.get_rate", lambda base, target: 2.0)
    add(client, type="income", category="Salary", amount=100)
    data = client.get("/api/convert?to=eur&period=month&date=2026-09-15").get_json()
    assert data["converted"] == 200.0


def test_convert_handles_api_failure(client, monkeypatch):
    def boom(base, target):
        raise ExchangeError("down")
    monkeypatch.setattr("app.api.get_rate", boom)
    assert client.get("/api/convert?to=EUR").status_code == 502
