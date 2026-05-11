#!/usr/bin/env python3
"""爬取泰语文本并运行完整 LangGraph 陪审团 + 仲裁流程，结果落盘。

用法:
  python run_full_pipeline.py          # 爬 50 条
  python run_full_pipeline.py 100      # 爬 100 条
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, ".")

from config import settings
from crawler.spiders.reddit_with_comments import RedditCommentsSpider
from pipeline.cleaner import clean_post, quality_check
from pipeline.language_detector import annotate_language
from jury.graph import run_jury_graph

BASE_URL = os.getenv("JUROR_B_BASE_URL", "https://api.vectorengine.cn/v1/chat/completions")


def crawl_thai_posts(limit: int = 30):
    """爬取泰国 Reddit 帖子（含评论）。"""
    all_posts = []
    subreddits = ["thaithai", "thailand"]
    sorts = ["hot", "controversial", "top"]

    for sub in subreddits:
        for sort in sorts:
            print(f"▸ 爬取 r/{sub} ({sort})...", end=" ", flush=True)
            t0 = time.monotonic()
            spider = RedditCommentsSpider(
                subreddits=[sub], limit=limit, max_comments=20, sort=sort,
            )
            posts = list(spider.scrape())
            spider.close()
            all_posts.extend(posts)
            elapsed = time.monotonic() - t0
            print(f"{len(posts)} 条 ({elapsed:.1f}s)")

    # 去重（可能有跨排序重复）
    seen = set()
    unique = []
    for p in all_posts:
        if p.url not in seen:
            seen.add(p.url)
            unique.append(p)
    print(f"▸ 总计: {len(all_posts)} → 去重后 {len(unique)} 条")
    return unique


def clean_and_detect(raw_posts):
    """清洗 + 语种检测。"""
    cleaned = []
    for raw in raw_posts:
        post = clean_post(raw)
        post = annotate_language(post)
        post.quality_flag = quality_check(post.clean_text, post.language_confidence)
        cleaned.append(post)
    return cleaned


def run_jury_on_posts(cleaned_posts):
    """对每条清洗后的帖子运行 LangGraph 陪审团 + 仲裁。"""
    results = []
    total = len(cleaned_posts)
    violation_count = 0
    clean_count = 0

    for i, post in enumerate(cleaned_posts):
        print(f"\n[{i+1}/{total}] [{post.language}] {post.title[:60]}...", flush=True)

        # 只对有模型的语种跑陪审团
        if post.language not in ("th", "en", "pt", "es"):
            print(f"  ⚠ 语种 {post.language} 无可用 Juror A 模型，跳过 B/C")
            final = None
        elif post.quality_flag != "ok":
            print(f"  ⚠ 质量问题 ({post.quality_flag})，跳过")
            final = None
        else:
            try:
                final = run_jury_graph(
                    content_id=post.content_id,
                    text=post.clean_text,
                    source=post.source,
                    country=post.country,
                    language=post.language,
                    juror_b_provider="custom",
                    juror_b_model="qwen2.5-72b-instruct",
                    juror_b_base_url=BASE_URL,
                    juror_b_no_proxy=True,
                    juror_c_provider="custom",
                    juror_c_model="gpt-4o",
                    juror_c_base_url=BASE_URL,
                    juror_c_no_proxy=True,
                    arbiter_provider="custom",
                    arbiter_base_url=BASE_URL,
                    arbiter_no_proxy=True,
                    timeout=60.0,
                )
            except Exception as e:
                print(f"  ✗ 陪审团异常: {e}")
                final = None

        if final:
            v = "违规" if final.final_verdict else "正常"
            if final.final_verdict:
                violation_count += 1
            else:
                clean_count += 1
            print(f"  → {v} | {final.category} | conf={final.confidence:.2f} | {final.juror_agreement} | judge={final.judge_model}")
        else:
            print(f"  → 跳过")

        results.append({
            "content_id": post.content_id,
            "country": post.country,
            "language": post.language,
            "source": post.source,
            "title": post.title[:300],
            "text": post.clean_text[:500],
            "quality": post.quality_flag,
            "lang_conf": post.language_confidence,
            "final_verdict": final.final_verdict if final else None,
            "category": str(final.category) if final else "skipped",
            "confidence": final.confidence if final else 0.0,
            "adopted_juror": final.adopted_juror if final else "",
            "juror_agreement": final.juror_agreement if final else "",
            "judge_model": final.judge_model if final else "",
            "requires_human_review": final.requires_human_review if final else True,
            "reasoning": final.reasoning[:500] if final else "",
            "judged_at": datetime.now(timezone.utc).isoformat(),
        })

    print(f"\n{'='*60}")
    print(f"Summary: {violation_count} 违规 | {clean_count} 正常 | {total} 总计")
    return results


def save_results(results):
    """保存结果到 JSON + Parquet。"""
    results_dir = Path("data/results")
    results_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # JSON
    json_path = results_dir / f"full_pipeline_{ts}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nSaved JSON: {json_path} ({json_path.stat().st_size:,} bytes)")

    # Parquet
    df = pd.DataFrame(results)
    pq_path = results_dir / f"full_pipeline_{ts}.parquet"
    df.to_parquet(pq_path, index=False)
    print(f"Saved Parquet: {pq_path} ({pq_path.stat().st_size:,} bytes)")

    return json_path, pq_path


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 50

    print("=" * 60)
    print("完整流程: 爬取 → 清洗 → LangGraph 陪审团 → 仲裁 → 落盘")
    print("=" * 60)

    # Phase 1: 爬取
    raw = crawl_thai_posts(limit)
    if not raw:
        print("没有爬到数据！")
        sys.exit(1)

    # Phase 2: 清洗
    cleaned = clean_and_detect(raw)
    print(f"▸ 清洗完成: {len(cleaned)} 条")
    langs = {}
    for p in cleaned:
        langs[p.language] = langs.get(p.language, 0) + 1
    print(f"  语种分布: {langs}")

    # Phase 3: 陪审团 + 仲裁
    results = run_jury_on_posts(cleaned)

    # Phase 4: 落盘
    save_results(results)
    print("\n全部完成!")
