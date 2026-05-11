"""Reddit spider using PRAW — one API covers subreddits across all 8 countries."""

from datetime import datetime, timezone
from typing import Iterator

import praw
from praw.models import Submission

from config import settings, COUNTRY_SUBREDDITS, COUNTRY_NAMES
from crawler.base_spider import BaseSpider, RawPost


class RedditSpider(BaseSpider):
    """Fetches posts from country-specific subreddits via Reddit API."""

    def __init__(self, country: str, limit: int = 100, sort: str = "hot"):
        super().__init__(source="reddit", country=country, limit=limit)
        self.sort = sort
        self.subreddits = COUNTRY_SUBREDDITS.get(country, [])
        self._reddit = praw.Reddit(
            client_id=settings.reddit_client_id,
            client_secret=settings.reddit_client_secret,
            user_agent=settings.reddit_user_agent,
        )

    def scrape(self) -> Iterator[RawPost]:
        if not self.subreddits:
            return

        for sub_name in self.subreddits:
            subreddit = self._reddit.subreddit(sub_name)
            posts = self._get_posts(subreddit)

            for submission in posts:
                yield self._to_raw_post(submission)

    def _get_posts(self, subreddit):
        match self.sort:
            case "hot":
                return subreddit.hot(limit=self.limit)
            case "new":
                return subreddit.new(limit=self.limit)
            case "top":
                return subreddit.top(limit=self.limit)
            case _:
                return subreddit.hot(limit=self.limit)

    def _to_raw_post(self, s: Submission) -> RawPost:
        body = s.selftext or ""
        # Combine title + body when body is short; use both for context
        full_text = f"{s.title}\n\n{body}".strip()

        return RawPost(
            source="reddit",
            country=self.country,
            url=f"https://reddit.com{s.permalink}",
            title=s.title,
            body=full_text,
            author_hash=RawPost.hash_author(str(s.author) if s.author else "deleted"),
            created_at=datetime.fromtimestamp(s.created_utc, tz=timezone.utc),
            metadata={
                "subreddit": s.subreddit.display_name,
                "score": s.score,
                "num_comments": s.num_comments,
                "upvote_ratio": s.upvote_ratio,
            },
        )


def crawl_all_reddit(limit_per_country: int = 100) -> list[RawPost]:
    """Convenience: crawl Reddit for all 8 configured countries."""
    all_posts: list[RawPost] = []
    for code in COUNTRY_SUBREDDITS:
        name = COUNTRY_NAMES.get(code, code)
        print(f"Crawling Reddit: {name} ({code})")
        spider = RedditSpider(country=code, limit=limit_per_country)
        posts = list(spider.scrape())
        print(f"  → {len(posts)} posts")
        all_posts.extend(posts)
    return all_posts
