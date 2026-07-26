"""Shared cached, paced FatSecret client for the scraper modules."""

import base64
import fcntl
import hashlib
import hmac
import json
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from email.utils import parsedate_to_datetime
from pathlib import Path

API_URL = "https://platform.fatsecret.com/rest/server.api"
CACHE_DIR = Path("/home/ubuntu/.fscache")
LOCK_PATH = CACHE_DIR / ".request.lock"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36"
MIN_INTERVAL = 1.05
_last_request = 0.0
_clock_offset = 0.0


def _cache_path(params):
    canonical = urllib.parse.urlencode(
        sorted((str(key), str(value)) for key, value in params.items())
    )
    return CACHE_DIR / f"{hashlib.sha256(canonical.encode()).hexdigest()}.json"


def _read(path):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _update_clock(headers):
    global _clock_offset
    date = headers.get("Date")
    if not date:
        return
    try:
        _clock_offset = parsedate_to_datetime(date).timestamp() - time.time()
    except (TypeError, ValueError, OverflowError):
        pass


def _request(params):
    global _last_request
    delay = MIN_INTERVAL - (time.monotonic() - _last_request)
    if delay > 0:
        time.sleep(delay)
    secret = os.environ.get("FATSECRET_CONSUMER_SECRET") or os.environ["FAT_SECRET_CONSUMER_SECRET"]
    signed = {
        "oauth_consumer_key": os.environ["FATSECRET_CONSUMER_KEY"],
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time() + _clock_offset)),
        "oauth_nonce": str(random.getrandbits(64)),
        "oauth_version": "1.0",
        "format": "json",
        **params,
    }
    normalized = "&".join(
        f"{key}={urllib.parse.quote(str(signed[key]), '')}"
        for key in sorted(signed)
    )
    base = "&".join((
        "GET",
        urllib.parse.quote(API_URL, ""),
        urllib.parse.quote(normalized, ""),
    ))
    signed["oauth_signature"] = base64.b64encode(
        hmac.new((secret + "&").encode(), base.encode(), hashlib.sha1).digest()
    ).decode()
    request = urllib.request.Request(
        f"{API_URL}?{urllib.parse.urlencode(signed)}",
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        _update_clock(response.headers)
        result = json.load(response)
    _last_request = time.monotonic()
    return result


def fatsecret(params):
    """Fetch a successful response, caching and retrying transient failures."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(params)
    cached = _read(path)
    if cached is not None and not cached.get("error"):
        return cached
    with LOCK_PATH.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        cached = _read(path)
        if cached is not None and not cached.get("error"):
            return cached
        last_error = None
        for attempt in range(7):
            try:
                result = _request(params)
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
                result = None
                last_error = error
            if result is not None and not result.get("error"):
                path.write_text(json.dumps(result, separators=(",", ":")))
                return result
            error = (result or {}).get("error", {})
            last_error = error or last_error
            code = int(error.get("code", 0) or 0)
            if result is not None and code not in (6, 12):
                raise RuntimeError(f"FatSecret API error for {params}: {result}")
            if attempt < 6:
                time.sleep(min(120, 2 ** attempt))
        raise RuntimeError(f"FatSecret request failed after retries: {last_error}")
