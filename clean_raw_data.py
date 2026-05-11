#!/usr/bin/env python3
"""清洗 raw_bulk 数据：去多余换行/空格，每行一个连贯内容。

用法:
  python clean_raw_data.py              # 清洗全部
  python clean_raw_data.py SG TH        # 只清洗指定国家
"""

import re
import sys
from pathlib import Path

import pandas as pd


def clean_text(text: str) -> str:
    """清洗单条文本：去多余空白、规范化换行。"""
    if not isinstance(text, str):
        return ""

    # 1. 替换多余连续换行（3+ → 2）
    text = re.sub(r"\n{3,}", "\n\n", text)

    # 2. 替换连续空白行中的空格
    text = re.sub(r" +\n", "\n", text)
    text = re.sub(r"\n +", "\n", text)

    # 3. 去除每行首尾空白
    lines = [line.strip() for line in text.split("\n")]
    # 去掉空行开头/结尾
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()

    text = "\n".join(lines)

    # 4. 压缩连续空格（3+ → 2）
    text = re.sub(r" {3,}", "  ", text)

    # 5. 去除不可见控制字符（保留换行）
    text = "".join(ch for ch in text if ch.isprintable() or ch in "\n\t")

    # 6. 规范化 Unicode
    import unicodedata
    text = unicodedata.normalize("NFC", text)

    return text.strip()


def is_valid_content(text: str, min_len: int = 10) -> bool:
    """过滤无效内容。"""
    if not text or len(text) < min_len:
        return False
    # 过滤纯占位符
    low = text.lower().strip()
    if low in ("loading...", "[deleted]", "[removed]", "", ".", ".."):
        return False
    # 过滤纯数字/符号
    if re.match(r"^[\d\s\.,;:!?\-–—()\[\]{}<>\"'`~@#$%^&*+=/\\|]+$", text):
        return False
    return True


def split_long_text(text: str, max_lines: int = 15) -> list[str]:
    """超长文本拆成多个段落，每个段落保持连贯。"""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if len(lines) <= max_lines:
        return ["\n".join(lines)]

    # 按 max_lines 拆分
    chunks = []
    for i in range(0, len(lines), max_lines):
        chunk = "\n".join(lines[i:i + max_lines])
        if chunk.strip():
            chunks.append(chunk)
    return chunks


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """清洗一个国家的 DataFrame。"""
    # 清洗 body
    df["body"] = df["body"].apply(clean_text)
    df["title"] = df["title"].apply(clean_text)

    # 过滤无效
    before = len(df)
    df = df[df["body"].apply(is_valid_content)]
    after = len(df)
    if before > after:
        print(f"    Filtered {before - after} invalid rows")

    return df


def main():
    src_dir = Path("data/raw_bulk_csv")
    out_dir = Path("data/cleaned")
    out_dir.mkdir(parents=True, exist_ok=True)

    countries = sys.argv[1:] if len(sys.argv) > 1 else None

    total = 0
    for csv_path in sorted(src_dir.glob("*.csv")):
        country = csv_path.stem
        if countries and country not in countries:
            continue

        print(f"Cleaning {country}...", end=" ", flush=True)
        df = pd.read_csv(csv_path)
        df = clean_dataframe(df)
        df.to_csv(out_dir / f"{country}.csv", index=False, encoding="utf-8-sig")
        print(f"{len(df)} rows")
        total += len(df)

    print(f"\nDone! {total} clean rows → data/cleaned/")


if __name__ == "__main__":
    main()
