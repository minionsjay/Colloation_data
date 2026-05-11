"""Reddit spider with comment scraping.

Scrapes both post content AND all top-level comments from old.reddit.com.
No API credentials needed.
"""

import time
from datetime import datetime, timezone
from typing import Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from crawler.base_spider import BaseSpider, RawPost
from crawler.middleware import PoliteClient, RetryHandler


class RedditCommentsSpider(BaseSpider):
    """Scrapes posts + comments from old.reddit.com without authentication."""

    BASE = "https://old.reddit.com"

    def __init__(self, subreddits: list[str], limit: int = 25,
                 max_comments: int = 30, sort: str = "hot",
                 pages: int = 1, top_time: str = "all"):
        super().__init__(source="reddit", country="TH", limit=limit)
        self.subreddits = subreddits
        self.max_comments = max_comments
        self.sort = sort
        self.pages = pages
        self.top_time = top_time
        self.client = PoliteClient(default_delay=3.0, http2=False)
        self.retry = RetryHandler()

    def scrape(self) -> Iterator[RawPost]:
        seen_permalinks: set[str] = set()
        for sub in self.subreddits:
            if self.sort == "top":
                url = f"{self.BASE}/r/{sub}/top/?sort=top&t={self.top_time}"
            else:
                url = f"{self.BASE}/r/{sub}/{self.sort}/"

            for page in range(self.pages):
                thread_data, next_url = self._scrape_listing(url)
                for title, permalink, body_text in thread_data:
                    if permalink in seen_permalinks:
                        continue
                    seen_permalinks.add(permalink)

                    post_url = urljoin(self.BASE, permalink)
                    comments = self._scrape_comments(post_url)
                    comment_text = "\n---\n".join(comments) if comments else ""

                    full_body = f"[POST]\n{title}\n\n{body_text}"
                    if comment_text:
                        full_body += f"\n\n[COMMENTS]\n{comment_text}"

                    yield RawPost(
                        source=self.source, country=self.country,
                        url=post_url, title=title,
                        body=full_body.strip(),
                        author_hash=RawPost.hash_author("anonymous"),
                        created_at=datetime.now(timezone.utc),
                        metadata={
                            "subreddit": sub,
                            "sort": self.sort,
                            "comment_count": len(comments),
                            "page": page + 1,
                        },
                    )

                if not next_url:
                    break
                url = next_url
                time.sleep(2)

    def _scrape_listing(self, url: str) -> tuple[list[tuple[str, str, str]], str | None]:
        """Parse one listing page. Returns (results, next_url|None).

        Uses data-permalink for thread URL, NOT a.title href (which may
        point to external links like v.redd.it for link posts).
        """
        resp = self.client.get(url)
        soup = BeautifulSoup(resp.text, "lxml")

        results: list[tuple[str, str, str]] = []
        for post_div in soup.select("div.thing"):
            if len(results) >= self.limit:
                break

            # Skip stickies and ads
            if "stickied" in post_div.get("class", []):
                continue
            if post_div.select_one(".sponsored-tagline, .promoted"):
                continue

            title_el = post_div.select_one("a.title")
            if not title_el:
                continue
            title = title_el.text.strip()
            if not title:
                continue

            # Use data-permalink for the Reddit thread URL (always correct)
            permalink = post_div.get("data-permalink", "")
            if not permalink:
                comments_a = post_div.select_one("a.comments, a.bylink")
                permalink = comments_a.get("href", "") if comments_a else ""
            if not permalink:
                permalink = title_el.get("href", "")
            if not permalink:
                continue

            body_text = ""
            body_el = post_div.select_one("div.expando, div.usertext-body")
            if body_el:
                body_text = body_el.text.strip()

            results.append((title, permalink, body_text))

        # Find next page URL
        next_url = None
        next_a = soup.select_one("span.next-button a, a[rel='nofollow next']")
        if next_a:
            next_href = next_a.get("href", "")
            if next_href:
                next_url = urljoin(self.BASE, next_href)

        return results, next_url

    def _scrape_comments(self, post_url: str) -> list[str]:
        """Extract top-level comments from a Reddit thread page."""
        try:
            resp = self.client.get(post_url)
        except Exception:
            return []

        soup = BeautifulSoup(resp.text, "lxml")

        comments = []
        for comment_div in soup.select("div.comment"):
            if len(comments) >= self.max_comments:
                break

            # 跳过嵌套评论（只取顶层）
            parent = comment_div.find_parent("div.comment")
            if parent:
                continue

            # 跳过已删除的
            if comment_div.select_one("div.deleted, div.removed"):
                continue

            body_el = comment_div.select_one("div.md")
            if not body_el:
                continue

            text = body_el.text.strip()
            if len(text) < 10:  # 过滤太短的
                continue

            comments.append(text)

        return comments

    def close(self):
        self.client.close()
