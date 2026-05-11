#!/usr/bin/env python3
"""Diagnostic test for forum spiders. Tests connectivity and HTML structure."""

from urllib.parse import urlparse
import sys

import httpx


# ── Test targets ──────────────────────────────────────────────────

SITES = {
    "kaskus": {
        "country": "ID",
        "url": "https://www.kaskus.co.id",
        "list_url": "https://www.kaskus.co.id/forum/514/lounge",
    },
    "pantip": {
        "country": "TH",
        "url": "https://pantip.com",
        "list_url": "https://pantip.com/forum/sinthorn",
    },
    "eksisozluk": {
        "country": "TR",
        "url": "https://eksisozluk.com",
        "list_url": "https://eksisozluk.com/basliklar/gundem",
    },
    "hardwarezone": {
        "country": "SG",
        "url": "https://forums.hardwarezone.com.sg",
        "list_url": "https://forums.hardwarezone.com.sg/forums/eat-drink-man-woman.16/",
    },
    "mybroadband": {
        "country": "ZA",
        "url": "https://mybroadband.co.za/forum",
        "list_url": "https://mybroadband.co.za/forum/forums/general.2/",
    },
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


def test_site(name: str, cfg: dict) -> dict:
    """Try to fetch a site. Returns diagnostic info."""
    result = {"name": name, "country": cfg["country"]}

    with httpx.Client(timeout=30, follow_redirects=True) as client:
        # 1. Homepage
        try:
            resp = client.get(cfg["url"], headers={"User-Agent": USER_AGENT})
            result["home_status"] = resp.status_code
            result["home_size"] = len(resp.text)
            result["home_encoding"] = resp.encoding or "unknown"
        except Exception as e:
            result["home_status"] = 0
            result["home_error"] = str(e)[:120]
            result["list_status"] = 0
            return result

        # 2. Forum listing page
        try:
            resp2 = client.get(cfg["list_url"], headers={"User-Agent": USER_AGENT})
            result["list_status"] = resp2.status_code
            result["list_size"] = len(resp2.text)

            # Quick HTML structure analysis
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp2.text, "lxml")

            # Sample common thread/link patterns
            links = soup.select("a[href]")
            thread_links = []
            for a in links[:200]:
                href = a.get("href", "")
                text = a.get_text(strip=True)
                if len(text) > 10:
                    thread_links.append({"text": text[:80], "href": href[:120]})

            result["sample_links"] = thread_links[:10]
            result["total_links"] = len(links)

            # Check for relevant CSS markers
            selectors_checked = {
                "article": len(soup.select("article")),
                "div.thread": len(soup.select("div.thread, div[class*=thread], div[class*=post], div[class*=topic], div[class*=entry]")),
                "li.thread": len(soup.select("li[class*=thread], li[class*=post], li[class*=topic], li[class*=entry]")),
                "h1/h2": len(soup.select("h1, h2, h3")),
                "a.title": len(soup.select("a[class*=title], a[class*=subject], a[class*=link]")),
            }
            result["structure"] = selectors_checked

        except Exception as e:
            result["list_status"] = 0
            result["list_error"] = str(e)[:120]

    return result


def main():
    print("Testing forum connectivity and HTML structure...\n")
    print("=" * 60)

    for name, cfg in SITES.items():
        print(f"\n▸ {name} ({cfg['country']}): {cfg['url']}")
        r = test_site(name, cfg)

        if r.get("home_status") == 200:
            print(f"  ✓ Homepage: HTTP 200, {r['home_size']:,} bytes, encoding={r['home_encoding']}")
        elif r.get("home_error"):
            print(f"  ✗ Homepage: {r['home_error']}")
        else:
            print(f"  ✗ Homepage: HTTP {r.get('home_status', '?')}")

        if r.get("list_status") == 200:
            print(f"  ✓ List page: HTTP 200, {r['list_size']:,} bytes")
        elif r.get("list_error"):
            print(f"  ✗ List page: {r['list_error']}")

        # Show structure if we got HTML
        if "structure" in r:
            print(f"  Structure: {r['structure']}")
            print(f"  Total <a> tags: {r.get('total_links', 0)}")

        # Show sample links
        if "sample_links" in r and r["sample_links"]:
            print(f"  Sample links (first {len(r['sample_links'])}):")
            for link in r["sample_links"][:5]:
                print(f"    - {link['text']}")
                print(f"      {link['href']}")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
