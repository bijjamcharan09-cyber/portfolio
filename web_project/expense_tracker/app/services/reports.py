"""Date ranges, totals, and the matplotlib chart."""
import calendar
import io
from datetime import date, timedelta

from matplotlib.figure import Figure

from ..db import get_db

INCOME_COLOR = "#1f7a5c"
EXPENSE_COLOR = "#c0432f"


def date_range(period, anchor, days=30):
    """Return (start, end) for 'day', 'month', 'year' or 'days' (last N days)."""
    if period == "day":
        return anchor, anchor
    if period == "month":
        last = calendar.monthrange(anchor.year, anchor.month)[1]
        return anchor.replace(day=1), anchor.replace(day=last)
    if period == "year":
        return date(anchor.year, 1, 1), date(anchor.year, 12, 31)
    if period == "days":
        return anchor - timedelta(days=days - 1), anchor
    raise ValueError("period must be day, month, year or days")


def _labels(start, end, monthly):
    if not monthly:
        return [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]
    labels, cur = [], start.replace(day=1)
    while cur <= end:
        labels.append(cur.strftime("%Y-%m"))
        cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
    return labels


def summarize(start, end):
    conn = get_db()
    s, e = start.isoformat(), end.isoformat()

    totals = {"income": 0, "expense": 0}
    for r in conn.execute(
        "SELECT type, SUM(amount_cents) AS t FROM transactions WHERE date BETWEEN ? AND ? GROUP BY type", (s, e)
    ):
        totals[r["type"]] = r["t"]

    cats = conn.execute(
        "SELECT category, SUM(amount_cents) AS t FROM transactions "
        "WHERE type = 'expense' AND date BETWEEN ? AND ? GROUP BY category ORDER BY t DESC",
        (s, e),
    ).fetchall()

    monthly = (end - start).days > 92  # long ranges are grouped by month
    bucket = "substr(date, 1, 7)" if monthly else "date"  # constant strings, not user input
    rows = conn.execute(
        f"SELECT {bucket} AS label, type, SUM(amount_cents) AS t FROM transactions "
        "WHERE date BETWEEN ? AND ? GROUP BY label, type",
        (s, e),
    ).fetchall()
    series = {l: {"label": l, "income": 0, "expense": 0} for l in _labels(start, end, monthly)}
    for r in rows:
        series[r["label"]][r["type"]] = r["t"] / 100

    return {
        "start": s,
        "end": e,
        "income": totals["income"] / 100,
        "expense": totals["expense"] / 100,
        "balance": (totals["income"] - totals["expense"]) / 100,
        "by_category": [{"category": r["category"], "total": r["t"] / 100} for r in cats],
        "series": list(series.values()),
    }


def render_chart(summary):
    """Bar chart (income vs expense over time) + pie chart (expenses by category) as PNG bytes."""
    fig = Figure(figsize=(11, 4.2))  # Figure (not pyplot) is safe to use inside a web server
    bars, pie = fig.subplots(1, 2, gridspec_kw={"width_ratios": [3, 2]})

    labels = [p["label"] for p in summary["series"]]
    x = list(range(len(labels)))
    width = 0.4
    bars.bar([i - width / 2 for i in x], [p["income"] for p in summary["series"]], width, color=INCOME_COLOR, label="Income")
    bars.bar([i + width / 2 for i in x], [p["expense"] for p in summary["series"]], width, color=EXPENSE_COLOR, label="Expense")
    step = max(1, len(labels) // 8)
    bars.set_xticks(x[::step])
    bars.set_xticklabels([l[5:] if len(l) == 10 else l for l in labels][::step], rotation=45, ha="right")
    bars.set_title("Income vs expense")
    bars.legend()
    bars.spines[["top", "right"]].set_visible(False)

    cats = summary["by_category"]
    if cats:
        pie.pie([c["total"] for c in cats], labels=[c["category"] for c in cats], autopct="%1.0f%%", startangle=90)
        pie.set_title("Where the money went")
    else:
        pie.text(0.5, 0.5, "No expenses in this period", ha="center", va="center")
        pie.axis("off")

    fig.suptitle(f"{summary['start']} to {summary['end']}", fontsize=12)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110)
    return buf.getvalue()
