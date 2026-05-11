#!/usr/bin/env python3
"""清洗原始数据：不去重、不分块、不去 UI 噪音，只做基础文本清洗。"""

import re
import unicodedata
from pathlib import Path

import pandas as pd


def clean_text(text: str) -> str:
    if not isinstance(text, str):
        return ""
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" +\n", "\n", text)
    text = re.sub(r"\n +", "\n", text)
    lines = [line.strip() for line in text.split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    text = "\n".join(lines)
    text = re.sub(r" {3,}", "  ", text)
    text = "".join(ch for ch in text if ch.isprintable() or ch in "\n\t")
    text = unicodedata.normalize("NFC", text)
    return text.strip()


def is_valid(text: str, min_len: int = 10) -> bool:
    if not text or len(text) < min_len:
        return False
    low = text.lower().strip()
    if low in ("loading...", "[deleted]", "[removed]", "", ".", ".."):
        return False
    # 纯数字/符号
    if re.match(r"^[\d\s\.,;:!?\-–—()\[\]{}<>\"'`~@#$%^&*+=/\\|]+$", text):
        return False
    return True


def main():
    src_dir = Path("data/raw_bulk_csv")
    out_dir = Path("data/cleaned_original")
    out_dir.mkdir(parents=True, exist_ok=True)

    total = 0
    for csv_path in sorted(src_dir.glob("*.csv")):
        country = csv_path.stem
        print(f"Cleaning {country}...", end=" ", flush=True)
        df = pd.read_csv(csv_path)
        before = len(df)

        df["body"] = df["body"].apply(clean_text)
        df["title"] = df["title"].apply(clean_text)
        df = df[df["body"].apply(is_valid)]
        after = len(df)

        # 按 body 去重
        before_dedup = len(df)
        df = df.drop_duplicates(subset=["body"])

        df.to_csv(out_dir / f"{country}.csv", index=False, encoding="utf-8-sig")
        print(f"{after} rows (filtered {before - after}), dedup: {before_dedup} -> {len(df)}")
        total += len(df)

    print(f"\nTotal: {total} clean rows -> data/cleaned_original/")


if __name__ == "__main__":
    main()
