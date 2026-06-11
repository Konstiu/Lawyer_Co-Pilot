"""
Central environment loading.

Import this module before reading environment variables from application code.
"""

from pathlib import Path

from dotenv import load_dotenv


def load_environment() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(dotenv_path=env_path, override=False)


load_environment()
