"""
config.py
────────────────────────────────────────────────────────────────────────────────
Application Configuration
────────────────────────────────────────────────────────────────────────────────

WHAT THIS DOES:
    Centralised configuration loaded from environment variables.
    Uses Pydantic BaseSettings for validation and type coercion.
    A single `settings` singleton is imported throughout the app.

    NEVER hardcode credentials. All secrets come from:
        - .env file (local dev)
        - Docker environment variables (staging)
        - AWS Secrets Manager / GitHub Actions Secrets (production)

SETUP:
    Copy .env.example to .env and fill in your values:
        cp .env.example .env

    Required fields (bot won't start without these):
        DERIV_APP_ID
        DERIV_API_TOKEN
        DATABASE_URL
        SECRET_KEY

.env.example:
    DERIV_APP_ID=12345
    DERIV_API_TOKEN=your_token_here
        DATABASE_URL=postgresql+asyncpg://postgres:password@db.<project-ref>.supabase.co:5432/postgres
    REDIS_URL=redis://localhost:6379/0
    SECRET_KEY=change_this_to_a_random_256_bit_secret
    ENVIRONMENT=development
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    All application settings loaded from environment / .env file.
    Pydantic validates types and raises clear errors on startup if required
    fields are missing.
    """

    # ── App ───────────────────────────────────────────────────────────────────
    APP_NAME:       str  = "Mean Reversion Bot"
    APP_VERSION:    str  = "1.0.0"
    ENVIRONMENT:    str  = "development"    # development | staging | production
    DEBUG:          bool = False
    LOG_LEVEL:      str  = "INFO"

    # ── Deriv API ─────────────────────────────────────────────────────────────
    DERIV_APP_ID:       str = Field(..., description="Deriv application ID")
    DERIV_API_TOKEN:    str = Field(..., description="Deriv trading API token (keep secret)")
    DERIV_DEMO:         bool = True         # True = demo account, False = real money
    DERIV_WS_ENDPOINT:  str = "wss://ws.derivws.com/websockets/v3"

    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL:   str = Field(
        ...,
        description="Supabase Postgres async URL: postgresql+asyncpg://user:password@host:5432/postgres"
    )
    DB_ECHO:        bool = False            # Log SQL queries (dev only)

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_URL:      str  = "redis://localhost:6379/0"
    REDIS_TTL_TICK: int  = 5               # Tick cache TTL seconds
    REDIS_TTL_CANDLE: int = 60             # Candle cache TTL seconds
    REDIS_TTL_SIGNAL: int = 30             # Signal cache TTL seconds

    # ── Auth / Security ───────────────────────────────────────────────────────
    SECRET_KEY:         str  = Field(..., description="JWT signing key — must be long random string")
    ACCESS_TOKEN_EXPIRE_MINUTES:  int  = 60
    REFRESH_TOKEN_EXPIRE_DAYS:    int  = 7
    ALGORITHM:          str  = "HS256"
    ALLOWED_ORIGINS:    list[str] = ["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:3000", "http://127.0.0.1:5173"]

    # ── Trading — Risk ────────────────────────────────────────────────────────
    RISK_PCT:               float = 0.01    # 1% per trade
    MAX_RISK_PCT:           float = 0.02    # 2% hard cap
    MAX_OPEN_POSITIONS:     int   = 3
    SL_ATR_MULTIPLIER:      float = 1.5
    TP_RR_RATIO:            float = 2.0
    MIN_CONFLUENCE_SCORE:   int   = 6
    DERIV_MULTIPLIER:       int   = 100
    DERIV_PRODUCT:          str   = "multiplier"  # multiplier | rise_fall | vanilla

    # ── Trading — Circuit Breaker ─────────────────────────────────────────────
    CB_MAX_CONSECUTIVE_LOSSES:  int   = 3
    CB_DAILY_DRAWDOWN_PCT:      float = 0.05    # 5%
    CB_WEEKLY_DRAWDOWN_PCT:     float = 0.10    # 10%
    CB_SINGLE_TRADE_LOSS_PCT:   float = 0.03    # 3%
    CB_PAUSE_HOURS_LOSSES:      float = 4.0
    CB_PAUSE_HOURS_API:         float = 0.5

    # ── Trading — Instruments ─────────────────────────────────────────────────
    ACTIVE_SYMBOLS:     list[str] = ["R_75"]
    PRIMARY_TIMEFRAME:  int       = 300     # M5 in seconds
    HTF_TIMEFRAME:      int       = 3600    # H1 for bias
    CANDLE_BUFFER_SIZE: int       = 500
    MIN_CANDLES_SIGNAL: int       = 60

    # ── Trading — Indicators ──────────────────────────────────────────────────
    ZSCORE_PERIOD:      int   = 20
    BB_PERIOD:          int   = 20
    BB_STD_DEV:         float = 2.0
    RSI_PERIOD:         int   = 14
    ATR_PERIOD:         int   = 14
    STOCH_K_PERIOD:     int   = 14
    SWING_LOOKBACK:     int   = 5
    HURST_MIN_CANDLES:  int   = 50

    # ── Alerts ────────────────────────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_CHAT_ID:   Optional[str] = None
    ALERT_EMAIL:        Optional[str] = None

    # ── Sentry ────────────────────────────────────────────────────────────────
    SENTRY_DSN:         Optional[str] = None

    # ── Validators ────────────────────────────────────────────────────────────

    @field_validator("ENVIRONMENT")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        allowed = {"development", "staging", "production"}
        if v not in allowed:
            raise ValueError(f"ENVIRONMENT must be one of {allowed}")
        return v

    @field_validator("RISK_PCT", "MAX_RISK_PCT")
    @classmethod
    def validate_risk(cls, v: float) -> float:
        if not 0 < v <= 0.10:
            raise ValueError("Risk percentage must be between 0 and 10%")
        return v

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v = v.upper()
        if v not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {allowed}")
        return v

    # ── Computed Properties ───────────────────────────────────────────────────

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT == "development"

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.TELEGRAM_BOT_TOKEN and self.TELEGRAM_CHAT_ID)

    @property
    def sentry_enabled(self) -> bool:
        return bool(self.SENTRY_DSN)

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
        "extra": "ignore",
    }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return the cached Settings singleton.
    The @lru_cache ensures .env is only read once on startup.

    Usage:
        from app.config import settings
    """
    return Settings()


# Module-level singleton — import this everywhere
settings: Settings = get_settings()
