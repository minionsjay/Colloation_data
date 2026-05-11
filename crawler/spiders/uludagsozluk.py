"""Uludağ Sözlük (Turkey) spider.

Turkish collaborative dictionary / discussion platform.
- Topic listing: a[href*='/k/'] with entry count
- Topic detail: entries in div.entry-content, div.entry-text
"""

from datetime import datetime, timezone
from typing import Iterator
from urllib.parse import urljoin, unquote

from bs4 import BeautifulSoup

from crawler.base_spider import BaseSpider, RawPost
from crawler.middleware import PoliteClient, RetryHandler


class UludagSozlukSpider(BaseSpider):
    BASE = "https://www.uludagsozluk.com"

    START_PAGES = [
        "/",
        "/gundem",
    ]

    def __init__(self, limit: int = 20, entries_per_topic: int = 3):
        super().__init__(source="uludagsozluk", country="TR", limit=limit)
        self.entries_per_topic = entries_per_topic
        self.client = PoliteClient(default_delay=3.0, http2=False)
        self.retry = RetryHandler()

    def scrape(self) -> Iterator[RawPost]:
        seen_urls: set[str] = set()
        for page in self.START_PAGES:
            url = urljoin(self.BASE, page) if page != "/" else self.BASE
            topic_urls = self._scrape_listing(url)
            for t_url in topic_urls:
                if t_url in seen_urls:
                    continue
                seen_urls.add(t_url)
                entries = self._scrape_topic(t_url)
                yield from entries

    def _scrape_listing(self, url: str) -> list[str]:
        resp = self.client.get(url)
        soup = BeautifulSoup(resp.text, "lxml")

        links: list[str] = []
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            txt = a.get_text(strip=True)
            # Topic links: /k/slug-with-dashes/
            if href.startswith("/k/") and len(txt) > 10:
                full = urljoin(self.BASE, href)
                if full not in links:
                    links.append(full)
            if len(links) >= self.limit:
                break
        return links

    def _scrape_topic(self, url: str) -> list[RawPost]:
        def _fetch():
            return self.client.get(url)

        resp = self.retry.execute(_fetch)
        if resp is None:
            return []

        soup = BeautifulSoup(resp.text, "lxml")

        # Topic title from URL or h1
        topic_title = ""
        url_path = url.replace(self.BASE, "").rstrip("/")
        if "/k/" in url_path:
            slug = url_path.split("/k/")[-1].rstrip("/")
            topic_title = unquote(slug).replace("-", " ").title()

        h1 = soup.select_one("h1, h2[class*=title]")
        if h1 and len(h1.get_text(strip=True)) > 3:
            topic_title = h1.get_text(strip=True)

        # Find entry texts — look for div.entry-content-like structures
        # Uludag Sozluk entries are inside specific entry divs
        entries: list[RawPost] = []
        seen_keys: set[str] = set()

        # Target only entry-related divs, not the entire page
        entry_divs = soup.select(
            "div.entry-content, div[class*=entry-text], div.entry-body, "
            "div.col-entry-main-ulu, div[id*=entry]"
        )
        if not entry_divs:
            # Fallback: look for text-only divs inside the main content area
            entry_divs = soup.select("div[class*=entry] div, div[id*=entry] div")

        for el in entry_divs:
            if len(entries) >= self.entries_per_topic:
                break
            txt = el.get_text(strip=True)
            if 50 < len(txt) < 3000 and not any(
                skip in txt.lower()[:50]
                for skip in ["detaylı ara", "vazgeç", "başlıklar", "üyeler",
                             "giriş yap", "kayıt ol", "paylaş"]
            ):
                key = txt[:80]
                if key not in seen_keys and not txt.startswith(topic_title[:30]):
                    seen_keys.add(key)
                    entries.append(
                        RawPost(
                            source=self.source,
                            country=self.country,
                            url=url,
                            title=topic_title,
                            body=f"{topic_title}\n\n{txt}",
                            author_hash=RawPost.hash_author("anonymous"),
                            created_at=datetime.now(timezone.utc),
                        )
                    )
        return entries

    def close(self):
        self.client.close()
