"""Polite HTTP: per-host spacing, bounded retries, gzip. A 4xx (other than 429) is final: if a site
refuses us we stop and report it, we never retry around a block."""
from __future__ import annotations

import gzip
import os
import random
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
BASE_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip",
    "Accept-Language": "en-US,en;q=0.9",
}
MIN_INTERVAL = 1.2  # seconds between two requests to the same host
RETRIES = int(os.environ.get("FOF_HTTP_RETRIES", "3"))
TIMEOUT = float(os.environ.get("FOF_HTTP_TIMEOUT", "30"))

_last_call: dict[str, float] = {}


class FetchError(RuntimeError):
    def __init__(self, url: str, status: int | None, body: bytes = b""):
        super().__init__(f"{status} for {url}: {body[:200]!r}")
        self.url, self.status, self.body = url, status, body


def fetch(url: str, headers: dict | None = None, timeout: float | None = None,
          retries: int | None = None) -> bytes:
    timeout = TIMEOUT if timeout is None else timeout
    retries = RETRIES if retries is None else retries
    host = urlparse(url).netloc
    h = {**BASE_HEADERS, **(headers or {})}
    err = FetchError(url, None, b"no attempt made")
    for attempt in range(retries + 1):
        wait = _last_call.get(host, 0.0) + MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call[host] = time.monotonic()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500 and e.code != 429:
                raise FetchError(url, e.code, e.read()) from None
            err = FetchError(url, e.code, e.read())
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            err = FetchError(url, None, str(e).encode())
        if attempt < retries:
            time.sleep(2 ** attempt * 2 + random.random())
    raise err
