"""Excel Import and Export Service using openpyxl.

Provides secure parsing, validation, and generation of .xlsx spreadsheets
for both registered users and guest sessions.
Includes strict protection against CSV/Excel Formula Injection,
enforces file-size limits, and applies professional financial formatting.
"""
import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from ..validators import CATEGORIES, ValidationError

# Formula injection prefixes that must be sanitized
DANGEROUS_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "%")

# Standardized column headers expected in Excel templates
EXPECTED_COLUMNS = ["Date", "Title", "Category", "Amount", "Payment Method", "Description"]


def sanitize_text_for_excel(value: str) -> str:
    """Prepend a single quote if string starts with formula symbols to prevent formula injection."""
    if not value or not isinstance(value, str):
        return ""
    stripped = value.strip()
    if any(stripped.startswith(p) for p in DANGEROUS_FORMULA_PREFIXES):
        return "'" + stripped
    return stripped


def clean_imported_text(value) -> str:
    """Strip dangerous formula prefixes from user-uploaded cells."""
    if value is None:
        return ""
    text = str(value).strip()
    # If cell starts with formula indicator, strip leading formula symbols
    while text and any(text.startswith(p) for p in DANGEROUS_FORMULA_PREFIXES):
        text = text[1:].strip()
    return text


def parse_excel_date(val) -> str:
    """Safely parse various date formats from Excel cells into YYYY-MM-DD string."""
    if isinstance(val, (datetime, date)):
        return val.strftime("%Y-%m-%d")
    if not val:
        raise ValueError("Date cannot be blank")

    text = str(val).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    raise ValueError(f"Invalid date format '{text}'. Expected YYYY-MM-DD")


def match_category(raw_cat: str) -> tuple[str, str]:
    """Match category string case-insensitively and return (canonical_category, transaction_type)."""
    clean = clean_imported_text(raw_cat).strip().lower()
    for cat in CATEGORIES["expense"]:
        if cat.lower() == clean:
            return cat, "expense"
    for cat in CATEGORIES["income"]:
        if cat.lower() == clean:
            return cat, "income"

    allowed = ", ".join(CATEGORIES["expense"] + CATEGORIES["income"])
    raise ValueError(f"Unknown category '{raw_cat}'. Allowed: {allowed}")


def export_expenses_to_excel(transactions: list[dict], title: str = "Expense Report", base_currency: str = "INR(₹)") -> io.BytesIO:
    """Export transactions list to an in-memory .xlsx file with professional styling."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Transactions"
    ws.views.sheetView[0].showGridLines = True

    # Palette
    navy_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
    alt_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    white_fill = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")
    total_fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")

    font_title = Font(name="Calibri", size=16, bold=True, color="0F172A")
    font_sub = Font(name="Calibri", size=10, italic=True, color="64748B")
    font_header = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    font_data = Font(name="Calibri", size=10, color="0F172A")
    font_income = Font(name="Calibri", size=10, bold=True, color="15803D")  # Green
    font_expense = Font(name="Calibri", size=10, bold=True, color="DC2626") # Red
    font_total = Font(name="Calibri", size=11, bold=True, color="0F172A")

    thin_border_side = Side(border_style="thin", color="CBD5E1")
    thin_border = Border(left=thin_border_side, right=thin_border_side, top=thin_border_side, bottom=thin_border_side)
    top_double_side = Side(border_style="double", color="94A3B8")
    bottom_double_side = Side(border_style="double", color="94A3B8")
    summary_border = Border(top=thin_border_side, bottom=bottom_double_side, left=thin_border_side, right=thin_border_side)

    align_center = Alignment(horizontal="center", vertical="center")
    align_left = Alignment(horizontal="left", vertical="center")
    align_right = Alignment(horizontal="right", vertical="center")

    # Title block
    ws.merge_cells("A1:F1")
    ws["A1"] = f"{title} - Expense Tracker"
    ws["A1"].font = font_title
    ws["A1"].alignment = align_left

    ws.merge_cells("A2:F2")
    ws["A2"] = f"Generated on {date.today().strftime('%B %d, %Y')} | Currency: {base_currency}"
    ws["A2"].font = font_sub
    ws["A2"].alignment = align_left

    ws.row_dimensions[1].height = 24
    ws.row_dimensions[2].height = 18
    ws.row_dimensions[4].height = 26

    # Headers at Row 4
    for col_idx, col_name in enumerate(EXPECTED_COLUMNS, start=1):
        cell = ws.cell(row=4, column=col_idx, value=col_name)
        cell.font = font_header
        cell.fill = navy_fill
        cell.alignment = align_center
        cell.border = thin_border

    # Data Rows
    row_num = 5
    total_income = Decimal("0.00")
    total_expense = Decimal("0.00")

    for idx, tx in enumerate(transactions):
        t_type = tx.get("type", "expense")
        amount_val = Decimal(str(tx.get("amount", 0)))
        if t_type == "income":
            total_income += amount_val
        else:
            total_expense += amount_val

        # Derive title and description from tx note/category
        note = tx.get("note", "")
        payment_method = tx.get("payment_method") or "Cash"
        title_text = tx.get("title") or note or tx.get("category", "")
        desc_text = tx.get("description") or (note if note != title_text else "")

        # Format values with formula protection
        date_str = str(tx.get("date", ""))
        safe_title = sanitize_text_for_excel(title_text)
        safe_cat = sanitize_text_for_excel(tx.get("category", ""))
        safe_pm = sanitize_text_for_excel(payment_method)
        safe_desc = sanitize_text_for_excel(desc_text)

        row_fill = alt_fill if idx % 2 == 1 else white_fill

        c_date = ws.cell(row=row_num, column=1, value=date_str)
        c_date.alignment = align_center

        c_title = ws.cell(row=row_num, column=2, value=safe_title)
        c_title.alignment = align_left

        c_cat = ws.cell(row=row_num, column=3, value=safe_cat)
        c_cat.alignment = align_left

        c_amt = ws.cell(row=row_num, column=4, value=float(amount_val))
        c_amt.number_format = "#,##0.00"
        c_amt.alignment = align_right
        c_amt.font = font_income if t_type == "income" else font_expense

        c_pm = ws.cell(row=row_num, column=5, value=safe_pm)
        c_pm.alignment = align_center

        c_desc = ws.cell(row=row_num, column=6, value=safe_desc)
        c_desc.alignment = align_left

        for col_idx in range(1, 7):
            cell = ws.cell(row=row_num, column=col_idx)
            if col_idx != 4:
                cell.font = font_data
            cell.fill = row_fill
            cell.border = thin_border

        ws.row_dimensions[row_num].height = 20
        row_num += 1

    # Blank separator
    row_num += 1

    # Summary Section
    net_balance = total_income - total_expense
    summary_items = [
        ("Total Income", float(total_income), font_income),
        ("Total Expenses", float(total_expense), font_expense),
        ("Net Balance", float(net_balance), font_total),
    ]

    for label, val, font_style in summary_items:
        ws.merge_cells(start_row=row_num, start_column=1, end_row=row_num, end_column=3)
        lbl_cell = ws.cell(row=row_num, column=1, value=label)
        lbl_cell.font = font_total
        lbl_cell.alignment = align_right
        lbl_cell.fill = total_fill

        val_cell = ws.cell(row=row_num, column=4, value=val)
        val_cell.font = font_style
        val_cell.alignment = align_right
        val_cell.number_format = "#,##0.00"
        val_cell.fill = total_fill

        ws.merge_cells(start_row=row_num, start_column=5, end_row=row_num, end_column=6)
        ws.cell(row=row_num, column=5).fill = total_fill

        for c in range(1, 7):
            ws.cell(row=row_num, column=c).border = summary_border

        ws.row_dimensions[row_num].height = 22
        row_num += 1

    # Adjust Column Widths
    min_widths = [14, 25, 18, 16, 18, 28]
    for col_idx, min_w in enumerate(min_widths, start=1):
        col_letter = get_column_letter(col_idx)
        max_len = max(
            len(str(ws.cell(row=r, column=col_idx).value or ""))
            for r in range(4, row_num)
        )
        ws.column_dimensions[col_letter].width = max(max_len + 3, min_w)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output


def generate_template_excel() -> io.BytesIO:
    """Generate a clean sample Excel template for users/guests to fill out."""
    sample_data = [
        {
            "date": date.today().strftime("%Y-%m-%d"),
            "title": "Monthly Salary",
            "category": "Salary",
            "amount": 75000.00,
            "type": "income",
            "payment_method": "Direct Deposit",
            "description": "Tech Consulting monthly payout",
        },
        {
            "date": date.today().strftime("%Y-%m-%d"),
            "title": "Apartment Rent",
            "category": "Rent",
            "amount": 22000.00,
            "type": "expense",
            "payment_method": "Bank Transfer",
            "description": "November rent payment",
        },
        {
            "date": date.today().strftime("%Y-%m-%d"),
            "title": "Weekly Groceries",
            "category": "Food",
            "amount": 3450.00,
            "type": "expense",
            "payment_method": "Credit Card",
            "description": "Organic supermarket groceries",
        },
    ]
    return export_expenses_to_excel(sample_data, title="Expense Tracker - Import Template")


def import_expenses_from_excel(file_stream, max_rows: int = 1000) -> dict:
    """Parse and validate an uploaded .xlsx file.

    Returns:
        {
            "valid_records": [...],
            "success_count": int,
            "rejected_count": int,
            "errors": [{"row": int, "error": str}]
        }
    """
    try:
        # data_only=True ensures openpyxl does NOT evaluate formulas
        wb = openpyxl.load_workbook(file_stream, data_only=True, read_only=False)
    except Exception as exc:
        raise ValidationError(f"Invalid or corrupted Excel file: {exc}")

    ws = wb.active
    if ws is None:
        raise ValidationError("Uploaded Excel workbook contains no active worksheets.")

    # Locate header row (check first 10 rows)
    header_row_idx = None
    col_map = {}

    for row_idx in range(1, min(15, ws.max_row + 1)):
        row_vals = [clean_imported_text(ws.cell(row=row_idx, column=c).value).lower() for c in range(1, ws.max_column + 1)]
        matched = {}
        for c_idx, val in enumerate(row_vals, start=1):
            for expected in EXPECTED_COLUMNS:
                if val == expected.lower() or expected.lower() in val:
                    matched[expected] = c_idx

        # If at least Date, Category, and Amount are found, treat as header row
        if "Date" in matched and "Category" in matched and "Amount" in matched:
            header_row_idx = row_idx
            col_map = matched
            break

    if header_row_idx is None:
        raise ValidationError(
            "Could not find valid column headers. Expected columns: Date, Title, Category, Amount, Payment Method, Description."
        )

    # Check for missing required columns
    required_cols = ["Date", "Category", "Amount"]
    missing = [c for c in required_cols if c not in col_map]
    if missing:
        raise ValidationError(f"Missing required columns in Excel sheet: {', '.join(missing)}")

    valid_records = []
    errors = []
    seen_hashes = set()

    for r_idx in range(header_row_idx + 1, min(header_row_idx + 1 + max_rows, ws.max_row + 1)):
        # Check if entire row is empty
        row_cells = [ws.cell(row=r_idx, column=c).value for c in range(1, ws.max_column + 1)]
        if not any(row_cells):
            continue

        row_errors = []

        # 1. Date
        date_raw = ws.cell(row=r_idx, column=col_map["Date"]).value
        try:
            parsed_date = parse_excel_date(date_raw)
        except Exception as e:
            row_errors.append(f"Date error: {e}")
            parsed_date = None

        # 2. Category & Type
        cat_raw = ws.cell(row=r_idx, column=col_map["Category"]).value
        canonical_cat = None
        tx_type = None
        if not cat_raw:
            row_errors.append("Category cannot be empty")
        else:
            try:
                canonical_cat, tx_type = match_category(str(cat_raw))
            except Exception as e:
                row_errors.append(str(e))

        # 3. Amount
        amt_raw = ws.cell(row=r_idx, column=col_map["Amount"]).value
        amount_cents = None
        if amt_raw is None:
            row_errors.append("Amount cannot be empty")
        else:
            try:
                # Clean amount string
                clean_amt = str(amt_raw).replace(",", "").replace("$", "").replace("₹", "").strip()
                amt_dec = Decimal(clean_amt).quantize(Decimal("0.01"))
                if amt_dec <= 0:
                    row_errors.append("Amount must be greater than 0")
                elif amt_dec > Decimal("10000000"):
                    row_errors.append("Amount exceeds maximum limit of 10,000,000")
                else:
                    amount_cents = int(amt_dec * 100)
            except (InvalidOperation, ValueError):
                row_errors.append(f"Invalid numeric amount '{amt_raw}'")

        # 4. Title (optional, fallback to note/category)
        title_raw = ws.cell(row=r_idx, column=col_map.get("Title", 0)).value if "Title" in col_map else ""
        clean_title = clean_imported_text(title_raw)[:100]

        # 5. Payment Method
        pm_raw = ws.cell(row=r_idx, column=col_map.get("Payment Method", 0)).value if "Payment Method" in col_map else ""
        clean_pm = clean_imported_text(pm_raw)[:50] or "Cash"

        # 6. Description
        desc_raw = ws.cell(row=r_idx, column=col_map.get("Description", 0)).value if "Description" in col_map else ""
        clean_desc = clean_imported_text(desc_raw)[:200]

        # Check for errors in this row
        if row_errors:
            errors.append({"row": r_idx, "error": "; ".join(row_errors)})
            continue

        # Build composite note if description is provided
        if clean_title and clean_desc:
            combined_note = f"{clean_title}: {clean_desc}"[:200]
        else:
            combined_note = (clean_title or clean_desc or "")[:200]

        # Deduplication check within file
        dedup_key = (parsed_date, canonical_cat, amount_cents, combined_note)
        if dedup_key in seen_hashes:
            # Skip exact duplicate row in same upload
            continue
        seen_hashes.add(dedup_key)

        valid_records.append({
            "type": tx_type,
            "amount_cents": amount_cents,
            "amount": amount_cents / 100,
            "category": canonical_cat,
            "note": combined_note,
            "title": clean_title,
            "payment_method": clean_pm,
            "description": clean_desc,
            "date": parsed_date,
        })

    return {
        "valid_records": valid_records,
        "success_count": len(valid_records),
        "rejected_count": len(errors),
        "errors": errors,
    }
