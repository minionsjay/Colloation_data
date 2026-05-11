#!/usr/bin/env python3
"""爬取 Reddit + Pantip，每条评论独立评审，结果按语种导出 CSV。"""

import json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

sys.path.insert(0, ".")

from crawler.spiders.reddit_split_comments import RedditSplitSpider
from crawler.spiders.pantip import PantipSpider
from pipeline.cleaner import clean_post, quality_check
from pipeline.language_detector import annotate_language
from jury.graph import run_jury_graph

BASE_URL = "https://api.vectorengine.cn/v1/chat/completions"


def crawl_all():
    """爬取 Reddit（含分离评论）+ Pantip。"""
    items = []

    # Reddit
    for sub in ["thaithai", "thailand"]:
        for sort in ["hot", "controversial"]:
            print(f"▸ Reddit r/{sub} ({sort})...", end=" ", flush=True)
            spider = RedditSplitSpider(subreddits=[sub], limit=10,
                                        max_comments=15, sort=sort)
            posts = list(spider.scrape())
            spider.close()
            items.extend(posts)
            print(f"{len(posts)} 条")

    # Pantip
    print("▸ Pantip...", end=" ", flush=True)
    try:
        spider = PantipSpider(limit=20)
        pantip_posts = list(spider.scrape())
        spider.close()
        for p in pantip_posts:
            p.metadata["type"] = "post"
            p.metadata["parent_id"] = str(hash(p.url))[:12]
        items.extend(pantip_posts)
        print(f"{len(pantip_posts)} 条")
    except Exception as e:
        print(f"failed: {e}")

    # 去重
    seen = set()
    unique = []
    for p in items:
        key = p.body[:200]
        if key not in seen:
            seen.add(key)
            unique.append(p)

    print(f"▸ 总计: {len(items)} → 去重后 {len(unique)} 条")
    return unique


def run_jury(items):
    """对每条内容运行陪审团。"""
    results = []
    for i, raw in enumerate(items):
        post = clean_post(raw)
        post = annotate_language(post)
        post.quality_flag = quality_check(post.clean_text, post.language_confidence)
        lang = post.language

        item_type = raw.metadata.get("type", "post")
        parent_id = raw.metadata.get("parent_id", "")[:8]
        label = f"[{i+1}/{len(items)}] [{lang}] [{item_type}:{parent_id}]"
        print(f"{label} {post.title[:50]}...", end=" ", flush=True)

        if post.quality_flag != "ok" or lang not in ("th", "en", "pt", "es"):
            print("skip")
            results.append(_skipped_result(post, item_type, parent_id))
            continue

        try:
            final = run_jury_graph(
                content_id=post.content_id, text=post.clean_text,
                source=post.source, country=post.country, language=post.language,
                juror_b_provider="custom", juror_b_model="qwen2.5-72b-instruct",
                juror_b_base_url=BASE_URL, juror_b_no_proxy=True,
                juror_c_provider="custom", juror_c_model="gpt-4o",
                juror_c_base_url=BASE_URL, juror_c_no_proxy=True,
                arbiter_provider="custom", arbiter_base_url=BASE_URL, arbiter_no_proxy=True,
                timeout=60.0,
            )
        except Exception as e:
            print(f"error: {e}")
            results.append(_skipped_result(post, item_type, parent_id))
            continue

        v = "违规" if final.final_verdict else "正常"
        print(v)

        # 解析 juror_agreement
        agr = final.juror_agreement
        juror_a = juror_b = juror_c = ""
        if agr:
            for part in agr.split(" / "):
                if ":" in part:
                    k, val = part.split(":", 1)
                    if k == "A":
                        juror_a = val.strip()
                    elif k == "B":
                        juror_b = val.strip()
                    elif k == "C":
                        juror_c = val.strip()

        results.append({
            "content_id": post.content_id,
            "parent_id": parent_id,
            "type": item_type,
            "language": lang,
            "source": post.source,
            "title": post.title[:300],
            "text": post.clean_text[:500],
            "quality": post.quality_flag,
            "final_verdict": final.final_verdict,
            "category": str(final.category).replace("ViolationCategory.", ""),
            "confidence": final.confidence,
            "adopted_juror": final.adopted_juror,
            "juror_a": juror_a,
            "juror_b": juror_b,
            "juror_c": juror_c,
            "juror_agreement": final.juror_agreement,
            "judge_model": final.judge_model,
            "requires_human_review": final.requires_human_review,
            "reasoning": final.reasoning[:500],
        })

    violations = sum(1 for r in results if r["final_verdict"] is True)
    print(f"\n{'='*60}")
    print(f"Summary: {violations} 违规 | {len(results)-violations} 正常 | {len(results)} 总计")
    return results


def _skipped_result(post, item_type, parent_id):
    return {
        "content_id": post.content_id, "parent_id": parent_id,
        "type": item_type, "language": post.language,
        "source": post.source, "title": post.title[:300],
        "text": post.clean_text[:500], "quality": post.quality_flag,
        "final_verdict": None, "category": "", "confidence": 0.0,
        "adopted_juror": "", "juror_a": "", "juror_b": "", "juror_c": "",
        "juror_agreement": "", "judge_model": "", "requires_human_review": True,
        "reasoning": "",
    }


def generate_chinese_explanations(results):
    """为违规内容生成中文解释。"""
    violations = [r for r in results if r["final_verdict"] is True]
    if not violations:
        return

    import httpx
    from config import settings
    api_key = (os.getenv("JUROR_B_API_KEY", "") or settings.juror_b_api_key)

    for r in violations:
        text = r.get("text", "")[:800]
        title = r.get("title", "")
        cat = r.get("category", "")
        agr = r.get("juror_agreement", "")
        print(f"  解释: [{r['parent_id']}] {title[:40]}...", end=" ", flush=True)

        prompt = f"""用1-2句简洁中文解释为何以下{cat}内容被判违规。不要翻译原文。

帖子: {title[:200]}
陪审: {agr}

原文: {text}

中文解释:"""

        try:
            with httpx.Client(trust_env=False, timeout=25) as c:
                resp = c.post(
                    BASE_URL,
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": "qwen2.5-72b-instruct",
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.3, "max_tokens": 150,
                    },
                )
                resp.raise_for_status()
                expl = resp.json()["choices"][0]["message"]["content"].strip()
                r["violation_reason_cn"] = expl
                print(f"✓ {expl[:50]}...")
        except Exception as e:
            r["violation_reason_cn"] = f"生成失败: {e}"
            print(f"✗ {e}")


def export_csv(results):
    """按语种导出 CSV。"""
    df = pd.DataFrame(results)
    df["判定结果"] = df["final_verdict"].map({True: "违规", False: "正常", None: "未判定"})
    df["category"] = df["category"].astype(str)

    out_cols = [
        "parent_id", "type", "判定结果", "category", "confidence",
        "language", "source", "title", "text",
        "juror_a", "juror_b", "juror_c", "adopted_juror", "judge_model",
        "requires_human_review", "violation_reason_cn",
        "juror_agreement", "reasoning", "quality",
    ]

    export_dir = Path("data/results/csv")
    export_dir.mkdir(parents=True, exist_ok=True)

    for lang, group in df.groupby("language"):
        cols = [c for c in out_cols if c in group.columns]
        csv_path = export_dir / f"split_results_{lang}.csv"
        group[cols].sort_values(["type", "判定结果"], ascending=[True, False]) \
                    .to_csv(csv_path, index=False, encoding="utf-8-sig")
        vc = (group["final_verdict"] == True).sum()
        print(f"  → {csv_path.name}: {len(group)} 条 ({vc} 违规)")

    all_cols = [c for c in out_cols if c in df.columns]
    all_path = export_dir / "split_results_all.csv"
    df[all_cols].sort_values(["language", "type", "判定结果"], ascending=[True, True, False]) \
               .to_csv(all_path, index=False, encoding="utf-8-sig")
    print(f"  → {all_path.name}: {len(df)} 条 (汇总)")

    # Parquet 备份
    pq_path = export_dir / f"split_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.parquet"
    df.to_parquet(pq_path, index=False)
    print(f"  → {pq_path.name} (备份)")


if __name__ == "__main__":
    print("=" * 60)
    print("完整流程: 爬取 → 分离评论 → 单独评审 → CSV 导出")
    print("=" * 60)

    # 1. 爬取
    items = crawl_all()
    if not items:
        print("没有爬到数据！")
        sys.exit(1)

    # 2. 陪审团
    results = run_jury(items)

    # 3. 中文解释
    print("\n生成违规中文解释...")
    generate_chinese_explanations(results)

    # 4. 导出
    print("\n导出 CSV...")
    export_csv(results)

    print("\n全部完成!")
