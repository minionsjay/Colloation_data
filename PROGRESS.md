# Colloation Data — 爬取进展

**更新时间:** 2026-05-14 23:36  
**清洗后总量:** 595,343 条  
**原始数据量:** ~180,000 条  
**覆盖国家:** 11 个

---

## 各国数据概览

| 代码 | 国家 | 清洗数据 | 本地语占比 | 主要语言 Top 3 |
|------|------|----------|-----------|---------------|
| BR | 巴西 | 110,358 | 76.5% | pt(70K) · en(26K) · es(4.7K) |
| TR | 土耳其 | 87,523 | 87.9% | tr(66K) · en(11K) · de(1K) |
| MX | 墨西哥 | 63,465 | 52.8% | en(30K) · es(25K) · pt(2.1K) |
| SA | 沙特阿拉伯 | 61,274 | 43.7% | en(34K) · ar(21K) · arz(1.4K) |
| ZA | 南非 | 47,495 | 14.0% | en(41K) · af(1.8K) · nl(1.1K) |
| AE | 阿联酋 | 44,212 | 16.0% | en(37K) · ar(6K) · arz(945) |
| SG | 新加坡 | 41,860 | 8.7% | en(38K) · fr(485) · de(459) |
| TH | 泰国 | 39,401 | 36.6% | en(25K) · th(12K) · de(455) |
| PH | 菲律宾 | 34,468 | 21.8% | en(27K) · tl(7.4K) · ceb(33) |
| ID | 印度尼西亚 | 33,970 | 49.8% | en(17K) · id(10K) · ms(1.7K) |
| VN | 越南 | 31,317 | 44.9% | en(17K) · vi(14K) · fr(11) |

---

## 各国 Reddit 子版块

| 国家 | 子版块 |
|------|--------|
| BR | r/brasil, r/Brazil, r/futebol |
| TR | r/turkey, r/TurkeyJerky |
| MX | r/mexico, r/mexicanfood, r/espanolmexico |
| SA | r/saudiarabia, r/Arabs |
| ZA | r/southafrica, r/afrikaans |
| AE | r/dubai, r/UAE, r/abudhabi, r/Emiratis, r/DubaiPetrolHeads, r/DubaiCentral, r/DubaiGaming, r/Ajman, r/Sharjah, r/RasAlKhaimah |
| SG | r/singapore, r/SingaporeRaw |
| TH | r/thailand, r/thaithai |
| PH | r/Philippines, r/CasualPH, r/ChikaPH, r/phinvest |
| ID | r/indonesia, r/indonesian |
| VN | r/VietNam, r/Vietnamese, r/TroChuyenLinhTinh |

---

## 数据文件位置

```
data/cleaned_v4/            ← 8 个原有国家 + PH, VN, TH (Parquet)
├── BR.parquet   (110,358)
├── TR.parquet   ( 87,523)
├── MX.parquet   ( 63,465)
├── SA.parquet   ( 61,274)
├── ZA.parquet   ( 47,495)
├── SG.parquet   ( 41,860)
├── TH.parquet   ( 39,401)
├── PH.parquet   ( 34,468)
├── ID.parquet   ( 33,970)
├── VN.parquet   ( 31,317)
└── ...

data/clean/uae/
└── cleaned_uae.parquet     (44,212)  ← 阿联酋

data/raw/                   ← 原始爬取数据
data/raw/uae/               ← 阿联酋原始数据
data/raw/th/                ← 泰国原始数据
data/raw/vn/                ← 越南原始数据
```

---

## 爬取脚本

| 脚本 | 用途 |
|------|------|
| `run_crawl.py` | 通用 Reddit PRAW API 爬取 |
| `run_uae_crawl.py` | 阿联酋专用混合策略爬取 |
| `run_country_crawl.py` | 通用国家爬取 `python run_country_crawl.py <CODE> <pages> <comments> <target>` |
| `run_lang_boost.py` | 本地语言增强爬取 |

---

## 关键技术细节

- **数据来源:** 所有数据均来自 Reddit (old.reddit.com)，无 API 凭据要求
- **爬取方式:** HTML 解析 + 分页 + 评论拆分（每个评论作为独立记录）
- **清洗流程:** HTML 去标签 → Unicode 正规化 → fasttext 语种检测 → MinHash LSH 去重 → 质量过滤
- **格式:** Parquet (pandas 直接加载)
- **陪审团:** 三席并行判断 (本地专才 + 开源中坚 + 云端高阶) → 法官终审

## 已知限制

- Reddit 英语占主导，新加坡/阿联酋/南非/菲律宾本地语言占比偏低
- 非 Reddit 论坛 (Pantip, Kompasiana 等) 尚未大规模爬取
- 部分论坛 (Kaskus, Ekşi Sözlük 等) 因 Cloudflare 拦截无法访问
