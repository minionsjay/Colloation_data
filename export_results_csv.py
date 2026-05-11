#!/usr/bin/env python3
"""将陪审团结果导出为 CSV，按语种分文件，违规内容自动生成中文解释。

用法:
  python export_results_csv.py                          # 处理最新的 parquet
  python export_results_csv.py data/results/xxx.parquet  # 指定文件
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import httpx
import pandas as pd

from config import settings


def find_latest_parquet():
    """找到最新的 full_pipeline parquet 文件。"""
    results_dir = Path("data/results")
    files = sorted(results_dir.glob("full_pipeline_*.parquet"), reverse=True)
    if not files:
        print("没有找到 full_pipeline_*.parquet 文件！")
        sys.exit(1)
    return files[0]


def generate_chinese_explanation(text: str, title: str, category: str,
                                  agreement: str, api_key: str,
                                  base_url: str) -> str:
    """调用 LLM 生成违规内容的中文解释。"""
    prompt = f"""请用简洁的中文解释为什么以下内容被判定为违规。不要翻译全文，只解释违规原因（2-3句话）。

内容标题: {title[:200]}
违规类别: {category}
陪审团结论: {agreement}

原文内容:
{text[:1000]}

请输出中文解释:"""

    try:
        with httpx.Client(trust_env=False, timeout=30.0) as client:
            resp = client.post(
                base_url,
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": "qwen2.5-72b-instruct",
                    "messages": [
                        {"role": "system", "content": "你是内容审核专家，用简洁中文解释违规原因。"},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 200,
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"（解释生成失败: {e}）"


def main():
    pq_path = sys.argv[1] if len(sys.argv) > 1 else str(find_latest_parquet())
    print(f"读取: {pq_path}")

    df = pd.read_parquet(pq_path)
    print(f"共 {len(df)} 条记录")

    # 解析 juror_agreement 为独立列
    def parse_agreement(agr):
        parts = {}
        if isinstance(agr, str):
            for part in agr.split(" / "):
                if ":" in part:
                    k, v = part.split(":", 1)
                    parts[f"juror_{k.strip().lower()}"] = v.strip()
        return parts

    agreement_df = df["juror_agreement"].apply(parse_agreement).apply(pd.Series)
    df = pd.concat([df, agreement_df], axis=1)

    # 清理 category 显示（去掉 ViolationCategory. 前缀）
    df["category"] = df["category"].astype(str).str.replace("ViolationCategory.", "", regex=False)
    # 清理 juror 列中的 nan
    for col in ["juror_a", "juror_b", "juror_c"]:
        if col in df.columns:
            df[col] = df[col].fillna("null")

    # 解析 verdict 为中文
    df["判定结果"] = df["final_verdict"].map({True: "违规", False: "正常", None: "未判定"})

    # 获取 API 配置
    api_key = (os.getenv("JUROR_B_API_KEY", "") or
               settings.juror_b_api_key or
               settings.juror_c_api_key)
    base_url = os.getenv("JUROR_B_BASE_URL", "https://api.vectorengine.cn/v1/chat/completions")

    # 为违规内容生成中文解释
    violations = df[df["final_verdict"] == True]
    print(f"违规 {len(violations)} 条，生成中文解释...")

    explanations = {}
    for idx, row in violations.iterrows():
        text = row.get("text", "")[:1000]
        title = row.get("title", "")
        category = row.get("category", "unknown")
        agreement = row.get("juror_agreement", "")
        print(f"  [{idx}] {title[:40]}...", end=" ", flush=True)
        expl = generate_chinese_explanation(text, title, str(category),
                                            str(agreement), api_key, base_url)
        explanations[idx] = expl
        print(f"✓ {expl[:50]}...")

    df["违规原因(中文)"] = df.index.map(explanations.get)

    # 输出列定义
    out_columns = [
        "content_id", "判定结果", "category", "confidence",
        "language", "country", "source", "title", "text",
        "juror_a", "juror_b", "juror_c",
        "adopted_juror", "judge_model",
        "requires_human_review", "违规原因(中文)",
        "lang_conf", "quality", "reasoning", "judged_at",
    ]

    # 按语种分组导出
    export_dir = Path("data/results/csv")
    export_dir.mkdir(parents=True, exist_ok=True)

    for lang, group in df.groupby("language"):
        # 只保留存在的列
        cols = [c for c in out_columns if c in group.columns]
        group_sorted = group[cols].sort_values("判定结果", ascending=False)
        csv_path = export_dir / f"jury_results_{lang}.csv"
        group_sorted.to_csv(csv_path, index=False, encoding="utf-8-sig")
        v_count = (group["final_verdict"] == True).sum()
        print(f"  → {csv_path.name}: {len(group)} 条 ({v_count} 违规)")

    # 全量汇总 CSV
    all_cols = [c for c in out_columns if c in df.columns]
    all_path = export_dir / "jury_results_all.csv"
    df[all_cols].sort_values(["language", "判定结果"], ascending=[True, False]) \
               .to_csv(all_path, index=False, encoding="utf-8-sig")
    print(f"  → {all_path.name}: {len(df)} 条 (汇总)")

    print(f"\n导出完成！文件在: {export_dir.resolve()}/")


if __name__ == "__main__":
    main()
