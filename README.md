# Colloation Data — 多语种内容合规审核系统

## 当前进展 (Updated 2026-05-11)

```
Phase 1 ▸ 8 国爬虫全部跑通 ✓
Phase 2 ▸ 陪审团三席对接 + 并行调用 + 结果收集 ✓
Phase 3 ▸ 阶段一投票逻辑 + 阶段二法官 LLM 接入 ✓
Phase 4 ▸ 数据飞轮：标注积累 → 微调陪审员 A ← 待启动
```

### 关键数字

| 指标 | 数量 |
|------|------|
| 原始爬取帖子 | ~33,000+ 条（8 国） |
| 陪审团批量判断 | 450 条（8 国混合） |
| 全流程终审 | 56 条（泰国 Pantip 试点） |
| 检出违规 | 7 / 56（仇恨言论为主） |
| 裁决一致性 | 全票 clean: 53.3%, 全票 violation: 0.2% |

### 爬虫覆盖状态

| 国家 | 论坛 | 语种 | 原始数据量 |
|------|------|------|-----------|
| 泰国 | Pantip | 泰语 | 3,443 |
| 新加坡 | HardwareZone | 英语 | 3,378 |
| 印度尼西亚 | Kompasiana | 印尼语 | 787 |
| 土耳其 | Uludağ Sözlük | 土耳其语 | 5,438 |
| 墨西哥 | Reddit r/mexico | 西班牙语 | 2,959 |
| 沙特阿拉伯 | Reddit r/saudiarabia | 阿拉伯语 | 10,162 |
| 巴西 | Reddit r/brasil | 葡萄牙语 | 7,467 |
| 南非 | Reddit r/southafrica | 英语 | 131 |
| — | Kaskus (ID) | — | 429 限流 |
| — | Ekşi Sözlük (TR) | — | Cloudflare 拦截 |

### 陪审团模型状态

| 语种 | 陪审员 A 模型 | 状态 | 说明 |
|------|-------------|------|------|
| en | twitter-roberta-base-offensive | ✅ 可用 | 英语攻击性内容检测 |
| pt | xlm-roberta-sentiment | △ 可用 | 多语言情感分析做代理检测 |
| th | typhoon2-safety-preview | ✅ 可用 | 泰语安全检测（21 个敏感话题） |
| es | beto-sentiment-analysis | △ 可用 | 西语情感分析做代理检测 |
| id | bert-base-indonesian | ⚠ 待微调 | Base model，分类头随机 |
| tr | bert-base-turkish | ⚠ 待微调 | Base model，分类头随机 |
| ar | arabert-v02 | ⚠ 待微调 | Base model，分类头随机 |

陪审员 B: Together AI (Llama 3.1 8B) / 陪审员 C: Anthropic Claude Haiku + Gemini Flash

### 法官裁决（已实现）

- **阶段一（投票）**: 多数/加权投票，无 API 成本，用于快速初筛
- **阶段二（LLM 终审）**: 法官模型审阅三位陪审员 reasoning，输出结构化 JSON 裁决
- 全票一致直接采纳，存在分歧时由法官终审
- 全不一致 → 标记 `disputed`，建议人工抽检

---

## 快速开始（5 分钟跑通）

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 API key
cp .env.example .env
# 编辑 .env，填入你需要的 LLM API key

# 3. 下载 Juror A 本地模型（约 12GB，一次性）
python download_models.py

# 4. 跑冒烟测试
python test_crawl.py          # 验证爬虫+清洗+语种检测+去重
python test_each_model.py     # 验证 7 个本地模型是否正常
python test_jury.py           # 验证陪审团+投票+仲裁流程（旧版）
python test_jury_graph.py     # 验证 LangGraph 编排（新版，推荐）
```

---

## 配置文件说明

所有配置在项目根目录的 **`.env`** 文件中。

### 必须配置（最少要填一个 LLM API key）

```bash
# 三大 LLM 厂商（按你实际用的填，不用全填）
ANTHROPIC_API_KEY=sk-ant-...     # Juror C 首选，法官模型
OPENAI_API_KEY=sk-...            # Juror C 备选
GOOGLE_API_KEY=...               # Juror C 备选
TOGETHER_API_KEY=...             # Juror B 首选（开源模型）

# Reddit API（只抓 Reddit 才需要）
REDDIT_CLIENT_ID=your_client_id
REDDIT_CLIENT_SECRET=your_client_secret
REDDIT_USER_AGENT=ColloationData/1.0
```

### 自定义 LLM 地址（代理 / 聚合 API / 本地部署）

```bash
# 如果你用的是 API 代理、OpenRouter、LiteLLM、本地 vLLM 等
# 填下面这些，留空就用各厂商默认地址

JUROR_B_BASE_URL=https://your-proxy.com/v1/chat/completions
JUROR_B_API_KEY=sk-proxy-key
JUROR_C_BASE_URL=https://your-proxy.com/v1/chat/completions
JUROR_C_API_KEY=sk-proxy-key
```

---

## 项目结构一览

```
Colloation_data/
│
├── .env                          ← ★ API key 放这里
├── .env.example                  ← 配置模板
├── config.py                     ← 所有配置项定义（Pydantic Settings）
│
├── requirements.txt              ← Python 依赖
├── download_models.py            ← 下载 Juror A 本地模型（首次运行一次）
│
├── models/                       ← 下载的模型文件（~12GB，.gitignore）
│   ├── en--twitter-roberta-offensive/
│   ├── pt--xlm-roberta-sentiment/
│   ├── th--typhoon2-safety/
│   ├── es--beto-sentiment/
│   ├── id--bert-base-indonesian/    ← base model，需微调
│   ├── tr--bert-base-turkish/       ← base model，需微调
│   └── ar--arabert-v02/            ← base model，需微调
│
├── data/                         ← 运行时产出的数据
│   ├── raw_bulk_csv/   ← 爬虫原始数据 (CSV，8 国)
│   ├── cleaned_original/ ← 清洗后数据 (CSV，8 国)
│   └── results/        ← 陪审团判断结果 (JSON + Parquet)
│
├── crawler/                      ← 爬虫模块 (Phase 1 ✓)
│   ├── base_spider.py            ← 爬虫基类 + RawPost 数据模型
│   ├── reddit_spider.py          ← Reddit PRAW 专用爬虫
│   ├── spiders/                  ← 各论坛具体实现
│   │   ├── pantip.py             ← 泰国 Pantip ✓
│   │   ├── hardwarezone.py       ← 新加坡 HardwareZone ✓
│   │   ├── kompasiana.py         ← 印尼 Kompasiana ✓
│   │   ├── uludagsozluk.py       ← 土耳其 Uludağ Sözlük ✓
│   │   ├── old_reddit.py         ← 无认证 Reddit (MX/SA/BR/ZA) ✓
│   │   ├── kaskus.py             ← 印尼 Kaskus（被限流）
│   │   └── eksisozluk.py         ← 土耳其 Ekşi Sözlük（CF 拦截）
│   ├── middleware.py             ← 反爬中间件（限速/UA轮换/代理）
│   ├── scheduler.py              ← 定时调度
│   └── exporter.py               ← RawPost → Parquet 导出
│
├── pipeline/                     ← 数据管道 (Phase 1.5 ✓)
│   ├── schema.py                 ← 数据模型（CleanedPost, JurorVerdict, FinalVerdict）
│   ├── cleaner.py                ← HTML去标签 / Unicode正规化 / 质量检查
│   ├── clean_v4.py               ← 增强清洗（专为批量爬取数据优化）
│   ├── language_detector.py      ← fasttext 语种检测
│   ├── dedup.py                  ← MinHash LSH 近似去重
│   └── storage.py                ← Parquet 读写
│
├── jury/                         ← 陪审团模块 (Phase 2 ✓)
│   ├── juror_a.py                ← 本地小模型（7语种，classify_direct）
│   ├── juror_b.py                ← 开源 LLM API（Together AI 等）
│   ├── juror_c.py                ← 云端 LLM API（Anthropic/Gemini/OpenAI）
│   ├── prompt_builder.py         ← 三席陪审员 prompt 模板
│   ├── graph.py                  ← LangGraph 编排（并行 fan-out + 投票 + 仲裁）
│   └── executor.py               ← 旧版并行执行（ThreadPoolExecutor，保留兼容）
│
├── arbiter/                      ← 法官裁决模块 (Phase 3 ✓)
│   ├── voting.py                 ← 阶段一：多数/加权投票
│   └── llm_arbiter.py            ← 阶段二：LLM 终审法官（结构化 JSON 输出）
│
├── test_crawl.py                 ← 测试：爬虫 + 清洗 + 语种 + 去重
├── test_juror_a.py               ← 测试：Juror A（mock / transformers / server）
├── test_each_model.py            ← 测试：每个语种模型单独调用
├── test_jury.py                  ← 测试：陪审团 + 投票 + 仲裁（旧版）
├── test_jury_graph.py            ← 测试：LangGraph 图 + 6 个 mock 场景
├── test_forum_spiders.py         ← 测试：各论坛爬虫
│
├── run_crawl.py                  ← 入口：Reddit 各国子版块爬取
├── run_jury_batch.py             ← 入口：批量陪审团判断（450 条）
├── run_full_pipeline.py          ← 入口：全流程（爬取→清洗→陪审团→裁决）
├── run_clean_v4.py               ← 入口：增强清洗
├── crawl_all.py                  ← 入口：所有论坛爬取 + 清洗 + 导出
│
└── CLAUDE.md                     ← 项目架构详细文档
```

---

## 常用操作

### 1. 下载/检查 Juror A 模型

```bash
python download_models.py            # 下载全部 7 个模型
python download_models.py en th      # 只下载指定语种
python download_models.py --check    # 查看下载状态
python download_models.py --list     # 列出所有可用模型
```

### 2. 测试 Juror A 单个模型

```bash
# 全部测试
python test_each_model.py

# 只测某个语种
python test_each_model.py th
python test_each_model.py en
```

### 3. 爬取数据

```bash
python test_forum_spiders.py          # 测试各论坛能否连通
python crawl_all.py 50                # 全部论坛各爬 50 条
python test_crawl.py                  # 跑通全流程（不需要凭据）
```

### 4. 运行陪审团 + 裁决（需要 API key）

```bash
python test_jury_graph.py             # LangGraph 图测试（6 个 mock 场景）
python run_jury_batch.py              # 批量陪审团判断（需要 API key）
python run_full_pipeline.py           # 全流程一键运行
```

### 5. 代码中调用

#### 推荐：LangGraph 一键调用（陪审团 + 投票 + 仲裁一步到位）

```python
import sys; sys.path.insert(0, '.')

from jury.graph import run_jury_graph

final = run_jury_graph(
    content_id="post-001",
    text="พวกมึงแม่งโง่ ไปตายซะ",
    language="th",
    country="TH",
    source="pantip",
    timeout=30.0,
)
# → FinalVerdict(final_verdict=True, category='hate_speech', ...)
print(final.final_verdict)  # True
```

#### 底层调用（可单独控制每个环节）

```python
import sys; sys.path.insert(0, '.')

# ── 只用 Juror A（本地模型，免费）──
from jury.juror_a import classify_direct
result = classify_direct('th', 'พวกมึงแม่งโง่ ไปตายซะ')
# → {'violation': True, 'category': 'hate_speech', 'confidence': 0.999, ...}

# ── 三席陪审团并行（需要 API key，旧版 API）──
from jury.executor import run_jury
result = run_jury(
    content_id="post-001",
    text="เนื้อหาที่ต้องการตรวจสอบ...",
    language="th",
    country="TH",
    source="pantip",
    timeout=30.0,
)
# → JuryResult(verdict_a=..., verdict_b=..., verdict_c=...)
print(result.agreement)  # "A:violation / B:clean / C:violation"

# ── 法官仲裁 ──
from arbiter.llm_arbiter import call_arbiter

final = call_arbiter(
    content_id="post-001",
    content="原始文本...",
    verdicts=result.all_verdicts,
    provider="anthropic",
)
```

---

## 依赖安装

```bash
pip install -r requirements.txt

# 如果 pt 模型报错，额外安装：
pip install sentencepiece protobuf
```
