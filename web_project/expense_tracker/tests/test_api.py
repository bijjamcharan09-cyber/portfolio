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


def test_root_homepage_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Expense Tracker" in html
    assert "Add a transaction" in html
    assert "style.css" in html
    assert "app.js" in html


def test_vercel_index_aliases_render_homepage(client):
    resp_index = client.get("/api/index")
    assert resp_index.status_code == 200
    assert "Expense Tracker" in resp_index.get_data(as_text=True)

    resp_py = client.get("/api/index.py")
    assert resp_py.status_code == 200
    assert "Expense Tracker" in resp_py.get_data(as_text=True)


def test_static_assets_serve_correctly(client):
    resp_css = client.get("/static/style.css")
    assert resp_css.status_code == 200
    assert "text/css" in resp_css.headers.get("Content-Type", "")
    assert len(resp_css.data) > 500

    resp_js = client.get("/static/app.js")
    assert resp_js.status_code == 200
    assert "javascript" in resp_js.headers.get("Content-Type", "")
    assert len(resp_js.data) > 500


def test_vercel_path_middleware_routing():
    from api.index import app as vercel_app
    vclient = vercel_app.test_client()

    # Client visiting root on Vercel with rewrite
    resp_root = vclient.get("/api/index", headers={"x-matched-path": "/"})
    assert resp_root.status_code == 200
    assert "Expense Tracker" in resp_root.get_data(as_text=True)

    # Client visiting API endpoint on Vercel with rewrite
    resp_api = vclient.get("/api/index", headers={"x-matched-path": "/api/categories"})
    assert resp_api.status_code == 200
    assert "expense" in resp_api.json

    # Client visiting static asset on Vercel with rewrite
    resp_static = vclient.get("/api/index", headers={"x-matched-path": "/static/style.css"})
    assert resp_static.status_code == 200

    # Query string stripping in x-matched-path
    resp_qs = vclient.get("/api/index", headers={"x-matched-path": "/?foo=bar"})
    assert resp_qs.status_code == 200
    assert "Expense Tracker" in resp_qs.get_data(as_text=True)

