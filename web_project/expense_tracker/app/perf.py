"""Lightweight request and database performance instrumentation.

Tracks per-request:
- Total request duration (ms)
- Database connection duration (ms)
- SQL execution duration (ms)
- Query count per request
- Slow queries exceeding SLOW_QUERY_THRESHOLD_MS (sanitized; never logs tokens or values)
"""
import logging
import re
import time

from flask import current_app, g, has_request_context, request

logger = logging.getLogger("expense_tracker.perf")

_WHITESPACE_RE = re.compile(r"\s+")


def sanitize_sql(sql: str) -> str:
    """Collapse whitespace and truncate SQL for safe diagnostic logging (no bound params)."""
    if not sql:
        return ""
    compact = _WHITESPACE_RE.sub(" ", sql).strip()
    return compact[:160] + ("..." if len(compact) > 160 else "")


def init_request_perf():
    """Initialize per-request performance counters on flask.g."""
    if not has_request_context():
        return
    g.perf_req_start = time.perf_counter()
    g.perf_db_connect_ms = 0.0
    g.perf_sql_ms = 0.0
    g.perf_query_count = 0
    g.perf_slow_queries = []


def record_db_connect(duration_ms: float):
    """Record database connection setup time for the current request."""
    if has_request_context():
        g.perf_db_connect_ms = getattr(g, "perf_db_connect_ms", 0.0) + duration_ms


def record_sql_execution(sql: str, duration_ms: float):
    """Record SQL execution timing and flag slow queries."""
    if not has_request_context():
        return
    g.perf_sql_ms = getattr(g, "perf_sql_ms", 0.0) + duration_ms
    g.perf_query_count = getattr(g, "perf_query_count", 0) + 1

    threshold = current_app.config.get("SLOW_QUERY_THRESHOLD_MS", 200)
    if duration_ms >= threshold:
        slow_list = getattr(g, "perf_slow_queries", None)
        if slow_list is not None:
            slow_list.append((sanitize_sql(sql), round(duration_ms, 2)))


def init_perf(app):
    """Register before_request / after_request performance hooks on the Flask app."""

    @app.before_request
    def _perf_before_request():
        init_request_perf()

    @app.after_request
    def _perf_after_request(response):
        start = getattr(g, "perf_req_start", None)
        if start is None:
            return response

        total_ms = (time.perf_counter() - start) * 1000.0
        db_conn_ms = getattr(g, "perf_db_connect_ms", 0.0)
        sql_ms = getattr(g, "perf_sql_ms", 0.0)
        query_count = getattr(g, "perf_query_count", 0)
        app_ms = max(0.0, total_ms - db_conn_ms - sql_ms)
        slow_queries = getattr(g, "perf_slow_queries", [])

        # Standard Server-Timing header (contains only numeric durations, zero sensitive data)
        response.headers["Server-Timing"] = (
            f"total;dur={total_ms:.1f}, "
            f"dbconn;dur={db_conn_ms:.1f}, "
            f"sql;dur={sql_ms:.1f}, "
            f"app;dur={app_ms:.1f}"
        )
        response.headers["X-DB-Query-Count"] = str(query_count)

        slow_req_threshold = app.config.get("SLOW_REQUEST_THRESHOLD_MS", 1000)
        if app.config.get("PERF_LOGGING_ENABLED", True) and (
            total_ms >= slow_req_threshold or slow_queries
        ):
            logger.info(
                "perf path=%s method=%s status=%s total_ms=%.1f db_conn_ms=%.1f sql_ms=%.1f app_ms=%.1f queries=%d slow_queries=%s",
                request.path,
                request.method,
                response.status_code,
                total_ms,
                db_conn_ms,
                sql_ms,
                app_ms,
                query_count,
                slow_queries[:5],
            )
        return response
