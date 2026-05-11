"""Reddit spider that yields each comment as a separate RawPost.

Post title+body = one record. Each comment = separate record.
All linked by parent_id for traceability.

Supports pagination: crawl multiple listing pages via old.reddit.com's
?count=N&after=t3_xxx mechanism.
"""

import random
import time
import uuid
from datetime import datetime, timezone
from typing import Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from crawler.base_spider import BaseSpider, RawPost
from crawler.middleware import PoliteClient, RetryHandler


class RedditSplitSpider(BaseSpider):
    """Scrapes posts + individual comments from old.reddit.com with pagination."""

    BASE = "https://old.reddit.com"

    def __init__(self, subreddits: list[str], limit: int = 25,
                 max_comments: int = 30, sort: str = "hot",
                 pages: int = 1, top_time: str = "all"):
        """
        Args:
            subreddits: list of subreddit names
            limit: max posts per PAGE (not total)
            max_comments: max comments per post
            sort: hot, new, top, controversial
            pages: how many listing pages to crawl per subreddit
            top_time: for sort=top, one of hour, day, week, month, year, all
        """
        super().__init__(source="reddit", country="TH", limit=limit)
        self.subreddits = subreddits
        self.max_comments = max_comments
        self.sort = sort
        self.pages = pages
        self.top_time = top_time
        self.client = PoliteClient(default_delay=5.0, http2=False)

    def scrape(self) -> Iterator[RawPost]:
        for sub in self.subreddits:
            yield from self._scrape_subreddit(sub)

    def _scrape_subreddit(self, sub: str) -> Iterator[RawPost]:
        """Crawl a subreddit across multiple pages with 429 cooldown."""
        seen_permalinks: set[str] = set()

        if self.sort == "top":
            url = f"{self.BASE}/r/{sub}/top/?sort=top&t={self.top_time}"
        else:
            url = f"{self.BASE}/r/{sub}/{self.sort}/"

        consecutive_429 = 0

        for page in range(self.pages):
            thread_data, next_url = self._scrape_listing(url)

            for title, permalink, body_text in thread_data:
                if permalink in seen_permalinks:
                    continue
                seen_permalinks.add(permalink)
                post_url = urljoin(self.BASE, permalink)
                post_id = str(uuid.uuid4())[:12]

                # Post row
                yield RawPost(
                    source=self.source, country=self.country,
                    url=post_url, title=title,
                    body=f"[POST] {title}\n\n{body_text}".strip(),
                    author_hash=RawPost.hash_author("anonymous"),
                    created_at=datetime.now(timezone.utc),
                    metadata={
                        "type": "post",
                        "parent_id": post_id,
                        "subreddit": sub,
                        "sort": self.sort,
                        "page": page + 1,
                    },
                )

                # Comments
                comments, was_429 = self._scrape_comments_with_cooldown(post_url)
                if was_429:
                    consecutive_429 += 1
                    if consecutive_429 >= 3:
                        break  # too many 429s, move to next sub
                else:
                    consecutive_429 = 0

                for i, comment_text in enumerate(comments):
                    yield RawPost(
                        source=self.source, country=self.country,
                        url=post_url,
                        title=f"RE: {title}",
                        body=f"[COMMENT #{i+1}]\n{comment_text}".strip(),
                        author_hash=RawPost.hash_author("anonymous"),
                        created_at=datetime.now(timezone.utc),
                        metadata={
                            "type": "comment",
                            "parent_id": post_id,
                            "comment_index": i + 1,
                            "subreddit": sub,
                            "sort": self.sort,
                            "page": page + 1,
                        },
                    )

            if consecutive_429 >= 3:
                break
            if not next_url:
                break
            url = next_url
            time.sleep(random.uniform(3, 5))  # inter-page delay

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

            # Skip stickied posts and ads
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

            # Use data-permalink (always points to Reddit thread)
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

    def _scrape_comments_with_cooldown(self, post_url: str) -> tuple[list[str], bool]:
        """Returns (comments, was_429). Cooldown 60s on 429."""
        try:
            resp = self.client.get(post_url)
            return self._parse_comments(resp.text), False
        except Exception as e:
            if "429" in str(e):
                print(f"     429 cooldown 60s...", flush=True)
                time.sleep(60)
                # retry once after cooldown
                try:
                    resp = self.client.get(post_url)
                    return self._parse_comments(resp.text), True
                except Exception:
                    return [], True
            return [], False

    def _scrape_comments(self, post_url: str) -> list[str]:
        """Legacy: scrape without 429 handling."""
        comments, _ = self._scrape_comments_with_cooldown(post_url)
        return comments

    def _parse_comments(self, html: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        comments = []
        for comment_div in soup.select("div.comment"):
            if len(comments) >= self.max_comments:
                break
            if comment_div.find_parent("div.comment"):
                continue
            if comment_div.select_one("div.deleted, div.removed"):
                continue
            body_el = comment_div.select_one("div.md")
            if not body_el:
                continue
            text = body_el.text.strip()
            if len(text) < 10:
                continue
            comments.append(text)
        return comments

    def close(self):
        self.client.close()
