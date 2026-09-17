"""All tests use isolated configuration, never developer broker credentials."""
import os

os.environ.update({
    "DERIV_APP_ID": "test", "DERIV_API_TOKEN": "test-no-trading",
    "DERIV_ACCOUNT_ID": "VRTC123", "DERIV_DEMO": "true",
    "LIVE_TRADING_ENABLED": "false", "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
    "SECRET_KEY": "test-signing-key-not-for-production", "ENVIRONMENT": "development", "DEBUG": "false",
    "NEWS_AUTO_SYNC": "false", "SENTRY_DSN": "", "TELEGRAM_BOT_TOKEN": "",
    "API_ADMIN_KEY_HASH": "", "API_OPERATOR_KEY_HASH": "", "API_VIEWER_KEY_HASH": "",
})
