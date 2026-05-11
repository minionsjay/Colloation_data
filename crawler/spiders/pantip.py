"""Pantip (Thailand) forum spider.

Pantip is Thailand's largest discussion forum. Actual HTML structure (2026):
- Thread listing: a[href*="/topic/"] with div.pt-list-item__title
- Topic detail: h1.display-post-title + div.display-post-story
- Key rooms: sinthorn (social/political), rajdumnern (current affairs),
  supachalasai (general), bluplanet (lifestyle)
"""

from datetime import datetime, timezone
from typing import Iterator

from bs4 import BeautifulSoup

from crawler.base_spider import BaseSpider, RawPost
from crawler.middleware import PoliteClient, RetryHandler


class PantipSpider(BaseSpider):
    BASE = "https://pantip.com"

    ROOMS = [
        ("/forum/sinthorn", "social & political"),
        ("/forum/rajdumnern", "current affairs"),
        ("/forum/supachalasai", "general talk"),
    ]

    def __init__(self, limit: int = 50):
        super().__init__(source="pantip", country="TH", limit=limit)
        self.client = PoliteClient(default_delay=3.0)
        self.retry = RetryHandler()

    def scrape(self) -> Iterator[RawPost]:
        for room_path, _room_name in self.ROOMS:
            topic_urls = self._scrape_room(room_path)
            for url in topic_urls:
                post = self._scrape_topic(url)
                if post:
                    yield post

    def _scrape_room(self, room_path: str) -> list[str]:
        """Extract topic URLs from a room listing page."""
        url = f"{self.BASE}{room_path}"
        resp = self.client.get(url)
        soup = BeautifulSoup(resp.text, "lxml")

        links = []
        for a in soup.select('a[href*="/topic/"]'):
            href = a.get("href", "")
            if "/topic/" in href:
                full = f"{self.BASE}{href}" if href.startswith("/") else href
                if full not in links:
                    links.append(full)
            if len(links) >= self.limit:
                break
        return links

    def _scrape_topic(self, url: str) -> RawPost | None:
        """Scrape a single topic detail page."""
        def _fetch():
            return self.client.get(url)

        resp = self.retry.execute(_fetch)
        if resp is None:
            return None

        soup = BeautifulSoup(resp.text, "lxml")

        # Title: h1.display-post-title
        title_el = soup.select_one("h1.display-post-title")
        title = title_el.text.strip() if title_el else ""

        # Body: div.display-post-story
        body_el = soup.select_one("div.display-post-story")
        body = body_el.text.strip() if body_el else ""

        if not title and not body:
            return None

        # Author: try to extract from the page
        author = "anonymous"
        author_el = soup.select_one("a[href*='/profile/']")
        if author_el:
            author = author_el.text.strip()

        # Date: try to extract
        created = datetime.now(timezone.utc)
        time_el = soup.select_one("time[datetime], abbr[title]")
        if time_el:
            dt_str = time_el.get("datetime", "") or time_el.get("title", "")
            try:
                created = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
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
            metadata={"room": url.split("/forum/")[-1].split("/")[0] if "/forum/" in url else ""},
        )

    def close(self):
        self.client.close()
