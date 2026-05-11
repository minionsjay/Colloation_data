"""Ekşi Sözlük (Turkey) spider.

Turkish collaborative dictionary / discussion platform.
- Topic listing: links with '--' in href
- Topic detail: h1#title + div.content entries

Cloudflare bypass: use HTTP/1.1 (NOT http2), set Turkish Accept-Language,
and visit listing pages first to get cookies before detail pages.
"""

import random
from datetime import datetime, timezone
from typing import Iterator
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from crawler.base_spider import BaseSpider, RawPost


class EksiSozlukSpider(BaseSpider):
    BASE = "https://eksisozluk.com"

    PAGES = [
        "/basliklar/gundem",
        "/basliklar/populer",
    ]

    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    ]

    def __init__(self, limit: int = 30, entries_per_topic: int = 5):
        super().__init__(source="eksisozluk", country="TR", limit=limit)
        self.entries_per_topic = entries_per_topic
        self._client = httpx.Client(
            timeout=30,
            follow_redirects=True,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
            },
        )

    def _ua(self) -> str:
        return random.choice(self.USER_AGENTS)

    def scrape(self) -> Iterator[RawPost]:
        # Visit listing pages first to acquire Cloudflare cookies
        for page in self.PAGES:
            self._client.get(
                urljoin(self.BASE, page),
                headers={"User-Agent": self._ua()},
            )

        for page in self.PAGES:
            url = urljoin(self.BASE, page)
            topic_urls = self._scrape_listing(url)
            for t_url in topic_urls:
                yield from self._scrape_topic(t_url)

    def _scrape_listing(self, url: str) -> list[str]:
        resp = self._client.get(url, headers={"User-Agent": self._ua()})
        soup = BeautifulSoup(resp.text, "lxml")

        links = []
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            txt = a.get_text(strip=True)
            if "--" in href and len(txt) > 10:
                full = urljoin(self.BASE, href)
                if full not in links:
                    links.append(full)
            if len(links) >= self.limit:
                break
        return links

    def _scrape_topic(self, url: str) -> list[RawPost]:
        resp = self._client.get(url, headers={"User-Agent": self._ua()})
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "lxml")

        title_el = soup.select_one("h1#title, h1[class*=title]")
        topic_title = title_el.text.strip() if title_el else ""

        posts = []
        for entry_el in soup.select("div.content")[: self.entries_per_topic]:
            text = entry_el.text.strip()
            if len(text) < 10:
                continue
            posts.append(
                RawPost(
                    source=self.source,
                    country=self.country,
                    url=url,
                    title=topic_title,
                    body=f"{topic_title}\n\n{text}",
                    author_hash=RawPost.hash_author("anonymous"),
                    created_at=datetime.now(timezone.utc),
                )
            )
        return posts

    def close(self):
        self._client.close()
