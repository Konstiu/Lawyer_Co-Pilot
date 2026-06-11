#!/usr/bin/env python3
from __future__ import annotations

import os

import uvicorn

from app.config import load_environment


def main() -> None:
    load_environment()
    host = os.getenv("APP_HOST", "127.0.0.1")
    port = int(os.getenv("APP_PORT", "8000"))
    reload_enabled = os.getenv("APP_RELOAD", "false").lower() in {"1", "true", "yes", "on"}
    uvicorn.run("app.main:app", host=host, port=port, reload=reload_enabled)


if __name__ == "__main__":
    main()
