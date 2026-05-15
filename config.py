from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Reddit
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "ColloationData/1.0"

    # LLM
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    google_api_key: str = ""
    together_api_key: str = ""

    # Storage
    data_dir: Path = Path("./data")
    raw_dir: Path = Path("./data/raw")
    clean_dir: Path = Path("./data/clean")
    results_dir: Path = Path("./data/results")

    # LLM custom endpoints (支持代理、聚合 API、本地部署)
    juror_b_base_url: str = ""  # 留空则用默认提供商地址
    juror_c_base_url: str = ""  # 留空则用默认提供商地址
    juror_b_api_key: str = ""   # 留空则用对应提供商的 API key
    juror_c_api_key: str = ""   # 留空则用对应提供商的 API key
    juror_b_no_proxy: bool = False  # 绕过系统代理（直连 API 代理时用）
    juror_c_no_proxy: bool = False

    # Crawler defaults
    request_delay: float = 2.0  # seconds between requests
    crawl_limit: int = 100  # max posts per site per run
    juror_a_endpoint: str = "http://localhost:8080"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()

# Ensure data directories exist
for d in [settings.data_dir, settings.raw_dir, settings.clean_dir, settings.results_dir]:
    d.mkdir(parents=True, exist_ok=True)


# ── Country → Subreddit mapping ──────────────────────────────────────

COUNTRY_SUBREDDITS: dict[str, list[str]] = {
    "SG": ["singapore", "SingaporeRaw"],
    "ID": ["indonesia", "indonesian"],
    "TH": ["thailand", "thaithai"],
    "TR": ["turkey", "TurkeyJerky"],
    "SA": ["saudiarabia", "Arabs"],
    "BR": ["brasil", "Brazil", "futebol"],
    "MX": ["mexico", "mexicanfood", "espanolmexico"],
    "ZA": ["southafrica", "afrikaans"],
    "AE": ["dubai", "UAE", "abudhabi", "Emiratis",
           "DubaiPetrolHeads", "DubaiCentral", "DubaiGaming",
           "Ajman", "Sharjah", "RasAlKhaimah"],
    "PH": ["Philippines", "CasualPH", "ChikaPH", "phinvest"],
    "VN": ["VietNam", "Vietnamese", "TroChuyenLinhTinh"],
}

COUNTRY_NAMES: dict[str, str] = {
    "SG": "Singapore",
    "ID": "Indonesia",
    "TH": "Thailand",
    "TR": "Turkey",
    "SA": "Saudi Arabia",
    "BR": "Brazil",
    "MX": "Mexico",
    "ZA": "South Africa",
    "AE": "United Arab Emirates",
    "PH": "Philippines",
    "VN": "Vietnam",
}

# ── Forum spider configurations (non-Reddit) ─────────────────────────

FORUM_CONFIGS: dict[str, dict] = {
    "hardwarezone": {
        "country": "SG",
        "base_url": "https://forums.hardwarezone.com.sg",
        "language": ["en", "zh"],
    },
    "kaskus": {
        "country": "ID",
        "base_url": "https://www.kaskus.co.id",
        "language": ["id"],
    },
    "pantip": {
        "country": "TH",
        "base_url": "https://pantip.com",
        "language": ["th"],
    },
    "eksisozluk": {
        "country": "TR",
        "base_url": "https://eksisozluk.com",
        "language": ["tr"],
    },
    "mybroadband": {
        "country": "ZA",
        "base_url": "https://mybroadband.co.za/forum",
        "language": ["en"],
    },
}
