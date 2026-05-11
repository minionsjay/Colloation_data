"""Old Reddit scraper — no API credentials needed.

Parses old.reddit.com HTML which is consistent and simple.
Covers: Mexico, Saudi Arabia, Brazil, South Africa, and any other
country with a subreddit.
"""

from datetime import datetime, timezone
from typing import Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from config import COUNTRY_SUBREDDITS, COUNTRY_NAMES
from crawler.base_spider import BaseSpider, RawPost
from crawler.middleware import PoliteClient, RetryHandler


class OldRedditSpider(BaseSpider):
    """Scrapes old.reddit.com subreddits without API authentication."""

    BASE = "https://old.reddit.com"

    def __init__(self, country: str, limit: int = 25):
        super().__init__(source="reddit", country=country, limit=limit)
        self.subreddits = COUNTRY_SUBREDDITS.get(country, [])
        self.client = PoliteClient(default_delay=3.0, http2=False)
        self.retry = RetryHandler()

    def scrape(self) -> Iterator[RawPost]:
        seen_urls: set[str] = set()
        for sub in self.subreddits:
            url = f"{self.BASE}/r/{sub}/"
            thread_data = self._scrape_listing(url)
            for title, href, body_text in thread_data:
                if href in seen_urls:
                    continue
                seen_urls.add(href)
                post_url = urljoin(self.BASE, href)
                yield RawPost(
                    source=self.source,
                    country=self.country,
                    url=post_url,
                    title=title,
                    body=f"{title}\n\n{body_text}".strip(),
                    author_hash=RawPost.hash_author("anonymous"),
                    created_at=datetime.now(timezone.utc),
                    metadata={"subreddit": sub},
                )

    def _scrape_listing(self, url: str) -> list[tuple[str, str, str]]:
        """Return list of (title, href, body_text) from subreddit listing."""
        resp = self.client.get(url)
        soup = BeautifulSoup(resp.text, "lxml")

        results: list[tuple[str, str, str]] = []
        for post_div in soup.select("div.thing"):
            if len(results) >= self.limit:
                break

            # Title + link
            title_el = post_div.select_one("a.title")
            if not title_el:
                continue
            title = title_el.text.strip()
            href = title_el.get("href", "")
            if not href or not title:
                continue

            # Self-post body
            body_text = ""
            body_el = post_div.select_one("div.expando, div.usertext-body")
            if body_el:
                body_text = body_el.text.strip()

            # If not a self-post, try the link domain as context
            if not body_text:
                domain_el = post_div.select_one("span.domain a")
                if domain_el:
                    domain = domain_el.text.strip()
                    if domain not in ("self", "reddit.com", ""):
                        body_text = f"[link to {domain}]"

            results.append((title, href, body_text))

        return results

    def close(self):
        self.client.close()


def crawl_all_old_reddit(limit_per_country: int = 20) -> list[RawPost]:
    """Convenience: crawl old.reddit.com for all configured countries."""
    all_posts: list[RawPost] = []
    for code in COUNTRY_SUBREDDITS:
        name = COUNTRY_NAMES.get(code, code)
        print(f"Crawling: {name} ({code})")
        spider = OldRedditSpider(country=code, limit=limit_per_country)
        posts = list(spider.scrape())
        print(f"  → {len(posts)} posts")
        all_posts.extend(posts)
    return all_posts
