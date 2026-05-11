"""Pantip spider with Playwright — renders JS to get posts + comments.

Requires: playwright (pip install playwright && python -m playwright install chromium)
"""

import asyncio
import re
from datetime import datetime, timezone
from typing import Iterator

from crawler.base_spider import RawPost

# 敏感话题房间
ROOMS = [
    ("https://pantip.com/forum/sinthorn", "social & political"),
    ("https://pantip.com/forum/rajdumnern", "current affairs"),
]


class PantipCommentSpider:
    """Scrapes Pantip topics + comments using headless Chromium."""

    BASE = "https://pantip.com"

    def __init__(self, limit: int = 30, max_comments: int = 30):
        self.limit = limit
        self.max_comments = max_comments

    def scrape(self) -> list[RawPost]:
        return asyncio.get_event_loop().run_until_complete(self._scrape_async())

    async def _scrape_async(self):
        import os
        from playwright.async_api import async_playwright

        proxy_url = os.getenv("http_proxy", "") or os.getenv("https_proxy", "")

        posts = []
        async with async_playwright() as p:
            launch_args = {"headless": True}
            if proxy_url:
                launch_args["proxy"] = {"server": proxy_url}

            browser = await p.chromium.launch(**launch_args)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                locale="th-TH",
            )
            page = await context.new_page()

            for room_url, _room_name in ROOMS:
                topic_urls = await self._scrape_room(page, room_url)
                for url in topic_urls:
                    if len(posts) >= self.limit:
                        break
                    post = await self._scrape_topic(page, url)
                    if post:
                        posts.append(post)
                        print(f"  [{len(posts)}] {post.title[:60]}...")

                if len(posts) >= self.limit:
                    break

            await browser.close()
        return posts

    async def _scrape_room(self, page, url: str) -> list[str]:
        """Get topic URLs from a room listing page."""
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(3000)  # 等 JS 渲染

        hrefs = await page.eval_on_selector_all(
            'a[href*="/topic/"]',
            "els => els.map(e => e.getAttribute('href')).filter(h => h && h.includes('/topic/'))"
        )
        seen = set()
        unique = []
        for h in hrefs:
            if h not in seen and "/tag/" not in h:
                seen.add(h)
                # href 可能已是完整 URL，也可能是相对路径
                url = h if h.startswith("http") else self.BASE + h
                unique.append(url)
        return unique[:self.limit]

    async def _scrape_topic(self, page, url: str) -> RawPost | None:
        """Scrape a single topic page: title + body + comments."""
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            # 等待评论 JS 渲染
            await page.wait_for_timeout(4000)
        except Exception:
            return None

        # 标题
        try:
            title = await page.text_content("h1.display-post-title")
            title = title.strip() if title else ""
        except Exception:
            title = ""

        # 正文
        try:
            body = await page.text_content("div.display-post-story")
            body = body.strip() if body else ""
        except Exception:
            body = ""

        # 评论
        comments = []
        try:
            comment_els = await page.query_selector_all(".display-post-story-wrapper .display-post-story, .comment-text")
            for el in comment_els[:self.max_comments]:
                text = await el.text_content()
                text = text.strip()
                if len(text) >= 10:  # 过滤太短的
                    comments.append(text)
        except Exception:
            pass

        # 如果上面的选择器没拿到，尝试更广泛的匹配
        if not comments:
            try:
                all_text = await page.evaluate("""
                    () => {
                        const comments = document.querySelectorAll('.comment-box-remark, .display-post-story');
                        return Array.from(comments).map(c => c.textContent.trim()).filter(t => t.length > 10);
                    }
                """)
                comments = all_text[:self.max_comments]
            except Exception:
                pass

        # 拼接
        full_body = f"[POST]\n{title}\n\n{body}"
        if comments:
            full_body += "\n\n[COMMENTS]\n" + "\n---\n".join(comments)

        if not title and not body:
            return None

        return RawPost(
            source="pantip",
            country="TH",
            url=url,
            title=title,
            body=full_body.strip(),
            author_hash=RawPost.hash_author("anonymous"),
            created_at=datetime.now(timezone.utc),
            metadata={"comment_count": len(comments), "room": url.split("/")[-2]},
        )


if __name__ == "__main__":
    # 快速测试
    spider = PantipCommentSpider(limit=5, max_comments=10)
    posts = spider.scrape()
    for p in posts:
        print(f"\n{'='*60}")
        print(f"Title: {p.title}")
        print(f"Comments: {p.metadata.get('comment_count', 0)}")
        print(f"Body ({len(p.body)} chars): {p.body[:500]}...")
