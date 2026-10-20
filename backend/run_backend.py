"""Entry point used by PyInstaller (a frozen app cannot use `python -m app.main`)."""
from app.main import run

if __name__ == "__main__":
    run()
