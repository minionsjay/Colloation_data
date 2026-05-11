"""Kaskus (Indonesia) forum spider.

Indonesia's largest online forum. Modern single-page app style.
- Thread listing: API-driven, need to find JSON endpoints or CSS selectors
- Fall back to visible links on page

Note: Kaskus rate-limits aggressively. Use high delay between requests.
"""

from datetime import datetime, timezone
from typing import Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from crawler.base_spider import BaseSpider, RawPost
from crawler.middleware import PoliteClient, RetryHandler


class KaskusSpider(BaseSpider):
    BASE = "https://www.kaskus.co.id"

    FORUMS = [
        ("/forum/514/lounge", "lounge"),
        ("/forum/2/berita-politik", "news & politics"),
    ]

    def __init__(self, limit: int = 20):
        super().__init__(source="kaskus", country="ID", limit=limit)
        # Kaskus rate-limits heavily, use longer delay
        self.client = PoliteClient(default_delay=5.0)
        self.retry = RetryHandler(max_retries=2, base_delay=10.0)

    def scrape(self) -> Iterator[RawPost]:
        for forum_path, _name in self.FORUMS:
            url = urljoin(self.BASE, forum_path)
            thread_urls = self._scrape_forum(url)
            for t_url in thread_urls:
                post = self._scrape_thread(t_url)
                if post:
                    yield post

    def _scrape_forum(self, url: str) -> list[str]:
        resp = self.client.get(url)
        soup = BeautifulSoup(resp.text, "lxml")

        links = []
        # Kaskus thread links
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            txt = a.get_text(strip=True)
            if ("/thread/" in href or "/post/" in href) and len(txt) > 10:
                full = urljoin(self.BASE, href)
                if full not in links:
                    links.append(full)
            if len(links) >= self.limit:
                break
        return links

    def _scrape_thread(self, url: str) -> RawPost | None:
        def _fetch():
            return self.client.get(url)

        resp = self.retry.execute(_fetch)
        if resp is None:
            return None

        soup = BeautifulSoup(resp.text, "lxml")

        title_el = soup.select_one("h1, h2, [class*=title], [class*=thread-title]")
        title = title_el.text.strip() if title_el else ""

        body_el = soup.select_one(
            "div[class*=post-body], div[class*=message], div[class*=content], article"
        )
        body = body_el.text.strip() if body_el else ""

        if not title and not body:
            return None

        # Kaskus often shows "429 Too Many Requests" in body — filter those
        if "429" in title or "Too Many Requests" in body:
            return None

        return RawPost(
            source=self.source,
            country=self.country,
            url=url,
            title=title,
            body=f"{title}\n\n{body}" if title and body else (title or body),
            author_hash=RawPost.hash_author("anonymous"),
            created_at=datetime.now(timezone.utc),
        )

    def close(self):
        self.client.close()
