# Expense Tracker

Track income and expenses, then see daily / monthly / yearly / last-N-days summaries as matplotlib charts.
Stack: Flask, SQLite 3, vanilla HTML/CSS/JS, pytest. Live currency rates come from frankfurter.app.

## Run it
```bash
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                  # then set SECRET_KEY
python run.py                                         # open http://127.0.0.1:5000
pytest                                                # run the tests
```

## Project map
| File | Job |
|---|---|
| `app/__init__.py` | Builds the app, error handling, security headers |
| `app/config.py` | Reads settings from `.env` |
| `app/db.py` | SQLite schema and queries (money stored as cents) |
| `app/validators.py` | Checks everything the browser sends |
| `app/api.py` | REST endpoints |
| `app/services/reports.py` | Date ranges, totals, matplotlib chart |
| `app/services/exchange.py` | External currency-rate API (cached 1 hour) |
| `app/templates`, `app/static` | The web page |
| `tests/` | pytest tests (use a temporary database) |

## API
| Method | Path | Notes |
|---|---|---|
| GET | `/api/transactions` | list for a period |
| POST | `/api/transactions` | JSON: `type, amount, category, date, note` |
| DELETE | `/api/transactions/<id>` | |
| GET | `/api/reports/summary` | totals, per-category, time series |
| GET | `/api/reports/chart.png` | matplotlib image |
| GET | `/api/convert?to=EUR` | period balance in another currency |
| GET | `/api/categories` | allowed categories |

Period parameters for the list, summary, chart and convert endpoints:
`period=day|month|year|days`, `date=YYYY-MM-DD` (default today), `days=N` (for `period=days`).

## Security notes
Parameterized SQL, server-side validation, `textContent` instead of `innerHTML`, a strict Content-Security-Policy,
request size limit, secrets in `.env`. There is no login yet, so run it locally or add authentication before hosting it.
