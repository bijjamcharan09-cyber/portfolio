"""External API: live currency rates (frankfurter.app, no API key needed)."""
import time

import requests
from flask import current_app

_cache = {}  # {(from, to): (timestamp, rate)} so we don't call the API on every click
CACHE_SECONDS = 3600


class ExchangeError(Exception):
    pass


def get_rate(base, target):
    if base == target:
        return 1.0
    hit = _cache.get((base, target))
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    try:
        resp = requests.get(
            current_app.config["EXCHANGE_API_URL"],
            params={"from": base, "to": target},
            timeout=current_app.config["EXCHANGE_TIMEOUT"],
        )
        resp.raise_for_status()
        rate = float(resp.json()["rates"][target])
    except (requests.RequestException, KeyError, ValueError):
        raise ExchangeError("Exchange rate service is unavailable or the currency code is unknown")
    _cache[(base, target)] = (time.time(), rate)
    return rate
