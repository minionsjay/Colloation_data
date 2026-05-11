"""Kompasiana (Indonesia) spider.

Indonesia's largest blogging platform (Kompas Gramedia group).
- Article listing: a[href*='/article/'] or direct links
- Article detail: div.read-content for body, JSON-LD for metadata
"""

import json
import re
from datetime import datetime, timezone
from typing import Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from crawler.base_spider import BaseSpider, RawPost
from crawler.middleware import PoliteClient, RetryHandler


class KompasianaSpider(BaseSpider):
    BASE = "https://www.kompasiana.com"

    CATEGORIES = [
        "/",  # homepage - mixed, always works
        "/topik/1",  # trending topics
    ]

    def __init__(self, limit: int = 30):
        super().__init__(source="kompasiana", country="ID", limit=limit)
        self.client = PoliteClient(default_delay=3.0)
        self.retry = RetryHandler()

    def _headers(self) -> dict:
        return {"Accept-Language": "id-ID,id;q=0.9,en;q=0.3", "Referer": self.BASE}

    def scrape(self) -> Iterator[RawPost]:
        seen_urls: set[str] = set()
        for cat in self.CATEGORIES:
            url = urljoin(self.BASE, cat)
            article_urls = self._scrape_listing(url)
            for a_url in article_urls:
                if a_url in seen_urls:
                    continue
                seen_urls.add(a_url)
                post = self._scrape_article(a_url)
                if post:
                    yield post

    def _scrape_listing(self, url: str) -> list[str]:
        resp = self.client.get(url, headers=self._headers())
        soup = BeautifulSoup(resp.text, "lxml")
        links = []
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            txt = a.get_text(strip=True)
            # Kompasiana article URLs: /username/slug
            if href.startswith("/") and href.count("/") >= 2 and len(txt) > 15:
                parts = href.strip("/").split("/")
                if len(parts) >= 2 and len(parts[1]) > 20:
                    full = urljoin(self.BASE, href)
                    if full not in links:
                        links.append(full)
            if len(links) >= self.limit:
                break
        return links

    def _scrape_article(self, url: str) -> RawPost | None:
        def _fetch():
            return self.client.get(url, headers=self._headers())

        resp = self.retry.execute(_fetch)
        if resp is None:
            return None

        soup = BeautifulSoup(resp.text, "lxml")

        # Try JSON-LD first for metadata
        title = ""
        author = "anonymous"
        created = datetime.now(timezone.utc)

        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.string)
                if isinstance(data, list):
                    data = data[0]
                if isinstance(data, dict) and data.get("@type") in (
                    "Article", "NewsArticle", "BlogPosting"
                ):
                    title = data.get("headline", "").replace(" - Kompasiana.com", "").replace(" Halaman 1", "")
                    if isinstance(data.get("author"), dict):
                        author = data["author"].get("name", author)
                    dt = data.get("datePublished", "")
                    if dt:
                        try:
                            created = datetime.fromisoformat(dt.replace("Z", "+00:00"))
                        except (ValueError, TypeError):
                            pass
                    break
            except (json.JSONDecodeError, KeyError, TypeError):
                continue

        # Fallback: extract from dataLayer
        if not title:
            for script in soup.select("script"):
                if script.string and "window.dataLayer" in script.string:
                    m = re.search(r'"title":\s*"([^"]+)"', script.string)
                    if m:
                        title = m.group(1)
                    m = re.search(r'"content_author":\s*"([^"]+)"', script.string)
                    if m:
                        author = m.group(1)
                    break

        # Body
        body_el = soup.select_one("div.read-content, div[class*=read__content], div.row.clearfix")
        body = body_el.get_text(separator="\n").strip() if body_el else ""

        if not title and not body:
            return None

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
