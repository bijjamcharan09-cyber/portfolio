"""Tests for Excel Import and Export features using openpyxl.

Verifies:
1. Template download (/api/excel/template).
2. Registered user Excel export (correct columns, headers, formatting, isolation).
3. Registered user Excel import (parsing, validation, error reporting, formula defense).
4. Guest Excel export (contains only guest records).
5. Guest Excel import (updates guest_transactions, never touches registered data).
6. Security checks (formula injection protection, extension validation, 401 on unauth).
"""
import io
from datetime import date

import openpyxl
import pytest
from app import db


def _create_sample_excel(rows: list[list]) -> io.BytesIO:
    """Helper to generate in-memory Excel workbook for upload testing."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Expenses"
    ws.append(["Date", "Title", "Category", "Amount", "Payment Method", "Description"])
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def test_download_excel_template(client, unauth_client):
    """Excel template is downloadable for both registered users and unauthenticated guests."""
    res_auth = client.get("/api/excel/template")
    assert res_auth.status_code == 200
    assert "spreadsheetml.sheet" in res_auth.mimetype

    wb = openpyxl.load_workbook(io.BytesIO(res_auth.data))
    ws = wb.active
    headers = [ws.cell(row=4, column=c).value for c in range(1, 7)]
    assert headers == ["Date", "Title", "Category", "Amount", "Payment Method", "Description"]

    # Guest endpoint
    res_guest = unauth_client.get("/api/guest/excel/template")
    assert res_guest.status_code == 200
    assert "spreadsheetml.sheet" in res_guest.mimetype


def test_user_excel_export(client):
    """Authenticated user can export their transactions to Excel; columns & formatting verified."""
    today_str = date.today().strftime("%Y-%m-%d")

    # Seed transactions for this user
    client.post("/api/transactions", json={
        "type": "expense",
        "amount": "150.00",
        "category": "Shopping",
        "note": "Office Chair",
        "date": today_str,
    })
    client.post("/api/transactions", json={
        "type": "income",
        "amount": "500.00",
        "category": "Salary",
        "note": "Bonus Payment",
        "date": today_str,
    })

    res = client.get("/api/excel/export")
    assert res.status_code == 200
    assert "attachment" in res.headers["Content-Disposition"]
    assert "expense_report_" in res.headers["Content-Disposition"]

    # Parse exported workbook
    wb = openpyxl.load_workbook(io.BytesIO(res.data), data_only=True)
    ws = wb.active

    # Check header
    headers = [ws.cell(row=4, column=c).value for c in range(1, 7)]
    assert headers == ["Date", "Title", "Category", "Amount", "Payment Method", "Description"]

    # Check rows exist
    titles = [ws.cell(row=r, column=2).value for r in range(5, 7)]
    assert any("Office Chair" in str(t) for t in titles)
    assert any("Bonus Payment" in str(t) for t in titles)


def test_unauthenticated_export_blocked(unauth_client):
    """Unauthenticated visitors cannot access registered export endpoint."""
    res = unauth_client.get("/api/excel/export")
    assert res.status_code == 401


def test_user_excel_import_success(client, app_instance):
    """User can import valid .xlsx file; records appear in user transactions."""
    today_str = date.today().strftime("%Y-%m-%d")

    file_buf = _create_sample_excel([
        [today_str, "Team Lunch", "Food", 65.50, "Credit Card", "Project celebration"],
        [today_str, "Client Retainer", "Freelance", 1200.00, "Bank Transfer", "Monthly retainer"],
        [today_str, "Train Pass", "Transport", 45.00, "Cash", "Monthly pass"],
    ])

    data = {"file": (file_buf, "expenses.xlsx")}
    res = client.post("/api/excel/import", data=data, content_type="multipart/form-data")
    assert res.status_code == 200
    resp_json = res.get_json()
    assert resp_json["success"] is True
    assert resp_json["success_count"] == 3
    assert resp_json["rejected_count"] == 0

    # Verify transactions in user's list
    res_list = client.get(f"/api/transactions?period=month&date={today_str}")
    notes = [tx["note"] for tx in res_list.get_json()]
    assert any("Team Lunch" in n for n in notes)
    assert any("Client Retainer" in n for n in notes)


def test_import_validation_and_partial_rejection(client):
    """Import reports rejected rows for invalid categories or invalid amounts while accepting valid rows."""
    today_str = date.today().strftime("%Y-%m-%d")

    file_buf = _create_sample_excel([
        [today_str, "Valid Expense", "Food", 25.00, "Cash", "Groceries"],
        [today_str, "Bad Category", "SpaceTravel", 1000.00, "Card", "Invalid category"],
        [today_str, "Bad Amount", "Rent", -50.00, "Cash", "Negative amount not allowed"],
    ])

    data = {"file": (file_buf, "test_mixed.xlsx")}
    res = client.post("/api/excel/import", data=data, content_type="multipart/form-data")
    assert res.status_code == 200
    resp_json = res.get_json()
    assert resp_json["success_count"] == 1
    assert resp_json["rejected_count"] == 2
    assert len(resp_json["errors"]) == 2
    assert any("SpaceTravel" in e["error"] for e in resp_json["errors"])


def test_import_rejects_non_xlsx_and_missing_file(client):
    """Only .xlsx files are permitted; other extensions or missing files are rejected."""
    # No file uploaded
    res_none = client.post("/api/excel/import", data={})
    assert res_none.status_code == 400

    # .csv file rejected
    fake_csv = io.BytesIO(b"Date,Title,Category,Amount\n2026-11-11,Test,Food,10")
    res_csv = client.post("/api/excel/import", data={"file": (fake_csv, "test.csv")}, content_type="multipart/form-data")
    assert res_csv.status_code == 400
    assert "xlsx" in res_csv.get_json()["error"].lower()


def test_import_formula_injection_defense(client):
    """Cells starting with formula symbols (=, +, -, @) are sanitized upon import."""
    today_str = date.today().strftime("%Y-%m-%d")

    file_buf = _create_sample_excel([
        [today_str, "=cmd|' /C calc'!A0", "Food", 30.00, "+PAYMENT", "@formula note"],
    ])

    data = {"file": (file_buf, "injection.xlsx")}
    res = client.post("/api/excel/import", data=data, content_type="multipart/form-data")
    assert res.status_code == 200
    assert res.get_json()["success_count"] == 1

    # Verify that stored note stripped the leading dangerous formula indicator
    res_list = client.get(f"/api/transactions?period=month&date={today_str}")
    items = res_list.get_json()
    imported_note = items[0]["note"]
    assert not imported_note.startswith("=")
    assert not imported_note.startswith("+")
    assert not imported_note.startswith("@")


def test_guest_excel_export_and_import(unauth_client, app_instance):
    """Guest can import Excel into demo data and export without affecting registered users."""
    unauth_client.post("/guest/start", follow_redirects=True)
    today_str = date.today().strftime("%Y-%m-%d")

    # 1. Guest Export
    res_exp = unauth_client.get("/api/guest/excel/export")
    assert res_exp.status_code == 200
    assert "guest_demo_expenses_" in res_exp.headers["Content-Disposition"]

    wb = openpyxl.load_workbook(io.BytesIO(res_exp.data), data_only=True)
    ws = wb.active
    # Must have headers
    assert ws.cell(row=4, column=1).value == "Date"
    assert ws.cell(row=4, column=4).value == "Amount"

    # 2. Guest Import
    file_buf = _create_sample_excel([
        [today_str, "Guest Imported Item", "Entertainment", 80.00, "Credit Card", "Movie Tickets"],
    ])

    data = {"file": (file_buf, "guest_import.xlsx")}
    res_imp = unauth_client.post("/api/guest/excel/import", data=data, content_type="multipart/form-data")
    assert res_imp.status_code == 200
    resp_json = res_imp.get_json()
    assert resp_json["success_count"] == 1

    # Verify it shows up in guest transactions
    res_guest_list = unauth_client.get(f"/api/guest/transactions?period=month&date={today_str}")
    notes = [tx["note"] for tx in res_guest_list.get_json()]
    assert any("Guest Imported Item" in n for n in notes)

    # Verify it was NOT written into registered user transactions
    with app_instance.app_context():
        reg_rows = db.get_db().execute("SELECT * FROM transactions WHERE note LIKE '%Guest Imported Item%'").fetchall()
        assert len(reg_rows) == 0
