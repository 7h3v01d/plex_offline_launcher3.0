#!/usr/bin/env python3
# run.py
#
# Production entry point using Waitress (a pure-Python WSGI server).
# Use this instead of `python app.py` or Flask's dev server.
#
#   python run.py
#
# Or with Gunicorn (if you prefer):
#   gunicorn --workers 2 --bind 0.0.0.0:5000 "app:app"

import os
import sys

# Ensure src/ is on the path when run from the project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from waitress import serve

from src.app import app
from src.config import PORT
from src.logger import setup_logging
from src.config import LOG_LEVEL

log = setup_logging(LOG_LEVEL)

if __name__ == "__main__":
    log.info("Starting Plex Offline Launcher on http://0.0.0.0:%d", PORT)
    log.info("Press Ctrl+C to stop.")
    serve(
        app,
        host="0.0.0.0",
        port=PORT,
        threads=4,
        channel_timeout=120,
        cleanup_interval=30,
    )
