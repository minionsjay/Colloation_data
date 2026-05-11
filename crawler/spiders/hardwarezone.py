"""HardwareZone (Singapore) forum spider.

XenForo-based forum. Key selectors:
- Thread listing: div.structItem-title a[data-tp-primary]
- Thread detail: h1.p-title-value + div.bbWrapper
"""

from datetime import datetime, timezone
from typing import Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from crawler.base_spider import BaseSpider, RawPost
from crawler.middleware import PoliteClient, RetryHandler


class HardwareZoneSpider(BaseSpider):
    BASE = "https://forums.hardwarezone.com.sg"

    FORUMS = [
        ("/forums/eat-drink-man-woman.16/", "general"),
        ("/forums/current-affairs-lounge.17/", "current affairs"),
    ]

    def __init__(self, limit: int = 30):
        super().__init__(source="hardwarezone", country="SG", limit=limit)
        self.client = PoliteClient(
            default_delay=3.0, http2=False,
            extra_headers={"Accept-Language": "en-SG,en;q=0.9,zh;q=0.5"},
        )
        self.retry = RetryHandler()

    def scrape(self) -> Iterator[RawPost]:
        # Warm up: visit homepage first to get security cookies
        self.client.get(self.BASE)

        seen_urls: set[str] = set()
        for forum_path, _name in self.FORUMS:
            url = urljoin(self.BASE, forum_path)
            thread_urls = self._scrape_forum(url)
            for t_url in thread_urls:
                if t_url in seen_urls:
                    continue
                seen_urls.add(t_url)
                post = self._scrape_thread(t_url)
                if post:
                    yield post

    def _scrape_forum(self, url: str) -> list[str]:
        resp = self.client.get(url)
        soup = BeautifulSoup(resp.text, "lxml")

        links = []
        for a in soup.select("div.structItem-title a[data-tp-primary]"):
            href = a.get("href", "")
            if "/threads/" in href and "/sticky" not in href:
                full = urljoin(self.BASE, href)
                if full not in links:
                    links.append(full)
            if len(links) >= self.limit:
                break
        return links

    def _scrape_thread(self, url: str) -> RawPost | None:
        def _fetch():
            return self.client.get(url, headers={
                "Referer": "https://forums.hardwarezone.com.sg/",
            })

        resp = self.retry.execute(_fetch)
        if resp is None:
            return None
        if resp.status_code == 403:
            return None  # Cloudflare block on this thread, skip

        soup = BeautifulSoup(resp.text, "lxml")

        title_el = soup.select_one("h1.p-title-value")
        title = title_el.text.strip() if title_el else ""

        body_el = soup.select_one("div.bbWrapper")
        body = body_el.text.strip() if body_el else ""

        if not title and not body:
            return None

        author = "anonymous"
        author_el = soup.select_one("a.username")
        if author_el:
            author = author_el.text.strip()

        created = datetime.now(timezone.utc)
        time_el = soup.select_one("time[datetime]")
        if time_el:
            dt_str = time_el.get("datetime", "")
            try:
                created = datetime.fromisoformat(dt_str)
            except (ValueError, TypeError):
                pass

        return RawPost(
            source=self.source,
            country=self.country,
            url=url,
            title=title,
            body=f"{title}\n\n{body}",
            author_hash=RawPost.hash_author(author),
            created_at=created,
        )

    def close(self):
        self.client.close()
