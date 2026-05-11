# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

小语种内容合规审核数据收集系统。爬取 8 个目标国家的主流论坛内容，通过三席"陪审团"模型 + 法官模型的架构进行违规/不违规判断，最终产出高质量标注数据集。

## 目标国家与语种

| 区域 | 国家 | 主要语种 | 备注 |
|------|------|----------|------|
| 东南亚 | 新加坡 | 英语、中文、马来语、泰米尔语 | 多语种混合 |
| 东南亚 | 印度尼西亚 | 印尼语 (Bahasa Indonesia) | |
| 东南亚 | 泰国 | 泰语 | 需要泰语分词（没有词间空格） |
| 中东 | 土耳其 | 土耳其语 | 黏着语，形态复杂 |
| 中东 | 沙特阿拉伯 | 阿拉伯语 | 方言与标准阿拉伯语差异大 |
| 拉美 | 巴西 | 葡萄牙语（巴西葡语） | 需区分欧洲葡语 |
| 拉美 | 墨西哥 | 西班牙语（墨西哥西语） | |
| 非洲 | 南非 | 英语、阿非利卡语、祖鲁语、科萨语等 | 11 种官方语言，论坛以英语为主 |

## 整体架构

```
┌──────────┐    ┌──────────────┐    ┌────────────────────────────┐    ┌──────────┐
│ 爬虫模块  │ ─▶ │ 数据清洗/存储  │ ─▶ │ 三席陪审团并行判断            │ ─▶ │ 法官裁决  │
│ Crawler  │    │ Data Pipeline │    │ (A:本地专才 B:开源中坚 C:云端) │    │ Arbiter  │
└──────────┘    └──────────────┘    └────────────────────────────┘    └──────────┘
```

## 陪审团设计（核心）

每段内容同时由三位"陪审员"独立判断，每位必须输出完整的推理过程（Reasoning），而非仅输出标签。

### 陪审员 A — 本地轻量级专才 (Local Specialist)

- **定位：** 部署在本地的微调小模型，专注特定语种的仇恨言论/违规内容检测
- **推理成本：** 零（本地 GPU 推理）
- **优势：** 对当地语言的俚语、黑话、隐晦攻击高度敏感；隐私数据不出站
- **候选模型：**
  - 葡萄牙语：TeenyTinyLlama-460m-HateBR（巴西仇恨言论微调）
  - 西班牙语：bert-base-spanish-unsmile（墨西哥西语有害内容）
  - 阿拉伯语：AraBERT-hate-speech
  - 印尼语：IndoBERT-hate-speech
  - 泰语：wangchanberta-hate-speech
  - 土耳其语：BERTurk-offensive
  - 多语言兜底：small-e5 或 LaBSE 做 embedding + 简单分类头
- **关键约束：** 每个语种需要一个对应的微调模型；初期如果某语种没有现成模型，先用多语言小模型兜底，后续用标注数据微调

### 陪审员 B — 开源中坚力量 (Open-Source Generalist)

- **定位：** 调用 API 托管的开源大模型，规模中等（8B~70B），侧重常识推理与上下文理解
- **优势：** 泛化能力强，能捕捉隐晦违规（讽刺、反串、隐喻），在低资源语种上也有一定理解力
- **候选模型：**
  - Llama-3.1-8B / 70B Instruct
  - Qwen2.5-72B Instruct（多语言强）
  - Mistral Large
- **调用方式：** 优先使用 Together AI / Groq / Fireworks 等托管 API（比自己部署便宜且稳定）

### 陪审员 C — 云端高阶模型 (Cloud Premium)

- **定位：** 基座能力最强的商业闭源模型，速度快、成本相对可控
- **优势：** 跨语言理解最强，复杂推理最稳，作为陪审团的"定海神针"
- **候选模型：**
  - Claude 3.5 Haiku（首选：快、便宜、多语言好）
  - Gemini 2.5 Flash（多语言原生支持，上下文窗口大）
  - GPT-4o-mini（覆盖面广，备选）
- **调用方式：** 通过各厂商 API 调用

### 陪审团统一输出格式

三位陪审员必须使用统一的 JSON 格式输出，包含推理过程：

```json
{
  "violation": true,
  "category": "hate_speech",
  "confidence": 0.85,
  "reasoning": "原文使用印尼语俚语 'bangsat' 并配合上下文攻击特定族群，结合印尼网络文化中该词的贬损含义，判定为仇恨言论。",
  "language": "id",
  "model": "juror_a",
  "model_name": "IndoBERT-hate-speech"
}
```

**违规类别定义：**
- `hate_speech` — 针对种族、宗教、性别、性取向等的仇恨言论
- `violence` — 暴力威胁、恐怖主义内容
- `adult` — 色情、性暗示内容
- `fraud` — 诈骗、钓鱼、虚假信息
- `illegal` — 违法内容（毒品交易、武器贩卖等）
- `political` — 煽动颠覆、极端政治敏感（视国家法律而定）
- `none` — 不违规

**约束：**
- `confidence` 为 0.0~1.0 的浮点数
- `reasoning` 必须用英语书写（便于法官模型统一审阅），引用原文片段时保留原语言
- 如果模型对某语言支持不足导致无法判断，`violation` 设为 `null`，`confidence` 为 0.0，reasoning 中说明原因

---

## 1. 爬虫模块 (Crawler)

### 各国论坛来源（实际验证 2026-04）

| 国家 | 论坛/平台 | 状态 | 语种 |
|------|-----------|------|------|
| 泰国 | Pantip (pantip.com) | ✓ 已验证 | 泰语 |
| 新加坡 | HardwareZone (forums.hardwarezone.com.sg) | ✓ 已验证 | 英语 |
| 印度尼西亚 | Kompasiana (kompasiana.com) | ✓ 已验证 | 印尼语 |
| 土耳其 | Uludağ Sözlük (uludagsozluk.com) | ✓ 已验证 | 土耳其语 |
| 墨西哥 | Reddit r/mexico (old.reddit.com) | ✓ 已验证 | 西班牙语 |
| 沙特阿拉伯 | Reddit r/saudiarabia (old.reddit.com) | ✓ 已验证 | 阿拉伯语 |
| 巴西 | Reddit r/brasil (old.reddit.com) | ✓ 已验证 | 葡萄牙语 |
| 南非 | Reddit r/southafrica (old.reddit.com) | ✓ 已验证 | 英语 |

**不可达站点（被 Cloudflare/网络拦截）：**
- Kaskus (ID) — 429 限流
- Ekşi Sözlük (TR) — Cloudflare JS 挑战
- MyBroadband (ZA) — Cloudflare
- Adrenaline (BR) — Cloudflare

**需要代理：** 大部分站点从国内直连需要 HTTP 代理。在 `.env` 中设置 `PROXY_URL`。

### 技术要点

- 每个站点独立 spider，继承统一基类
- 反爬策略：IP 轮换池、请求频率控制（按站点调整）、UA 轮换
- 编码自动检测（部分非英文站点可能使用非 UTF-8 编码）
- 增量爬取：记录每个站点上次爬取时间，只拉新增内容
- Reddit 统一通过 Reddit API (PRAW) 抓取，不走网页爬取

```
crawler/
├── base_spider.py         # 爬虫基类，RawPost 统一数据模型
├── reddit_spider.py       # Reddit 专用（PRAW API，需凭据）
├── spiders/               # 各站点具体实现
│   ├── pantip.py          # 泰国 Pantip ✓
│   ├── hardwarezone.py    # 新加坡 HardwareZone ✓
│   ├── kompasiana.py      # 印尼 Kompasiana ✓
│   ├── uludagsozluk.py    # 土耳其 Uludağ Sözlük ✓
│   ├── old_reddit.py      # 无认证 Reddit 爬虫（MX/SA/BR/ZA）✓
│   ├── kaskus.py          # 印尼 Kaskus（被限流）
│   └── eksisozluk.py      # 土耳其 Ekşi Sözlük（Cloudflare 拦截）
├── middleware.py           # 反爬中间件（限速/UA轮换/代理/重试）
├── scheduler.py            # 定时调度
└── exporter.py             # RawPost → Parquet 导出
```

---

## 2. 数据管道 (Data Pipeline)

- **清洗：** HTML 去标签、保留纯文本、统一 Unicode 正规化（NFC/NFKC）
- **语种检测：** fasttext-langdetect 自动检测，置信度 < 0.7 的进入人工/LLM 复核
- **去重：** MinHash LSH 近似去重（允许微小的拼写/格式差异）
- **过滤：** 纯链接、纯 emoji、过短 (< 10 tokens)、过长 (> 3000 tokens) 标记为低质
- **存储：** 原始数据 Parquet 格式；元数据包含来源、时间戳、URL、语种、作者 hash

```
pipeline/
├── cleaner.py              # 文本清洗
├── language_detector.py    # 语种检测
├── dedup.py                # MinHash 去重
├── storage.py              # 读写接口
└── schema.py               # 数据模型（原数据 + 判断结果）
```

---

## 3. 陪审团执行模块 (Jury Executor)

- 三位陪审员对同一条内容并行调用
- A 走本地 gRPC/HTTP（本地推理服务），B 和 C 走外部 API
- 所有调用设 30s 超时，失败重试 1 次
- 结果收集后与原文一起打包送入法官模块
- 记录每次调用的延迟、token 消耗用于成本分析

```
jury/
├── juror_a.py              # 本地专才模型调用封装
├── juror_b.py              # 开源模型 API 调用封装（Together AI 等）
├── juror_c.py              # 云端模型 API 调用封装（Anthropic/Google）
├── prompt_builder.py       # 陪审员 prompt 构建（按语种微调模板）
├── graph.py                # LangGraph 编排（fan-out 并行 + 条件路由 + 投票仲裁）
└── executor.py             # 旧版并行执行（ThreadPoolExecutor，保留兼容）
```

---

## 4. 法官裁决模块 (Arbiter)

**法官的职责：** 审阅三位陪审员的 reasoning，结合原文做出最终裁决。

**裁决策略（分阶段）：**

### 阶段一：结构化投票（初期，无标注数据）

- 三位陪审员各 1 票，多数决定
- 若 A 和 C 一致、B 不一致 → 取 A+C（专才+云端一致性高）
- 若三人各执一词 → 标记为 `disputed`，进入人工复审队列
- 加权规则：已知某模型在特定语种上准确率更高时，权重上调

### 阶段二：LLM 终审法官（有一定数据积累后）

- 将原文 + 三位陪审员的完整 reasoning 发送给法官模型
- 法官模型（推荐 Claude Opus 4 或 GPT-4o）做出终审裁决
- 法官需输出：最终判断、采纳了哪位陪审员的意见、原因
- 法官 prompt 重点：
  - 要求权衡三位陪审员的推理质量而非简单投票
  - 强调对当地文化/语言特性的考量
  - 输出结构化 JSON 便于追踪

### 法官输出格式：

```json
{
  "final_verdict": true,
  "category": "hate_speech",
  "confidence": 0.92,
  "adopted_juror": "juror_a",
  "adopted_reason": "陪审员 A 准确识别了印尼语俚语 'bangsat' 的贬损含义，且推理与原文上下文一致。陪审员 B（Llama）的推理忽略了印尼当地的用语习惯，陪审员 C 的判断正确但理由不如 A 充分。",
  "juror_agreement": "A:violation / B:clean / C:violation",
  "reasoning": "综合三位陪审员的意见，原文包含针对特定族群的侮辱性俚语，判定为仇恨言论。采纳陪审员 A 的意见，因为其对本地语言的敏感度最高。"
}
```

### 阶段三：数据飞轮

- 法官的终审结果累积为标注数据集
- 用标注数据微调各语种的陪审员 A 模型（替代现成小模型）
- 微调后的模型准确率上升，逐步减少对 C（高价模型）的依赖
- 同时训练一个轻量法官模型替代 LLM 法官

```
arbiter/
├── voting.py               # 阶段一：多数/加权投票
├── llm_arbiter.py          # 阶段二：LLM 终审法官
├── prompt_builder.py       # 法官 prompt 模板
└── metrics.py              # 陪审员准确率追踪、一致性分析
```

---

## 数据流总览

```
[定时任务触发]
       │
       ▼
  Spider 爬取 ──▶ 原始 HTML
       │
       ▼
  文本清洗 + 语种检测 + 去重
       │
       ▼
  结构化存储 (Parquet) ── content_id
       │
       ▼
  ┌─ 陪审员 A (本地专才) ────┐
  ├─ 陪审员 B (开源中坚) ────┤  并行
  └─ 陪审员 C (云端高阶) ────┘
       │
       ▼
  三位 reasoning 聚合
       │
       ├── 全票一致 → 直接采纳
       ├── 2:1 → 法官 LLM 终审
       └── 全不一致 → 法官 LLM 终审 + 人工抽检
       │
       ▼
  最终标注结果 ──▶ 标注数据集 ──▶ 微调陪审员 A
```

## 技术选型

| 组件 | 推荐方案 | 说明 |
|------|----------|------|
| 爬虫框架 | Scrapy | 成熟稳定，中间件生态好 |
| Reddit 抓取 | PRAW (Python Reddit API Wrapper) | Reddit 官方推荐 |
| 本地推理 | vLLM / llama.cpp | 部署陪审员 A |
| 开源模型 API | Together AI / Groq | 成本低，免运维 |
| 云端模型 API | litellm 统一调用 | 一套代码切换多厂商 |
| 数据存储 | Parquet (数据) + SQLite (元数据) | 前期简单，后期可切 PostgreSQL |
| 编排框架 | LangGraph | 陪审团并行 fan-out + 仲裁条件路由 |
| 异步框架 | asyncio + aiohttp | 并发 API 调用（备用） |
| 语种检测 | fasttext-langdetect | 176 语种，准确率高 |
| 去重 | datasketch (MinHash LSH) | 百万级数据去重 |

## 开发路径

```
Phase 1 ▸ 8 国爬虫全部跑通 ✓ (2026-04-29 已验证)
Phase 2 ▸ 陪审团三席对接 + 并行调用 + 结果收集 ← 当前阶段
Phase 3 ▸ 阶段一投票逻辑 + 阶段二法官 LLM 接入
Phase 4 ▸ 数据飞轮：标注积累 → 微调陪审员 A
```

## 运行方式

```bash
cp .env.example .env         # 填入代理和 API 凭据
pip install -r requirements.txt
python test_crawl.py          # 冒烟测试（无需联网）
python run_crawl.py 50        # 爬取 8 国 Reddit（需 API 凭据）

# 单个论坛爬虫测试
python -c "
from crawler.spiders.pantip import PantipSpider
for p in PantipSpider(limit=5).scrape():
    print(p.title)
"
```

## 关键设计决策

- [ ] 违规类别定义需要详细的标注指南（annotation guideline），按国家细化
- [ ] 各国的法律标准不同——初期按统一标准，后期是否分国家定制？
- [ ] 陪审员 A 的小模型：先找现成的 → 不够好就用法官产出的数据微调
- [ ] 法官模型轮换机制：建议每 N 条数据后换法官模型（Claude ↔ GPT-4o），防止单一模型系统性偏差
- [ ] 新加坡多语种混合内容处理——是否需要先做语种拆分再分别判断？
