"""Run the local Windows API with SQLite, without modifying .env.

    .venv-mt5/Scripts/python.exe run_local.py
"""
import os
import secrets
from pathlib import Path


def configure_local():
    backend = Path(__file__).resolve().parent
    os.chdir(backend)
    data = backend / "data"
    data.mkdir(exist_ok=True)
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///" + (data / "local.db").as_posix()
    os.environ["ENVIRONMENT"] = "development"
    os.environ["DEBUG"] = "false"
    os.environ["DERIV_API_TOKEN"] = ""
    os.environ.setdefault("DERIV_APP_ID", "")
    os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))
    os.environ["ACTIVE_SYMBOLS"] = '["1HZ75V"]'
    terminal = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'MetaTrader 5 Terminal' / 'terminal64.exe'
    if terminal.is_file():
        os.environ.setdefault('MT5_TERMINAL_PATH', str(terminal))


if __name__ == "__main__":
    configure_local()
    import uvicorn
    # Exactly one worker. Trading is started explicitly in the Strategy Lab.
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, workers=1)
