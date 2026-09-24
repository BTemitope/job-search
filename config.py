import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

NHS_JOBS_MIN_INTERVAL_SECONDS = float(os.getenv("NHS_JOBS_MIN_INTERVAL_SECONDS", "3"))
TRAC_MIN_INTERVAL_SECONDS = float(os.getenv("TRAC_MIN_INTERVAL_SECONDS", "5"))
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "14400"))  # default 4h — NHS vacancies stay open for weeks

ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "")
ADZUNA_MIN_INTERVAL_SECONDS = float(os.getenv("ADZUNA_MIN_INTERVAL_SECONDS", "3"))  # 25 req/min free-tier cap
ADZUNA_DAILY_CAP = int(os.getenv("ADZUNA_DAILY_CAP", "250"))  # free-tier daily cap

REED_API_KEY = os.getenv("REED_API_KEY", "")
REED_MIN_INTERVAL_SECONDS = float(os.getenv("REED_MIN_INTERVAL_SECONDS", "1"))

QUERY_EXPANSION_MAX_TERMS = int(os.getenv("QUERY_EXPANSION_MAX_TERMS", "3"))

DATABASE_PATH = BASE_DIR / os.getenv("DATABASE_PATH", "data/jobs.db")

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1")

PROFILE_PATH = BASE_DIR / os.getenv("PROFILE_PATH", "data/profile.yaml")

NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")

API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", "8000"))

USER_AGENT = "Mozilla/5.0 (compatible; personal-job-search-tool/0.1; +local use)"
