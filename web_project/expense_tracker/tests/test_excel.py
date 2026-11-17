"""Tests for Excel Import and Export features using openpyxl.

Verifies:
1. Template download (/api/excel/template and /api/guest/excel/template) includes 7 columns with 'Transaction Type'.
2. Registered user Excel export includes 'Transaction Type' column (Income/Expense).
3. Data isolation in export: users only export their own records; admins export their own data.
4. Excel template generation and import with 'Transaction Type'.
5. Legacy Excel import without 'Transaction Type' (graceful fallback).
6. Validation errors for invalid transaction type or mismatched categories.
7. Guest Excel export and import isolated from registered users.
8. Security defenses (CSV/Excel formula injection prevention, .xlsx extension validation, 401 on unauthenticated requests).
"""
import io
from datetime import date
from decimal import Decimal

import openpyxl
import pytest
from app import db
from app.auth import hash_password


def _create_sample_excel(rows: list[list], headers: list[str] = None) -> io.BytesIO:
    """Helper to generate in-memory Excel workbook for upload testing."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Expenses"
    if headers is None:
        headers = ["Date", "Title", "Transaction Type", "Category", "Amount", "Payment Method", "Description"]
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def test_download_excel_template(client, unauth_client):
    """Excel template is downloadable for both registered users and unauthenticated guests,
    and includes the 'Transaction Type' column at position 3."""
    expected_headers = ["Date", "Title", "Transaction Type", "Category", "Amount", "Payment Method", "Description"]

    res_auth = client.get("/api/excel/template")
    assert res_auth.status_code == 200
    assert "spreadsheetml.sheet" in res_auth.mimetype

    wb = openpyxl.load_workbook(io.BytesIO(res_auth.data))
    ws = wb.active
    headers = [ws.cell(row=4, column=c).value for c in range(1, 8)]
    assert headers == expected_headers

    # Guest endpoint
    res_guest = unauth_client.get("/api/guest/excel/template")
    assert res_guest.status_code == 200
    assert "spreadsheetml.sheet" in res_guest.mimetype
    wb_guest = openpyxl.load_workbook(io.BytesIO(res_guest.data))
    ws_guest = wb_guest.active
    headers_guest = [ws_guest.cell(row=4, column=c).value for c in range(1, 8)]
    assert headers_guest == expected_headers


def test_user_excel_export_includes_transaction_type(client):
    """Authenticated user can export their transactions to Excel;
    verifies:
    - 7 columns with 'Transaction Type' at column 3 (after Title, before Category).
    - Database 'type' correctly displays 'Income' and 'Expense'.
    - Amount is placed at column 5 with '#,##0.00' formatting.
    - Financial summary totals (Income, Expense, Net Balance) are exact.
    """
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

    # Check headers at row 4
    headers = [ws.cell(row=4, column=c).value for c in range(1, 8)]
    assert headers == ["Date", "Title", "Transaction Type", "Category", "Amount", "Payment Method", "Description"]

    # Check data rows exist (Row 5 & 6)
    row_data = []
    for r in (5, 6):
        row_data.append({
            "date": ws.cell(row=r, column=1).value,
            "title": ws.cell(row=r, column=2).value,
            "type": ws.cell(row=r, column=3).value,
            "category": ws.cell(row=r, column=4).value,
            "amount": ws.cell(row=r, column=5).value,
            "pm": ws.cell(row=r, column=6).value,
            "desc": ws.cell(row=r, column=7).value,
        })

    # Validate Expense row
    expense_row = next(r for r in row_data if "Office Chair" in str(r["title"]))
    assert expense_row["type"] == "Expense"
    assert expense_row["category"] == "Shopping"
    assert expense_row["amount"] == 150.00

    # Validate Income row
    income_row = next(r for r in row_data if "Bonus Payment" in str(r["title"]))
    assert income_row["type"] == "Income"
    assert income_row["category"] == "Salary"
    assert income_row["amount"] == 500.00

    # Validate Summary rows (Row 8 is blank separator, Rows 9-11 are totals)
    summary_labels = [ws.cell(row=r, column=1).value for r in range(8, 13)]
    assert "Total Income" in summary_labels
    assert "Total Expenses" in summary_labels
    assert "Net Balance" in summary_labels

    # Locate each summary row by label
    for r in range(8, 13):
        lbl = ws.cell(row=r, column=1).value
        if lbl == "Total Income":
            assert ws.cell(row=r, column=5).value == 500.00
        elif lbl == "Total Expenses":
            assert ws.cell(row=r, column=5).value == 150.00
        elif lbl == "Net Balance":
            assert ws.cell(row=r, column=5).value == 350.00


def test_export_data_isolation(app_instance):
    """User A and User B export files contain strictly their own transactions."""
    with app_instance.app_context():
        p_hash = hash_password("Password123!")
        u_alpha_id = db.create_user("Alpha User", "alpha_exp@example.com", p_hash, role="user")
        u_beta_id = db.create_user("Beta User", "beta_exp@example.com", p_hash, role="user")

    client_a = app_instance.test_client()
    with client_a.session_transaction() as sess:
        sess["user_id"] = u_alpha_id
        sess["user_name"] = "Alpha User"
        sess["user_email"] = "alpha_exp@example.com"
        sess["user_role"] = "user"

    client_b = app_instance.test_client()
    with client_b.session_transaction() as sess:
        sess["user_id"] = u_beta_id
        sess["user_name"] = "Beta User"
        sess["user_email"] = "beta_exp@example.com"
        sess["user_role"] = "user"

    # User A records an expense
    client_a.post("/api/transactions", json={
        "type": "expense",
        "amount": "99.00",
        "category": "Food",
        "note": "Alpha Confidential Lunch",
        "date": "2026-11-01",
    })

    # User B records an income
    client_b.post("/api/transactions", json={
        "type": "income",
        "amount": "4500.00",
        "category": "Salary",
        "note": "Beta Secret Payout",
        "date": "2026-11-01",
    })

    # Export User A
    res_a = client_a.get("/api/excel/export")
    wb_a = openpyxl.load_workbook(io.BytesIO(res_a.data), data_only=True)
    titles_a = [ws_cell.value for ws_cell in wb_a.active["B"] if ws_cell.value]
    assert any("Alpha Confidential Lunch" in str(t) for t in titles_a)
    assert not any("Beta Secret Payout" in str(t) for t in titles_a)

    # Export User B
    res_b = client_b.get("/api/excel/export")
    wb_b = openpyxl.load_workbook(io.BytesIO(res_b.data), data_only=True)
    titles_b = [ws_cell.value for ws_cell in wb_b.active["B"] if ws_cell.value]
    assert any("Beta Secret Payout" in str(t) for t in titles_b)
    assert not any("Alpha Confidential Lunch" in str(t) for t in titles_b)


def test_admin_excel_export(admin_client):
    """Admin user can export their personal transactions via /api/excel/export."""
    today_str = date.today().strftime("%Y-%m-%d")
    admin_client.post("/api/transactions", json={
        "type": "expense",
        "amount": "300.00",
        "category": "Bills",
        "note": "Admin Server Hosting",
        "date": today_str,
    })

    res = admin_client.get("/api/excel/export")
    assert res.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(res.data), data_only=True)
    ws = wb.active
    assert ws.cell(row=4, column=3).value == "Transaction Type"
    assert ws.cell(row=5, column=3).value == "Expense"
    assert ws.cell(row=5, column=5).value == 300.00


def test_unauthenticated_export_blocked(unauth_client):
    """Unauthenticated visitors cannot access registered export endpoint."""
    res = unauth_client.get("/api/excel/export")
    assert res.status_code == 401


def test_user_excel_import_with_transaction_type(client, app_instance):
    """User can import .xlsx file containing 'Transaction Type' column;
    Income and Expense records are created with correct types."""
    today_str = date.today().strftime("%Y-%m-%d")

    file_buf = _create_sample_excel([
        [today_str, "Team Lunch", "Expense", "Food", 65.50, "Credit Card", "Project celebration"],
        [today_str, "Client Retainer", "Income", "Freelance", 1200.00, "Bank Transfer", "Monthly retainer"],
        [today_str, "Train Pass", "Expense", "Transport", 45.00, "Cash", "Monthly pass"],
    ])

    data = {"file": (file_buf, "expenses_with_type.xlsx")}
    res = client.post("/api/excel/import", data=data, content_type="multipart/form-data")
    assert res.status_code == 200
    resp_json = res.get_json()
    assert resp_json["success"] is True
    assert resp_json["success_count"] == 3
    assert resp_json["rejected_count"] == 0

    # Verify transactions in user's list have correct type
    res_list = client.get(f"/api/transactions?period=month&date={today_str}")
    items = res_list.get_json()

    retainer = next(i for i in items if "Client Retainer" in i["note"])
    assert retainer["type"] == "income"
    assert retainer["amount"] == 1200.00

    lunch = next(i for i in items if "Team Lunch" in i["note"])
    assert lunch["type"] == "expense"
    assert lunch["amount"] == 65.50


def test_user_excel_import_legacy_template(client):
    """User can import a legacy 6-column sheet without 'Transaction Type' column;
    type is safely derived from category for backwards compatibility."""
    today_str = date.today().strftime("%Y-%m-%d")

    legacy_headers = ["Date", "Title", "Category", "Amount", "Payment Method", "Description"]
    file_buf = _create_sample_excel([
        [today_str, "Legacy Dinner", "Food", 40.00, "Cash", "Dinner with client"],
        [today_str, "Legacy Consulting", "Freelance", 800.00, "Bank Transfer", "Advisory"],
    ], headers=legacy_headers)

    data = {"file": (file_buf, "legacy_expenses.xlsx")}
    res = client.post("/api/excel/import", data=data, content_type="multipart/form-data")
    assert res.status_code == 200
    assert res.get_json()["success_count"] == 2

    res_list = client.get(f"/api/transactions?period=month&date={today_str}")
    items = res_list.get_json()
    legacy_dinner = next(i for i in items if "Legacy Dinner" in i["note"])
    assert legacy_dinner["type"] == "expense"
    legacy_consult = next(i for i in items if "Legacy Consulting" in i["note"])
    assert legacy_consult["type"] == "income"


def test_import_validation_and_partial_rejection(client):
    """Import reports rejected rows for invalid categories, amounts, or invalid transaction types."""
    today_str = date.today().strftime("%Y-%m-%d")

    file_buf = _create_sample_excel([
        [today_str, "Valid Expense", "Expense", "Food", 25.00, "Cash", "Groceries"],
        [today_str, "Bad Category", "Expense", "SpaceTravel", 1000.00, "Card", "Invalid category"],
        [today_str, "Bad Amount", "Expense", "Rent", -50.00, "Cash", "Negative amount not allowed"],
        [today_str, "Bad Type", "CryptoTransfer", "Food", 100.00, "Card", "Invalid type"],
        [today_str, "Mismatched Type", "Income", "Rent", 500.00, "Cash", "Rent is expense not income"],
    ])

    data = {"file": (file_buf, "test_mixed.xlsx")}
    res = client.post("/api/excel/import", data=data, content_type="multipart/form-data")
    assert res.status_code == 200
    resp_json = res.get_json()
    assert resp_json["success_count"] == 1
    assert resp_json["rejected_count"] == 4
    assert len(resp_json["errors"]) == 4
    assert any("SpaceTravel" in e["error"] for e in resp_json["errors"])
    assert any("CryptoTransfer" in e["error"] for e in resp_json["errors"])
    assert any("Rent" in e["error"] for e in resp_json["errors"])


def test_import_rejects_non_xlsx_and_missing_file(client):
    """Only .xlsx files are permitted; other extensions or missing files are rejected."""
    # No file uploaded
    res_none = client.post("/api/excel/import", data={})
    assert res_none.status_code == 400

    # .csv file rejected
    fake_csv = io.BytesIO(b"Date,Title,Transaction Type,Category,Amount\n2026-11-11,Test,Expense,Food,10")
    res_csv = client.post("/api/excel/import", data={"file": (fake_csv, "test.csv")}, content_type="multipart/form-data")
    assert res_csv.status_code == 400
    assert "xlsx" in res_csv.get_json()["error"].lower()


def test_import_formula_injection_defense(client):
    """Cells starting with formula symbols (=, +, -, @) are sanitized upon import."""
    today_str = date.today().strftime("%Y-%m-%d")

    file_buf = _create_sample_excel([
        [today_str, "=cmd|' /C calc'!A0", "Expense", "Food", 30.00, "+PAYMENT", "@formula note"],
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
    """Guest can import Excel into demo data and export with Transaction Type without affecting registered users."""
    unauth_client.post("/guest/start", follow_redirects=True)
    today_str = date.today().strftime("%Y-%m-%d")

    # 1. Guest Export
    res_exp = unauth_client.get("/api/guest/excel/export")
    assert res_exp.status_code == 200
    assert "guest_demo_expenses_" in res_exp.headers["Content-Disposition"]

    wb = openpyxl.load_workbook(io.BytesIO(res_exp.data), data_only=True)
    ws = wb.active
    # Must have headers including Transaction Type at col 3
    assert ws.cell(row=4, column=1).value == "Date"
    assert ws.cell(row=4, column=2).value == "Title"
    assert ws.cell(row=4, column=3).value == "Transaction Type"
    assert ws.cell(row=4, column=4).value == "Category"
    assert ws.cell(row=4, column=5).value == "Amount"

    # Check that demo transactions have correct type
    types = [ws.cell(row=r, column=3).value for r in range(5, 10) if ws.cell(row=r, column=3).value]
    assert "Income" in types or "Expense" in types

    # 2. Guest Import
    file_buf = _create_sample_excel([
        [today_str, "Guest Imported Item", "Expense", "Entertainment", 80.00, "Credit Card", "Movie Tickets"],
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
