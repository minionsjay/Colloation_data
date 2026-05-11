"""Anti-blocking middleware for non-Reddit web crawlers.

Reddit goes through PRAW (API), which handles rate limits natively.
This module is for forum spiders that use raw HTTP requests.
"""

import random
import time
from collections import defaultdict
from typing import Callable

import httpx

# Large pool of real browser User-Agent strings
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (X11; Linux i686; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
]


class PoliteClient:
    """httpx wrapper with automatic rate limiting and UA rotation.

    Per-domain rate tracking ensures we never hit the same domain
    faster than the configured delay.

    Supports proxy configuration via the PROXY_URL environment variable
    or by passing proxy_url directly. Example proxies:
      - HTTP:  http://user:pass@proxy.example.com:8080
      - SOCKS: socks5://127.0.0.1:1080
    """

    def __init__(self, default_delay: float = 2.0, proxy_url: str = "",
                 http2: bool = True, extra_headers: dict | None = None):
        self.default_delay = default_delay
        self._last_request: dict[str, float] = defaultdict(float)

        headers = {"Accept-Language": "en-US,en;q=0.9"}
        if extra_headers:
            headers.update(extra_headers)

        client_kwargs: dict = {
            "timeout": 30,
            "follow_redirects": True,
            "headers": headers,
        }

        # Proxy support: explicit arg takes priority, then env var
        proxy = proxy_url or ""
        if not proxy:
            import os
            proxy = (os.getenv("PROXY_URL", "")
                     or os.getenv("HTTPS_PROXY", "") or os.getenv("https_proxy", "")
                     or os.getenv("HTTP_PROXY", "") or os.getenv("http_proxy", ""))
        if proxy:
            client_kwargs["proxy"] = proxy

        if http2:
            try:
                self._client = httpx.Client(http2=True, **client_kwargs)
            except ImportError:
                self._client = httpx.Client(**client_kwargs)
        else:
            self._client = httpx.Client(**client_kwargs)

    def _wait(self, domain: str, delay: float | None = None):
        wait = delay or self.default_delay
        elapsed = time.monotonic() - self._last_request[domain]
        if elapsed < wait:
            time.sleep(wait - elapsed + random.uniform(0, 0.5))

    def _random_ua(self) -> str:
        return random.choice(USER_AGENTS)

    def get(self, url: str, *, delay: float | None = None, max_retries: int = 2, **kwargs) -> httpx.Response:
        from urllib.parse import urlparse

        domain = urlparse(url).netloc
        headers = kwargs.pop("headers", {})
        headers.setdefault("User-Agent", self._random_ua())

        last_err = None
        for attempt in range(max_retries + 1):
            try:
                self._wait(domain, delay)
                resp = self._client.get(url, headers=headers, **kwargs)
                self._last_request[domain] = time.monotonic()
                resp.raise_for_status()
                return resp
            except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError) as e:
                last_err = e
                if attempt < max_retries:
                    time.sleep(3 + attempt * 2)
                    continue
                raise
        raise last_err  # type: ignore[misc]

    def close(self):
        self._client.close()


class RetryHandler:
    """Exponential backoff retry for transient HTTP errors."""

    def __init__(self, max_retries: int = 3, base_delay: float = 5.0):
        self.max_retries = max_retries
        self.base_delay = base_delay

    def execute(self, fn: Callable[[], httpx.Response]) -> httpx.Response | None:
        for attempt in range(self.max_retries):
            try:
                return fn()
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (429, 503, 403):
                    if attempt < self.max_retries - 1:
                        wait = self.base_delay * (2**attempt)
                        time.sleep(wait)
                        continue
                    return None  # exhausted retries, give up gracefully
                raise
            except (httpx.ConnectError, httpx.TimeoutException):
                if attempt < self.max_retries - 1:
                    time.sleep(self.base_delay * (2**attempt))
                    continue
                raise
        return None
