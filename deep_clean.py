#!/usr/bin/env python3
"""深度清洗 raw_bulk 数据：去 UI 文本、压缩换行、按句子拆分、去噪。

用法:
  python deep_clean.py              # 清洗全部，输出到 data/cleaned/
  python deep_clean.py SG TH        # 只清洗指定国家
"""

import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd


# ── 论坛界面噪音文本 ──
NOISE_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        # 通用
        r"^loading\.\.\.$",
        r"^\[POST\].*$", r"^\[COMMENT\s*#?\d*\].*$", r"^\[deleted\]$", r"^\[removed\]$",
        r"^deleted$", r"^removed$",
        r"^\d+ (minutes?|hours?|days?) ago$", r"^\d+ (dakika|saat|gün) (önce|once)$",
        r"^repl(ies|y)$", r"^upvote$", r"^downvote$",
        r"^share$", r"^report$", r"^save$", r"^hide$",
        r"^see more$", r"^view all comments$",
        r"^use app$", r"^open in app$",
        r"^©\s*\d{4}.*$", r"^all rights reserved\.?$",
        # 土耳其语
        r"^mesaj.*n.*z kopyaland.*$", r"^ctrl\+v.*yap.*t.*rabilirsiniz\.?$",
        r"^kaydol$", r"^giri.*$", r"^üye gir.*$",
        r"^bölüme git$", r"^popüler konular$", r"^standart sürüm$", r"^gece modu$",
        r"^bu konuyu yan.*tlayabilmek için.*$",
        r"^gizlilik politikas.*$", r"^üyelik s.*zle.*mesi$",
        r"^yorum yap$", r"^cevapla$", r"^yan.*tla$",
        r"^be.*en$", r"^be.*enmedim$", r"^payla.*$",
        r"^şikayet et$", r"^bildir$",
        r"^\d+ yorum$", r"^\d+ cevap$", r"^tümünü gör$", r"^daha fazla$",
        r"^cookie.*politik.*$",
        # 葡萄牙语
        r"^para comentar por favor.*$", r"^fale conosco$",
        r"^política de privacidade$", r"^termos de uso$",
        r"^voltar ao topo$", r"^registre-se$", r"^entrar$",
        r"^tema escuro$", r"^tema claro$", r"^responsivo$",
        r"^compartilhar$", r"^compartilhe$", r"^curtir$", r"^comentar$",
        r"^envie por e-mail$", r"^imprimir$",
        # 西班牙语
        r"^compartir$", r"^comparte$", r"^me gusta$", r"^no me gusta$",
        r"^denunciar$", r"^responder$", r"^comenta$", r"^comentarios$",
        r"^opciones de compartir$", r"^copiar vínculo$", r"^enlace copiado$",
        r"^correo$", r"^whatsapp$", r"^facebook$", r"^twitter$",
        r"^regístrate$", r"^iniciar sesión$",
        r"^política de cookies$", r"^aviso legal$", r"^términos y condiciones$",
        r"^noticias de hoy$",
        # 阿拉伯语
        r"^تسجيل الدخول$", r"^تسجيل$", r"^خروج$",
        r"^مشاركة$", r"^إبلاغ$", r"^رد$", r"^تعليق$",
        r"^موضوع جديد$", r"^الرئيسية$",
        # 泰语
        r"^เข้าสู่ระบบ$", r"^สมัครสมาชิก$", r"^ออก$",
        r"^แชร์$", r"^รายงาน$", r"^ตอบกลับ$",
        r"^ถูกใจ$", r"^แสดงความคิดเห็น$",
        # 印尼语
        r"^masuk$", r"^daftar$", r"^keluar$",
        r"^bagikan$", r"^laporkan$", r"^balas$", r"^suka$",
        r"^komentar$", r"^tampilkan semua$",
    ]
]

# ── [POST] / [COMMENT] 前缀 ──
PREFIX_RE = re.compile(r"^\[(?:POST|COMMENT\s*#?\d*)\]\s*", re.IGNORECASE)

# ── 句子边界 ──
SENTENCE_END = re.compile(r"([.!?…。！？\n])\s*")


def remove_noise(text: str) -> str:
    """去除论坛界面文本噪音。"""
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.strip()
        # 跳过纯噪音行
        if any(p.match(stripped) for p in NOISE_PATTERNS):
            continue
        # 跳过太短的无意义行
        if len(stripped) < 2:
            continue
        cleaned.append(stripped)
    return "\n".join(cleaned)


def normalize_text(text: str) -> str:
    """激进规范化：合并所有多余空白，保留合理段落。"""
    if not isinstance(text, str):
        return ""

    # 0. 去 [POST] / [COMMENT #N] 前缀
    text = PREFIX_RE.sub("", text)

    # 1. Unicode 正规化
    text = unicodedata.normalize("NFC", text)

    # 2. 统一换行符
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 3. 去控制字符
    text = "".join(ch for ch in text if ch.isprintable() or ch in "\n\t")

    # 4. 合并所有连续换行 → 最多1个空行
    text = re.sub(r"\n{2,}", "\n\n", text)

    # 5. 去每行首尾空白
    lines = [l.strip() for l in text.split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()

    # 6. 合并连续空格
    text = "\n".join(lines)
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r"\t+", " ", text)

    return text.strip()


def split_by_sentence(text: str, max_chars: int = 200) -> list[str]:
    """长文本按句子边界拆分，每段不超过 max_chars。"""
    if len(text) <= max_chars:
        return [text]

    # 尝试在句子边界处分割
    parts = []
    current = ""
    for chunk in SENTENCE_END.split(text):
        if not chunk:
            continue
        if len(current) + len(chunk) < max_chars:
            current += chunk
        else:
            if current.strip():
                parts.append(current.strip())
            current = chunk

    if current.strip():
        parts.append(current.strip())

    # 如果还有超长的，强制按字数切割
    final = []
    for p in parts:
        if len(p) <= max_chars:
            final.append(p)
        else:
            # 按空格强制分割
            words = p.split(" ")
            chunk = ""
            for w in words:
                if len(chunk) + len(w) < max_chars:
                    chunk += (" " if chunk else "") + w
                else:
                    if chunk:
                        final.append(chunk)
                    chunk = w
            if chunk:
                final.append(chunk)

    return final if final else [text]


def is_valuable(text: str) -> bool:
    """判断文本是否有保留价值。"""
    if not text or len(text) < 8:
        return False

    # 纯数字/符号
    if re.match(r"^[\d\s\.,;:!?\-–—()\[\]{}<>\"'`~@#$%^&*+=/\\|]+$", text):
        return False

    # 纯URL
    if re.match(r"^https?://\S+$", text.strip()):
        return False

    # 纯 emoji
    if len(text) < 20 and all(ord(c) > 127 or c.isspace() for c in text):
        return False

    # 重复字符过多
    if len(set(text)) < 5 and len(text) > 20:
        return False

    return True


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """对整个 DataFrame 做深度清洗。"""
    # 清洗
    if "body" in df.columns:
        df["body"] = df["body"].astype(str).apply(normalize_text).apply(remove_noise)
    if "title" in df.columns:
        df["title"] = df["title"].astype(str).apply(normalize_text)

    # 过滤
    if "body" in df.columns:
        df = df[df["body"].apply(is_valuable)]

    # 拆分超长文本
    if "body" in df.columns:
        rows = []
        for _, row in df.iterrows():
            parts = split_by_sentence(row["body"], max_chars=250)
            for part in parts:
                if is_valuable(part):
                    new_row = row.to_dict()
                    new_row["body"] = part
                    rows.append(new_row)
        df = pd.DataFrame(rows)

    return df


def main():
    src_dir = Path("data/raw_bulk")
    out_dir = Path("data/cleaned")
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.csv"):
        old.unlink()

    countries = sys.argv[1:] if len(sys.argv) > 1 else None

    total = 0
    for country_dir in sorted(src_dir.iterdir()):
        if not country_dir.is_dir():
            continue
        country = country_dir.name
        if countries and country not in countries:
            continue

        print(f"Cleaning {country}...", end=" ", flush=True)

        # 加载所有 parquet
        dfs = []
        for pq in country_dir.glob("*.parquet"):
            if pq.stat().st_size == 0:
                continue
            try:
                dfs.append(pd.read_parquet(pq))
            except Exception:
                pass

        if not dfs:
            print("no data")
            continue

        df = pd.concat(dfs, ignore_index=True)

        # 深度清洗
        df = clean_dataframe(df)

        # 保存
        keep_cols = ["source", "country", "url", "title", "body", "type",
                     "subreddit", "forum", "sort", "created_at"]
        cols = [c for c in keep_cols if c in df.columns]
        df[cols].to_csv(out_dir / f"{country}.csv", index=False, encoding="utf-8-sig")

        types = df["type"].value_counts().to_dict() if "type" in df.columns else {}
        print(f"{len(df)} rows (post={types.get('post', 0)}, comment={types.get('comment', 0)})")
        total += len(df)

    print(f"\nTotal clean: {total} → data/cleaned/")


if __name__ == "__main__":
    main()
